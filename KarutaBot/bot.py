import discord
import asyncio
import re
import random
import time
from datetime import datetime, timedelta
from config import KARUTA_ID, DROP_COOLDOWN_MIN, DROP_JITTER_MIN, DROP_JITTER_MAX

LU_COOLDOWN_SECS = 11  # k!lu has a 10s cooldown — we wait 11 to be safe

# Commands we track in k!reminders
REMINDER_KEYS = ["Daily", "Vote", "Drop", "Grab", "Work", "Visit"]


# ─────────────────────────────────────────────
#  Discord runner
# ─────────────────────────────────────────────
def run_discord_loop(app, token, channel_id):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.loop = loop
    app._last_lu_time = 0

    client = discord.Client()
    app.client = client

    @client.event
    async def on_ready():
        app.ui_log(f"✅ Logged in as {client.user.name}")
        app.ui_set_status(f"Online as {client.user.name}", online=True)
        loop.create_task(automation_loop(app, client, channel_id))

    async def runner():
        try:
            async with client:
                await client.start(token)
        except discord.LoginFailure:
            app.ui_log("❌ Invalid token.")
            app.ui_set_status("Invalid Token", online=False)
            app.app.root.after(0, app.stop_bot)
        except Exception:
            import traceback
            app.ui_log(f"❌ Error: {traceback.format_exc()}")
            app.ui_set_status("Error", online=False)

    loop.run_until_complete(runner())


# ─────────────────────────────────────────────
#  k!reminders parser
#  Returns dict: {"Daily": 0, "Vote": 3600, "Drop": 0, ...}
#  Value is seconds until ready (0 = ready now)
# ─────────────────────────────────────────────
async def fetch_reminders(app, client, channel):
    await channel.send("k!reminders")

    def check(m):
        return (m.channel.id == channel.id and
                m.author.id == KARUTA_ID and
                m.embeds)
    try:
        msg = await client.wait_for("message", check=check, timeout=12)
    except asyncio.TimeoutError:
        app.ui_log("⚠ k!reminders timed out")
        return {}

    result = {}
    for embed in msg.embeds:
        # Raw debug dump so we can see exact reminder format
        app.ui_log(f"[REM] title={embed.title!r}")
        app.ui_log(f"[REM] desc={str(embed.description or '')[:300]!r}")
        for fi, f in enumerate(embed.fields):
            app.ui_log(f"[REM] field[{fi}] name={f.name!r} value={f.value!r}")

        text = " ".join([
            str(embed.title or ""),
            str(embed.description or ""),
            " ".join(str(f.value) for f in embed.fields),
        ]).replace("**", "").replace("`", "")

        for key in REMINDER_KEYS:
            # Match "Daily is ready" or "Daily in 2 hours 30 minutes" etc.
            pattern = rf'{key}\s+(?:is\s+)?(ready|in\s+([\d\.]+)\s*(hour|minute|second)s?(?:\s+(\d+)\s*(minute|second)s?)?)'
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                if "ready" in m.group(1).lower():
                    result[key] = 0
                else:
                    result[key] = _parse_duration(m.group(0))
            else:
                result[key] = None  # not mentioned

    app.ui_log("📋 Reminders: " + ", ".join(
        f"{k}={'ready' if v == 0 else f'{int(v)}s' if v else '?'}"
        for k, v in result.items()
    ))

    # Update UI reminder labels
    app.app.root.after(0, lambda: app.update_reminders(result))
    return result


def _parse_duration(text):
    """Convert 'in `2 hours 30 minutes`' -> seconds. Strips backticks."""
    # Strip backtick formatting Karuta uses: `2 hours`
    text = text.replace("`", "")
    total = 0
    for num, unit in re.findall(r"([\d\.]+)\s*(hour|minute|second)", text, re.IGNORECASE):
        n = float(num)
        u = unit.lower()
        if u.startswith("h"):
            total += n * 3600
        elif u.startswith("m"):
            total += n * 60
        elif u.startswith("s"):
            total += n
    return int(total) if total else 0


# ─────────────────────────────────────────────
#  Main automation loop — one k!reminders check per drop cycle
# ─────────────────────────────────────────────
async def automation_loop(app, client, channel_id):
    channel = client.get_channel(int(channel_id))
    if not channel:
        app.ui_log("❌ Channel not found.")
        return

    while app.running:
        app.reset_daily_if_needed()

        # Check reminders once per cycle to update UI badges and run ready commands
        reminders = await fetch_reminders(app, client, channel)
        await asyncio.sleep(2)

        # ── Daily ──
        if reminders.get("Daily") == 0:
            await do_daily(app, client, channel)
            await asyncio.sleep(2)

        # ── Visit ──
        if reminders.get("Visit") == 0:
            await do_visit(app, client, channel)
            await asyncio.sleep(2)

        # ── Drop ──
        if app.drops_today >= app.max_drops_var.get():
            app.ui_log(f"⚠ Daily drop limit reached ({app.max_drops_var.get()}). Waiting...")
            await asyncio.sleep(600)
            continue

        await do_drop(app, client, channel)

        # Base cooldown from k!reminders Drop value (seconds), fall back to flat 30 min
        # Add random jitter between user-configured min and max
        base_secs = reminders.get("Drop") or (DROP_COOLDOWN_MIN * 60)
        jitter_min = getattr(app, "jitter_min_var", None)
        jitter_max = getattr(app, "jitter_max_var", None)
        j_min = (jitter_min.get() if jitter_min else DROP_JITTER_MIN) * 60
        j_max = (jitter_max.get() if jitter_max else DROP_JITTER_MAX) * 60
        if j_max < j_min:
            j_min, j_max = j_max, j_min  # swap if misconfigured
        jitter = random.uniform(j_min, j_max)
        delay  = base_secs + jitter

        app.next_drop_time = datetime.now() + timedelta(seconds=delay)
        rem_mins  = int(base_secs // 60)
        tot_mins  = int(delay // 60)
        tot_secs  = int(delay % 60)
        app.ui_log(f"⏱ Next drop in {tot_mins}m {tot_secs}s "
                   f"(cooldown {rem_mins}m + {int(jitter//60)}m jitter)")
        await asyncio.sleep(delay)


# ─────────────────────────────────────────────
#  Drop + grab
# ─────────────────────────────────────────────
async def do_drop(app, client, channel):
    app.reset_daily_if_needed()
    if app.drops_today >= app.max_drops_var.get():
        return

    try:
        await channel.send("k!drop")
        app.drops_today += 1
        app.ui_log(f"🃏 Dropped! ({app.drops_today}/{app.max_drops_var.get()} today)")
        app.app.root.after(0, app.update_drops_label)

        drop_msg = await wait_for_drop(client, channel)
        if not drop_msg:
            app.ui_log("⚠ No drop message detected.")
            return

        # OCR parse
        cards = None
        if drop_msg.attachments:
            from ocr import parse_drop_image, check_easyocr
            ok, _ = check_easyocr()
            if ok:
                viewer = None
                try:
                    from ocr_viewer import OCRViewer
                    viewer = OCRViewer(app.app.root)
                    viewer.set_status("Downloading drop image...")
                except Exception as e:
                    app.ui_log(f"⚠ Viewer error: {e}")
                cards = parse_drop_image(
                    drop_msg.attachments[0].url,
                    log_fn=app.ui_log,
                    viewer=viewer
                )
                if viewer and cards:
                    viewer.show_result(cards)

        if not cards:
            cards = parse_drop_embed(app, drop_msg)
        if not cards:
            app.ui_log("⚠ Couldn't parse cards.")
            return

        app.ui_log("📋 Cards: " + ", ".join(
            f"{c['name']} (#{c['print']})" for c in cards))

        # Wishlist lookup per card
        for card in cards:
            if card["print"] < 100:
                continue
            query = card["name"]
            if card.get("series"):
                query += f" {card['series']}"
            app.ui_log(f"🔎 Looking up: {query}")
            card["wishes"] = await lookup_wishes(app, client, channel, query)

        # Pick + grab
        best_idx = pick_best_card(app, cards)
        best     = cards[best_idx]
        emoji    = ["1️⃣", "2️⃣", "3️⃣"][best_idx]

        app.ui_log(
            f"⭐ Grabbing card {best_idx+1}: {best['name']} "
            f"(print: #{best['print']}, wishes: {best['wishes']})")
        await drop_msg.add_reaction(emoji)

        # Check burn eligibility
        await asyncio.sleep(3)
        await maybe_tag_burn(app, client, channel, best)

    except Exception:
        import traceback
        app.ui_log(f"❌ Drop failed: {traceback.format_exc()}")


# ─────────────────────────────────────────────
#  Wait for drop message
# ─────────────────────────────────────────────
async def wait_for_drop(client, channel, timeout=15):
    def check(m):
        return (m.channel.id == channel.id and
                m.author.id == KARUTA_ID and
                m.attachments and
                "dropping" in m.content.lower())
    try:
        return await client.wait_for("message", check=check, timeout=timeout)
    except asyncio.TimeoutError:
        return None


# ─────────────────────────────────────────────
#  k!lu with cooldown handling
# ─────────────────────────────────────────────
async def lookup_wishes(app, client, channel, card_name):
    # Enforce cooldown
    elapsed = time.time() - getattr(app, "_last_lu_time", 0)
    if elapsed < LU_COOLDOWN_SECS:
        wait = LU_COOLDOWN_SECS - elapsed
        app.ui_log(f"   ⏳ k!lu cooldown — waiting {wait:.1f}s")
        await asyncio.sleep(wait)

    await channel.send(f"k!lu {card_name}")
    app._last_lu_time = time.time()

    def check(m):
        return (m.channel.id == channel.id and
                m.author.id == KARUTA_ID and
                (m.embeds or "cannot use that command" in m.content.lower()))
    try:
        msg = await client.wait_for("message", check=check, timeout=15)

        # Cooldown error — parse exact seconds and retry
        if "cannot use that command" in msg.content.lower():
            secs_match = re.search(r'(\d+)\s*second', msg.content, re.IGNORECASE)
            wait_secs  = int(secs_match.group(1)) + 1 if secs_match else LU_COOLDOWN_SECS
            app.ui_log(f"   ⏳ k!lu cooldown from Karuta — waiting {wait_secs}s")
            await asyncio.sleep(wait_secs)
            await channel.send(f"k!lu {card_name}")
            app._last_lu_time = time.time()
            try:
                msg = await client.wait_for("message", check=check, timeout=15)
            except asyncio.TimeoutError:
                app.ui_log("⚠ k!lu retry timed out")
                return 0

        for embed in msg.embeds:
            parts = [str(embed.title or ""), str(embed.description or "")]
            for f in embed.fields:
                parts += [str(f.name or ""), str(f.value or "")]
            text  = " ".join(parts).replace("**", "")
            match = re.search(r'Wishlisted\s*[·:\-]?\s*([\d,]+)', text, re.IGNORECASE)
            if match:
                count = int(match.group(1).replace(",", ""))
                app.ui_log(f"   ♥ Wishlisted: {count}")
                return count

    except asyncio.TimeoutError:
        app.ui_log("⚠ k!lu timed out")

    return 0


# ─────────────────────────────────────────────
#  Burn tagging (no k!burn — safe)
# ─────────────────────────────────────────────
async def maybe_tag_burn(app, client, channel, card):
    if not (card.get("print", 99999) > 100 and card.get("wishes", 0) < 10):
        return

    app.ui_log(f"🔥 {card['name']} eligible for burn (#{card['print']}, "
               f"{card['wishes']} wishes) — tagging...")

    await channel.send("k!tag burn")

    def check(m):
        return (m.channel.id == channel.id and m.author.id == KARUTA_ID)
    try:
        msg = await client.wait_for("message", check=check, timeout=10)
        if "does not exist" in msg.content.lower():
            app.ui_log("   📌 Creating 'burn' tag...")
            await channel.send("k!tagcreate burn :fire:")
            await asyncio.sleep(2)
            await channel.send("k!tag burn")
            app.ui_log("   ✅ Tagged for burn.")
        else:
            app.ui_log("   ✅ Tagged for burn.")
    except asyncio.TimeoutError:
        app.ui_log("   ⚠ Tag response timed out")


# ─────────────────────────────────────────────
#  Daily
# ─────────────────────────────────────────────
async def do_daily(app, client, channel):
    app.ui_log("📅 Claiming daily...")
    await channel.send("k!daily")

    def check_msg(m):
        return m.channel.id == channel.id and m.author.id == KARUTA_ID

    def check_edit(before, after):
        return after.channel.id == channel.id and after.author.id == KARUTA_ID and after.components

    try:
        # Wait for Karuta's initial daily message
        msg = await client.wait_for("message", check=check_msg, timeout=10)

        if "already" in msg.content.lower():
            app.ui_log("   📅 Daily already claimed.")
            return

        # Log initial buttons
        if msg.components:
            for ri, row in enumerate(msg.components):
                for bi, btn in enumerate(row.children):
                    label = getattr(btn, "label", None) or getattr(btn, "emoji", "?")
                    app.ui_log(f"   [daily] button[{ri}][{bi}] = {label!r}")

        if not msg.components:
            app.ui_log(f"   📅 No buttons. Content: {msg.content[:80]!r}")
            return

        try:
            # Step 1: click the Quiz button (first button)
            quiz_btn = msg.components[0].children[0]
            await quiz_btn.click()
            app.ui_log("   📅 Clicked Quiz button, waiting for edit...")

            # Step 2: Karuta EDITS the message to show Yes/No buttons — listen for edit
            # discord.py passes (before, after) as two args to the check function
            def check_edit(before, after):
                return (after.id == msg.id and
                        after.channel.id == channel.id and
                        bool(after.components))

            before_msg, after_msg = await client.wait_for("message_edit", check=check_edit, timeout=15)

            # Log the edited message buttons
            if after_msg.components:
                for ri, row in enumerate(after_msg.components):
                    for bi, btn in enumerate(row.children):
                        label = getattr(btn, "label", None) or getattr(btn, "emoji", "?")
                        app.ui_log(f"   [daily edit] button[{ri}][{bi}] = {label!r}")
                # Click first button — Yes, No, whatever it is
                answer_btn = after_msg.components[0].children[0]
                await answer_btn.click()
                app.ui_log("   ✅ Daily answered!")
            else:
                app.ui_log("   ⚠ Edited message has no buttons")

        except asyncio.TimeoutError:
            app.ui_log("   ⚠ Timed out waiting for quiz edit")
        except Exception as e:
            app.ui_log(f"   ⚠ Daily button click failed: {e}")

    except asyncio.TimeoutError:
        app.ui_log("   ⚠ Daily timed out")


# Vote intentionally not automated — requires browser interaction


# ─────────────────────────────────────────────
#  Visit
# ─────────────────────────────────────────────
async def do_visit(app, client, channel):
    app.ui_log("🏛 Visiting shrine...")
    await channel.send("k!visit")
    def check(m):
        return m.channel.id == channel.id and m.author.id == KARUTA_ID
    try:
        msg = await client.wait_for("message", check=check, timeout=10)
        app.ui_log(f"   🏛 Visit: {msg.content[:80]}")
    except asyncio.TimeoutError:
        app.ui_log("   ⚠ Visit timed out")


# ─────────────────────────────────────────────
#  Parse drop embed (OCR fallback)
# ─────────────────────────────────────────────
def parse_drop_embed(app, message):
    cards = []
    try:
        for embed in message.embeds:
            for i, field in enumerate(embed.fields[:3]):
                name      = field.name.strip() if field.name else f"Card {i+1}"
                value     = str(field.value or "")
                match     = re.search(r'(\d+)\s*[·•\-]\s*\d', value)
                print_num = int(match.group(1)) if match else 99999
                cards.append({"name": name, "print": print_num, "wishes": 0, "index": i})
            if cards:
                break

        if not cards and message.embeds:
            desc   = str(message.embeds[0].description or "")
            names  = re.findall(r'\*\*(.+?)\*\*', desc)
            prints = re.findall(r'(\d+)\s*[·•\-]\s*\d', desc)
            for i, name in enumerate(names[:3]):
                print_num = int(prints[i]) if i < len(prints) else 99999
                cards.append({"name": name, "print": print_num, "wishes": 0, "index": i})

        if not cards:
            cards = [{"name": "Unknown", "print": 99999, "wishes": 0, "index": 0}]

    except Exception:
        import traceback
        app.ui_log(f"⚠ Embed parse error: {traceback.format_exc()}")
        cards = [{"name": "Unknown", "print": 99999, "wishes": 0, "index": 0}]

    return cards


# ─────────────────────────────────────────────
#  Card scoring
# ─────────────────────────────────────────────
def pick_best_card(app, cards):
    for i, card in enumerate(cards):
        if card["print"] < 100:
            app.ui_log(f"🔥 Auto-grabbing {card['name']} — ultra low print #{card['print']}!")
            return i

    max_print  = max(c["print"]  for c in cards) or 1
    max_wishes = max(c["wishes"] for c in cards) or 1

    best_score, best_idx = -1, 0
    for i, card in enumerate(cards):
        score = ((1 - card["print"] / max_print) + card["wishes"] / max_wishes) / 2
        if score > best_score:
            best_score, best_idx = score, i

    return best_idx


# ─────────────────────────────────────────────
#  Manual drop (called from UI button)
# ─────────────────────────────────────────────
async def do_drop_manual(app, client):
    channel = client.get_channel(int(app.channel_var.get().strip()))
    if channel:
        await do_drop(app, client, channel)

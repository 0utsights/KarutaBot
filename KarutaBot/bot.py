import discord
import asyncio
import re
import random
import time
from datetime import datetime, timedelta
from config import KARUTA_ID, DROP_COOLDOWN_MIN, DROP_JITTER_MIN, DROP_JITTER_MAX

LU_COOLDOWN_SECS = 11  # k!lu has a 10s cooldown — we wait 11 to be safe


# ─────────────────────────────────────────────
#  OCR correction — retry variants for k!lu
#  Handles common EasyOCR confusions:
#  W misread as N, u/v swapped mid-word
# ─────────────────────────────────────────────
def _make_lu_variants(name):
    """Return alternative query strings to retry if k!lu says not found."""
    def swap_uv(s):
        s = re.sub(r'(?<=[a-z])u(?=[a-z])', 'v', s)
        s = re.sub(r'(?<=[a-z])v(?=[a-z])', 'u', s)
        return s
    def swap_N_to_W(s):
        return re.sub(r'N([a-zA-Z])', r'W', s)

    variants = set()
    r1 = swap_uv(name)
    r2 = swap_N_to_W(name)
    variants.update([r1, r2, swap_uv(r2), swap_N_to_W(r1)])
    variants.discard(name)
    return list(variants)

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
            app.ui_log("❌ Invalid token — Discord rejected the login.")
            app.ui_log("   Make sure you copied the full token and haven't accidentally included extra characters.")
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

        # Fetch reminders at the top of every cycle
        reminders = await fetch_reminders(app, client, channel)
        await asyncio.sleep(2)

        # ── Daily ──
        if reminders.get("Daily") == 0:
            await do_daily(app, client, channel)
            await asyncio.sleep(2)

        # ── Work ──
        if reminders.get("Work") == 0:
            await do_work(app, client, channel)
            await asyncio.sleep(2)

        # ── Drop ──
        drop_cooldown = reminders.get("Drop")  # seconds remaining, 0 = ready, None = unknown

        if app.drops_today >= app.max_drops_var.get():
            app.ui_log(f"⚠ Daily drop limit reached ({app.max_drops_var.get()}). Waiting 10m...")
            await asyncio.sleep(600)
            continue

        if drop_cooldown and drop_cooldown > 0:
            # Drop not ready — sleep the cooldown then loop back to re-check everything
            jitter_min = getattr(app, "jitter_min_var", None)
            jitter_max = getattr(app, "jitter_max_var", None)
            j_min  = (jitter_min.get() if jitter_min else DROP_JITTER_MIN) * 60
            j_max  = (jitter_max.get() if jitter_max else DROP_JITTER_MAX) * 60
            if j_max < j_min:
                j_min, j_max = j_max, j_min
            jitter = random.uniform(j_min, j_max)
            delay  = drop_cooldown + jitter

            app.next_drop_time = datetime.now() + timedelta(seconds=delay)
            rem_mins = int(drop_cooldown // 60)
            tot_mins = int(delay // 60)
            tot_secs = int(delay % 60)
            app.ui_log(f"⏱ Drop on cooldown — next in {tot_mins}m {tot_secs}s "
                       f"(cooldown {rem_mins}m + {int(jitter//60)}m jitter)")
            await asyncio.sleep(delay)
            continue

        # Drop is ready — run it
        await do_drop(app, client, channel)

        # ── Visit ──
        if reminders.get("Visit") == 0:
            await do_visit(app, client, channel)
            await asyncio.sleep(2)

        # Re-fetch reminders after all commands so badges and sleep duration are accurate
        await asyncio.sleep(2)
        reminders = await fetch_reminders(app, client, channel)

        # Sleep until next drop (+ jitter)
        base_secs = reminders.get("Drop") or (DROP_COOLDOWN_MIN * 60)
        jitter_min = getattr(app, "jitter_min_var", None)
        jitter_max = getattr(app, "jitter_max_var", None)
        j_min  = (jitter_min.get() if jitter_min else DROP_JITTER_MIN) * 60
        j_max  = (jitter_max.get() if jitter_max else DROP_JITTER_MAX) * 60
        if j_max < j_min:
            j_min, j_max = j_max, j_min
        jitter = random.uniform(j_min, j_max)
        delay  = base_secs + jitter

        app.next_drop_time = datetime.now() + timedelta(seconds=delay)
        rem_mins = int(base_secs // 60)
        tot_mins = int(delay // 60)
        tot_secs = int(delay % 60)
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
                cards = parse_drop_image(
                    drop_msg.attachments[0].url,
                    log_fn=app.ui_log,
                )

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
            result = await lookup_wishes(app, client, channel, query)
            card["wishes"] = result  # None = lookup failed, 0 = found with 0 wishes

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
async def _send_lu(app, client, channel, card_name):
    """Send k!lu, handle cooldown errors, return the response message or None."""
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
                (m.embeds or "cannot use" in m.content.lower()
                 or "could not be found" in m.content.lower()))
    try:
        msg = await client.wait_for("message", check=check, timeout=15)
        # Cooldown error — parse seconds and retry once
        if "cannot use" in msg.content.lower():
            secs_match = re.search(r'(\d+)\s*second', msg.content, re.IGNORECASE)
            wait_secs  = int(secs_match.group(1)) + 1 if secs_match else LU_COOLDOWN_SECS
            app.ui_log(f"   ⏳ k!lu cooldown from Karuta — waiting {wait_secs}s")
            await asyncio.sleep(wait_secs)
            await channel.send(f"k!lu {card_name}")
            app._last_lu_time = time.time()
            msg = await client.wait_for("message", check=check, timeout=15)
        return msg
    except asyncio.TimeoutError:
        app.ui_log("⚠ k!lu timed out")
        return None


def _parse_wishes(msg):
    """Extract wishlist count from a k!lu response message. Returns int or None."""
    if not msg or not msg.embeds:
        return None
    for embed in msg.embeds:
        parts = [str(embed.title or ""), str(embed.description or "")]
        for f in embed.fields:
            parts += [str(f.name or ""), str(f.value or "")]
        text  = " ".join(parts).replace("**", "")
        match = re.search(r'Wishlisted\s*[·:\-]?\s*([\d,]+)', text, re.IGNORECASE)
        if match:
            return int(match.group(1).replace(",", ""))
    return None


async def lookup_wishes(app, client, channel, card_name):
    """
    Look up wishlist count for a card name.
    If k!lu says 'could not be found', automatically retry with OCR-correction
    variants (W/N swap, u/v swap) before giving up.
    Returns wishlist count, or None if lookup definitively failed (not found after retries).
    Returns 0 if lookup succeeded but card has 0 wishlists.
    """
    msg = await _send_lu(app, client, channel, card_name)

    # Check if Karuta said "not found"
    if msg and "could not be found" in msg.content.lower():
        app.ui_log(f"   ⚠ k!lu not found for {card_name!r} — trying OCR variants...")
        for variant in _make_lu_variants(card_name):
            app.ui_log(f"   🔄 Retrying with: {variant!r}")
            msg = await _send_lu(app, client, channel, variant)
            if msg and "could not be found" not in msg.content.lower():
                count = _parse_wishes(msg)
                if count is not None:
                    app.ui_log(f"   ♥ Wishlisted: {count} (via variant {variant!r})")
                    return count
        # All variants failed — return None to signal lookup failure
        app.ui_log(f"   ⚠ All variants failed — skipping burn check for safety")
        return None

    count = _parse_wishes(msg)
    if count is not None:
        app.ui_log(f"   ♥ Wishlisted: {count}")
        return count

    app.ui_log("   ♥ Wishlisted: 0")
    return 0


# ─────────────────────────────────────────────
#  Burn tagging (no k!burn — safe)
# ─────────────────────────────────────────────
async def maybe_tag_burn(app, client, channel, card):
    # None wishes means lookup failed — never burn-tag unknown cards
    if card.get("wishes") is None:
        app.ui_log(f"   ⏭ Skipping burn tag — wishlist unknown (lookup failed)")
        return
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
#  Work
# ─────────────────────────────────────────────
_SLOT_EMOJIS = {"🇦": "A", "🇧": "B", "🇨": "C", "🇩": "D", "🇪": "E"}


def _parse_jb(desc):
    """Parse k!jb embed description.
    Returns dict: {'A': 'Hisoka', 'B': 'Subaru Natsuki', ...}
    """
    slots = {}
    for line in desc.splitlines():
        for emoji, letter in _SLOT_EMOJIS.items():
            if line.startswith(emoji):
                # 🇦 Subaru Natsuki · **285** Effort · `Healthy`
                rest = line[len(emoji):].strip()
                name = rest.split("·")[0].strip()
                slots[letter] = name
                break
    return slots


def _parse_c_sort_effort(desc, limit=5):
    """Parse k!c sort=effort embed description.
    Returns list of {name, code} dicts, top `limit` by effort order.
    """
    cards = []
    for line in desc.splitlines():
        # Code: **`hnf6p7`**   Name: **Hisoka** (last bold token on the line)
        code_m = re.search(r'\*\*`([a-z0-9]{4,8})`\*\*', line)
        name_m = re.findall(r'\*\*([^`][^*]+)\*\*', line)
        if not code_m or not name_m:
            continue
        code = code_m.group(1)
        name = name_m[-1].strip()  # last bold segment is the character name
        cards.append({"name": name, "code": code})
        if len(cards) >= limit:
            break
    return cards


async def do_work(app, client, channel):
    app.ui_log("💼 Work: checking job board...")

    def check(m):
        return m.channel.id == channel.id and m.author.id == KARUTA_ID

    # ── Fetch k!jb ──
    await channel.send("k!jb")
    try:
        jb_msg = await client.wait_for("message", check=check, timeout=12)
    except asyncio.TimeoutError:
        app.ui_log("   ⚠ k!jb timed out")
        return

    jb_desc = ""
    for emb in jb_msg.embeds:
        jb_desc += str(emb.description or "")

    slots = _parse_jb(jb_desc)
    if not slots:
        app.ui_log("   ⚠ Could not parse k!jb — no slots found")
        return

    missing = [s for s in "ABCDE" if s not in slots]
    if missing:
        app.ui_log(f"   ⚠ Missing slots in k!jb: {missing}")

    app.ui_log(f"   📋 Current workers: " +
               ", ".join(f"{s}={slots.get(s, '?')}" for s in "ABCDE"))

    await asyncio.sleep(2)

    # ── Fetch k!c sort=effort ──
    await channel.send("k!c sort=effort")
    try:
        c_msg = await client.wait_for("message", check=check, timeout=12)
    except asyncio.TimeoutError:
        app.ui_log("   ⚠ k!c sort=effort timed out")
        return

    c_desc = ""
    for emb in c_msg.embeds:
        c_desc += str(emb.description or "")

    top5 = _parse_c_sort_effort(c_desc, limit=5)
    if len(top5) < 5:
        app.ui_log(f"   ⚠ Only found {len(top5)} cards in k!c sort=effort, need 5")
        if not top5:
            return

    top5_names = {c["name"] for c in top5}
    top5_by_name = {c["name"]: c["code"] for c in top5}
    app.ui_log(f"   🏆 Top 5 by effort: " + ", ".join(c["name"] for c in top5))

    # ── Find slots that need replacing ──
    current_names = set(slots.values())
    slots_to_replace = {s: n for s, n in slots.items() if n not in top5_names}
    replacements = [c for c in top5 if c["name"] not in current_names]

    if not slots_to_replace:
        app.ui_log("   ✅ All workers are already top 5 — running k!work")
    else:
        app.ui_log(f"   🔄 Replacing {len(slots_to_replace)} worker(s)...")
        for (slot, old_name), replacement in zip(slots_to_replace.items(), replacements):
            new_code = replacement["code"]
            new_name = replacement["name"]
            app.ui_log(f"   🔄 Slot {slot}: {old_name} → {new_name} (k!jobworker {slot} {new_code})")
            await channel.send(f"k!jobworker {slot} {new_code}")
            try:
                await client.wait_for("message", check=check, timeout=10)
            except asyncio.TimeoutError:
                app.ui_log(f"   ⚠ k!jobworker {slot} timed out")
            await asyncio.sleep(2)

    # ── Run k!work ──
    await asyncio.sleep(1)
    await channel.send("k!work")
    try:
        work_msg = await client.wait_for("message", check=check, timeout=12)
        full_text = work_msg.content
        for emb in work_msg.embeds:
            full_text += str(emb.description or "") + str(emb.title or "")

        if "do not have a permit" in full_text.lower():
            app.ui_log("   💳 No work permit — buying one...")
            await channel.send("k!buy work permit")
            try:
                buy_msg = await client.wait_for("message", check=check, timeout=10)
                app.ui_log(f"   💳 Buy result: {buy_msg.content[:100] or 'OK'}")
            except asyncio.TimeoutError:
                app.ui_log("   ⚠ k!buy work permit timed out")
            await asyncio.sleep(2)
            # Retry k!work after buying permit
            await channel.send("k!work")
            try:
                await client.wait_for("message", check=check, timeout=12)
                app.ui_log("   ✅ Work started")
            except asyncio.TimeoutError:
                app.ui_log("   ⚠ k!work retry timed out")
        else:
            app.ui_log("   ✅ Work started")
    except asyncio.TimeoutError:
        app.ui_log("   ⚠ k!work timed out")


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

            # Step 2: message is cached so message_edit will fire
            # Poll the message directly every second for up to 15s
            # as a reliable alternative to event-based listening
            after_msg = None
            for _ in range(15):
                await asyncio.sleep(1)
                try:
                    refreshed = await channel.fetch_message(msg.id)
                    if refreshed.components:
                        for ri, row in enumerate(refreshed.components):
                            for bi, btn in enumerate(row.children):
                                label = getattr(btn, "label", None) or getattr(btn, "emoji", "?")
                                app.ui_log(f"   [daily edit] button[{ri}][{bi}] = {label!r}")
                        after_msg = refreshed
                        break
                    else:
                        app.ui_log(f"   [daily] polling... no buttons yet")
                except Exception as e:
                    app.ui_log(f"   [daily] fetch error: {e}")

            if after_msg:
                answer_btn = after_msg.components[0].children[0]
                await answer_btn.click()
                app.ui_log("   ✅ Daily answered!")
            else:
                app.ui_log("   ⚠ Quiz buttons never appeared after 15s")

        except Exception as e:
            import traceback
            app.ui_log(f"   ⚠ Daily failed: {traceback.format_exc()}")

    except asyncio.TimeoutError:
        app.ui_log("   ⚠ Daily timed out")


# Vote intentionally not automated — requires browser interaction


# ─────────────────────────────────────────────
#  Visit helpers
# ─────────────────────────────────────────────
def _debug_visit_msg(app, tag, msg):
    """Log every detail of a message so we can identify energy format."""
    app.ui_log(f"   [visit:{tag}] content: {msg.content[:120]!r}")
    for ei, emb in enumerate(msg.embeds):
        app.ui_log(f"   [visit:{tag}] embed[{ei}] title={emb.title!r} desc={str(emb.description)[:300]!r}")
        for fi, field in enumerate(emb.fields):
            app.ui_log(f"   [visit:{tag}] embed[{ei}].field[{fi}] name={field.name!r} val={field.value!r}")
    for ri, row in enumerate(msg.components):
        for bi, btn in enumerate(row.children):
            lbl      = getattr(btn, "label", None) or ""
            emoji    = getattr(btn, "emoji", None)
            disabled = getattr(btn, "disabled", False)
            app.ui_log(f"   [visit:{tag}] btn[{ri}][{bi}] label={lbl!r} emoji={emoji} disabled={disabled}")


def _find_button(components, *label_substrings):
    """Return first button whose label contains any substring (case-insensitive). Includes disabled."""
    for row in components:
        for btn in row.children:
            lbl = (getattr(btn, "label", "") or "").lower()
            for sub in label_substrings:
                if sub.lower() in lbl:
                    return btn
    return None


def _find_emoji_button(components, *emoji_names):
    """Return first button whose emoji str-representation contains any of the given strings."""
    for row in components:
        for btn in row.children:
            emoji = getattr(btn, "emoji", None)
            if emoji is None:
                continue
            emoji_str = str(emoji)
            for name in emoji_names:
                if name in emoji_str:
                    return btn
    return None


def _find_check_button(components):
    """Return the confirm button — matches on 'buttonconfirm' in the custom emoji name/id.
    Karuta uses <:buttonconfirm:859308342479683584> as the confirm and
    <:buttoncancel:859308355847454720> as cancel — must target confirm specifically.
    """
    for row in components:
        for btn in row.children:
            emoji = getattr(btn, "emoji", None)
            if emoji is None:
                continue
            if "buttonconfirm" in str(emoji):
                return btn
    return None


def _parse_affection_points(msg):
    """Parse 'Affection Points · N' from embed description. Returns int or None."""
    for emb in msg.embeds:
        desc = str(emb.description or "")
        m = re.search(r'Affection Points\s*[·:]\s*\*{0,2}(\d+)\*{0,2}', desc, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


async def _poll_visit_msg(app, channel, msg_id, timeout=15):
    """Poll a message every second until it has components. Returns message or None."""
    for _ in range(timeout):
        await asyncio.sleep(1)
        try:
            refreshed = await channel.fetch_message(msg_id)
            _debug_visit_msg(app, "poll", refreshed)
            if refreshed.components:
                return refreshed
        except Exception as e:
            app.ui_log(f"   [visit] fetch error: {e}")
    return None


# ─────────────────────────────────────────────
#  Affection list parser
# ─────────────────────────────────────────────
def _parse_affectionlist_desc(desc):
    """Parse k!affectionlist embed description into a list of card dicts.

    Each entry looks like:
    `1`. [emojis] · `5 ■` · `18 AR` · `3 AP` · `nkkmpd` · **Mikasa Ackerman** · Series

    Returns list of {code, name, energy, ar, ap, score}
    """
    cards = []
    # Each numbered entry starts with `N`.
    for entry in re.split(r'(?=`\d+`\.)', desc):
        entry = entry.strip()
        if not entry:
            continue

        energy_m = re.search(r'`(\d+)\s*■`', entry)
        ar_m     = re.search(r'`(\d+)\s*AR`', entry)
        ap_m     = re.search(r'`(\d+)\s*AP`', entry)
        # Card code: short alphanumeric in backticks, appears after AP field
        # Extract all backtick tokens, code is the one that isn't a number or stat
        codes    = re.findall(r'`([a-z0-9]{4,8})`', entry)
        # Filter out stat tokens like "5 ■", "18 AR" etc — those have spaces/symbols
        # after stripping: what remains are pure alphanumeric codes
        pure_codes = [c for c in codes if re.fullmatch(r'[a-z0-9]+', c) and not c.isdigit()]
        name_m   = re.search(r'\*\*(.+?)\*\*', entry)

        if not (energy_m and pure_codes):
            continue

        energy = int(energy_m.group(1))
        ar     = int(ar_m.group(1)) if ar_m else 0
        ap     = int(ap_m.group(1)) if ap_m else 0
        code   = pure_codes[0]
        name   = name_m.group(1) if name_m else code
        score  = ar * 2 + ap  # 2 AP = 1 AR, so AR is worth 2x

        cards.append({"code": code, "name": name, "energy": energy,
                      "ar": ar, "ap": ap, "score": score})
    return cards


async def _fetch_affectionlist(app, client, channel):
    """Send k!affectionlist, handle pagination, return all parsed cards."""
    all_cards = []

    await channel.send("k!affectionlist")
    def check_al(m):
        return m.channel.id == channel.id and m.author.id == KARUTA_ID

    page = 1
    while True:
        try:
            al_msg = await client.wait_for("message", check=check_al, timeout=12)
        except asyncio.TimeoutError:
            app.ui_log("   ⚠ k!affectionlist timed out")
            break

        desc = ""
        for emb in al_msg.embeds:
            if emb.description:
                desc += str(emb.description)

        cards = _parse_affectionlist_desc(desc)
        all_cards.extend(cards)
        app.ui_log(f"   📋 Affectionlist page {page}: {len(cards)} characters parsed")
        for c in cards:
            app.ui_log(f"      {c['name']} ({c['code']}) — energy={c['energy']} AR={c['ar']} AP={c['ap']} score={c['score']}")

        # Check for a Next button to paginate
        next_btn = _find_button(al_msg.components, "next") if al_msg.components else None
        if next_btn and not getattr(next_btn, "disabled", False):
            try:
                await next_btn.click()
                page += 1
                await asyncio.sleep(1)
            except Exception as e:
                app.ui_log(f"   ⚠ Affectionlist next page failed: {e}")
                break
        else:
            break

    return all_cards


async def _fetch_tag_codes(app, client, channel, tag):
    """Send k!c tag=<tag>, paginate, return set of card codes found in the collection."""
    codes = set()
    await channel.send(f"k!c tag={tag}")

    def check(m):
        return m.channel.id == channel.id and m.author.id == KARUTA_ID

    page = 1
    while True:
        try:
            msg = await client.wait_for("message", check=check, timeout=12)
        except asyncio.TimeoutError:
            app.ui_log(f"   ⚠ k!c tag={tag} timed out (page {page})")
            break

        full_text = msg.content
        for emb in msg.embeds:
            full_text += str(emb.title or "") + str(emb.description or "")
            for f in emb.fields:
                full_text += str(f.value or "")

        if "The list is empty" in full_text:
            app.ui_log(f"   ⚠ Tag '{tag}' is empty or doesn't exist")
            break

        # Card codes appear as **`code`** in collection embeds
        found = re.findall(r'\*\*`([a-z0-9]{4,8})`\*\*', full_text)
        # Also catch bare backtick codes that may appear in description
        found += [c for c in re.findall(r'`([a-z0-9]{4,8})`', full_text)
                  if re.fullmatch(r'[a-z0-9]+', c) and not c.isdigit()]
        codes.update(found)
        app.ui_log(f"   📋 Tag page {page}: {len(found)} codes found ({len(codes)} total)")

        # Paginate via Next button
        next_btn = _find_button(msg.components, "next") if msg.components else None
        if next_btn and not getattr(next_btn, "disabled", False):
            try:
                await next_btn.click()
                page += 1
                await asyncio.sleep(1)
            except Exception as e:
                app.ui_log(f"   ⚠ Tag next page failed: {e}")
                break
        else:
            break

    app.ui_log(f"   🏷 Tag '{tag}' codes: {codes or 'none'}")
    return codes


def _rank_visit_cards(cards, tag_codes=None):
    """Return visit candidates sorted by priority.

    Energy ≥5 is required for affectionlist cards.
    If tag_codes provided:
      1. Tag cards not on affectionlist (unknown energy — visit to register them)
      2. Tag cards on affectionlist with energy ≥5, sorted by score desc
      3. Non-tag affectionlist cards with energy ≥5, sorted by score desc
    If no tag_codes:
      All affectionlist cards with energy ≥5, sorted by score desc.

    Each item in the returned list is either a card dict (from affectionlist)
    or a minimal dict {code, name, energy: None, _unregistered: True} for tag-only cards.
    """
    MIN_ENERGY = 5

    al_by_code = {c["code"]: c for c in cards}

    if tag_codes:
        # Phase 1: tag codes not on affectionlist at all
        unregistered = [
            {"code": code, "name": code, "energy": None, "score": 0, "_unregistered": True}
            for code in tag_codes
            if code not in al_by_code
        ]

        # Phase 2: tag codes on affectionlist with energy ≥5
        tag_eligible = sorted(
            [al_by_code[code] for code in tag_codes
             if code in al_by_code and al_by_code[code]["energy"] >= MIN_ENERGY],
            key=lambda c: c["score"], reverse=True
        )

        # Phase 3: non-tag affectionlist cards with energy ≥5
        other_eligible = sorted(
            [c for c in cards if c["code"] not in tag_codes and c["energy"] >= MIN_ENERGY],
            key=lambda c: c["score"], reverse=True
        )

        return unregistered + tag_eligible + other_eligible
    else:
        # No tag — all affectionlist cards with energy ≥5, best score first
        eligible = [c for c in cards if c["energy"] >= MIN_ENERGY]
        return sorted(eligible, key=lambda c: c["score"], reverse=True)


async def _check_card_owned(app, client, channel, code):
    """Send k!c code=<id> and return True if the card exists in the collection, False if empty."""
    await channel.send(f"k!c code={code}")

    def check(m):
        return m.channel.id == channel.id and m.author.id == KARUTA_ID

    try:
        msg = await client.wait_for("message", check=check, timeout=12)
    except asyncio.TimeoutError:
        app.ui_log(f"   ⚠ k!c code={code} timed out — skipping")
        return False

    # Check all text surfaces for the empty marker
    full_text = msg.content
    for emb in msg.embeds:
        full_text += str(emb.title or "") + str(emb.description or "")
        for f in emb.fields:
            full_text += str(f.value or "")

    if "The list is empty" in full_text:
        app.ui_log(f"   ⚠ {code} not in collection — skipping")
        return False

    app.ui_log(f"   ✅ {code} confirmed in collection")
    return True


# ─────────────────────────────────────────────
#  Visit
# ─────────────────────────────────────────────
async def do_visit(app, client, channel):
    # ── Determine which card to visit ──
    _visit_card_var = getattr(app, "visit_card_var", None)
    manual_code     = _visit_card_var.get().strip() if _visit_card_var else ""

    if manual_code:
        # Manual override set — skip affectionlist entirely
        card_code = manual_code
        app.ui_log(f"🏛 Visiting (manual code: {card_code})")
    else:
        # Auto-select via k!affectionlist (+ optional tag prioritisation)
        _visit_tag_var = getattr(app, "visit_tag_var", None)
        visit_tag      = _visit_tag_var.get().strip() if _visit_tag_var else ""

        # Fetch tag codes first if a tag is configured
        tag_codes = set()
        if visit_tag:
            app.ui_log(f"🏛 Fetching tag '{visit_tag}' card codes...")
            tag_codes = await _fetch_tag_codes(app, client, channel, visit_tag)
            await asyncio.sleep(2)

        app.ui_log("🏛 Fetching k!affectionlist...")
        al_cards = await _fetch_affectionlist(app, client, channel)
        await asyncio.sleep(1)

        ranked = _rank_visit_cards(al_cards, tag_codes if visit_tag else None)

        if not ranked:
            card_code = ""
            app.ui_log("🏛 No eligible cards found — running k!visit with no code")
        else:
            card_code = ""
            for i, candidate in enumerate(ranked):
                is_unreg = candidate.get("_unregistered", False)
                energy_str = "unregistered" if is_unreg else f"energy={candidate['energy']}"
                app.ui_log(f"   🔍 Checking ownership: {candidate['name']} ({candidate['code']}) [{energy_str}]")
                if i > 0:
                    app.ui_log("   ⏳ k!c cooldown — waiting 10s...")
                    await asyncio.sleep(10)
                else:
                    await asyncio.sleep(1)
                owned = await _check_card_owned(app, client, channel, candidate["code"])
                if owned:
                    card_code = candidate["code"]
                    score_str = f"score={candidate['score']}" if not is_unreg else "new to affectionlist"
                    app.ui_log(f"🏛 Selected: {candidate['name']} ({card_code}) — {energy_str} {score_str}")
                    break
            if not card_code:
                app.ui_log("🏛 No owned eligible cards found — running k!visit with no code")
    cmd       = f"k!visit {card_code}" if card_code else "k!visit"
    app.ui_log(f"🏛 Visiting shrine... ({cmd})")
    await channel.send(cmd)

    def check_msg(m):
        return m.channel.id == channel.id and m.author.id == KARUTA_ID

    try:
        msg = await client.wait_for("message", check=check_msg, timeout=10)
    except asyncio.TimeoutError:
        app.ui_log("   ⚠ Visit timed out waiting for initial message")
        return

    _debug_visit_msg(app, "initial", msg)

    if not msg.components:
        app.ui_log("   ⚠ Visit: no buttons on initial message")
        return

    # ── Detect which screen we're on and normalise to Talk/Actions screen ──
    # Case A: "Visit" + "Nevermind" buttons — new/unvisited card, need to confirm
    # Case B: "Talk" + "Actions" + ... buttons — already confirmed, go straight to loop
    if _find_button(msg.components, "visit"):
        visit_btn = _find_button(msg.components, "visit")
        try:
            await visit_btn.click()
            app.ui_log("   🏛 Clicked Visit (confirmation screen)")
        except Exception as e:
            app.ui_log(f"   ⚠ Visit: confirmation click failed: {e}")
            return

        msg = await _poll_visit_msg(app, channel, msg.id)
        if not msg:
            app.ui_log("   ⚠ Visit: timed out after clicking Visit")
            return
        _debug_visit_msg(app, "after_confirm", msg)

    # By now we should be on Talk/Actions/Date/Propose screen
    if not _find_button(msg.components, "talk"):
        app.ui_log("   ⚠ Visit: expected Talk button but not found — debug logged above")
        return

    # ── Main loop: Talk → Answer → repeat until energy out ──
    MAX_ROUNDS = 25
    for round_num in range(1, MAX_ROUNDS + 1):
        app.ui_log(f"   🏛 Visit round {round_num}")

        talk_btn = _find_button(msg.components, "talk")
        if not talk_btn:
            app.ui_log("   ✅ Visit: Talk button gone — energy exhausted")
            break
        if getattr(talk_btn, "disabled", False):
            app.ui_log("   ✅ Visit: Talk button disabled — energy exhausted")
            break

        try:
            await talk_btn.click()
            app.ui_log("   🏛 Clicked Talk")
        except Exception as e:
            app.ui_log(f"   ⚠ Visit: Talk click failed: {e}")
            break

        # Wait for question screen (answer buttons 1/2/3/4)
        msg = await _poll_visit_msg(app, channel, msg.id)
        if not msg or not msg.components:
            app.ui_log("   ⚠ Visit: timed out waiting for question screen")
            break

        _debug_visit_msg(app, f"round{round_num}_question", msg)

        # Click first available answer — doesn't matter which
        answer_btn = msg.components[0].children[0] if msg.components[0].children else None
        if not answer_btn:
            app.ui_log("   ⚠ Visit: no answer buttons found")
            break

        try:
            ans_label = getattr(answer_btn, "label", "?")
            await answer_btn.click()
            app.ui_log(f"   🏛 Answered: {ans_label!r}")
        except Exception as e:
            app.ui_log(f"   ⚠ Visit: answer click failed: {e}")
            break

        # Wait for result to resolve back to Talk/Actions screen
        await asyncio.sleep(1.5)
        try:
            msg = await channel.fetch_message(msg.id)
        except Exception as e:
            app.ui_log(f"   ⚠ Visit: post-answer fetch failed: {e}")
            break

        _debug_visit_msg(app, f"round{round_num}_result", msg)

        if not msg.components:
            app.ui_log("   ✅ Visit complete — no more buttons")
            break
    else:
        app.ui_log(f"   ⚠ Visit: hit safety cap of {MAX_ROUNDS} rounds")

    # ── Actions loop: Tell Joke while affection points >= 2 ──
    # After Talk energy runs out we're back on the Talk/Actions screen.
    # Enter Actions once, then loop :one: (Tell Joke) → ✓ until points < 2.
    # Exit with :speech_balloon: to return to the main screen.
    app.ui_log("   🎭 Checking affection points for Actions loop...")
    _debug_visit_msg(app, "pre_actions", msg)

    points = _parse_affection_points(msg)
    if points is None:
        app.ui_log("   ⚠ Couldn't parse affection points — skipping Actions loop")
    else:
        app.ui_log(f"   🎭 Affection points: {points}")

    if points is not None and points >= 2:
        # Enter Actions menu
        actions_btn = _find_button(msg.components, "actions")
        if not actions_btn:
            app.ui_log("   ⚠ Actions button not found — skipping Actions loop")
        else:
            try:
                await actions_btn.click()
                app.ui_log("   🎭 Clicked Actions")
            except Exception as e:
                app.ui_log(f"   ⚠ Actions click failed: {e}")
                actions_btn = None  # signal to skip loop

            if actions_btn:
                # Poll for Actions menu
                msg = await _poll_visit_msg(app, channel, msg.id)
                if not msg:
                    app.ui_log("   ⚠ Timed out waiting for Actions menu")
                else:
                    _debug_visit_msg(app, "actions_menu_enter", msg)

                    MAX_JOKES = 30
                    for joke_num in range(1, MAX_JOKES + 1):
                        if points is None or points < 2:
                            break

                        app.ui_log(f"   🎭 Tell Joke #{joke_num} (points={points})")

                        # Click :one: — Tell Joke
                        one_btn = _find_emoji_button(msg.components, "1️⃣", ":one:")
                        if not one_btn:
                            app.ui_log("   ⚠ :one: button not found — debug above")
                            break
                        try:
                            await one_btn.click()
                            app.ui_log("   🎭 Clicked Tell Joke (:one:)")
                        except Exception as e:
                            app.ui_log(f"   ⚠ Tell Joke click failed: {e}")
                            break

                        # Poll for confirmation screen (checkmark button)
                        msg = await _poll_visit_msg(app, channel, msg.id)
                        if not msg:
                            app.ui_log("   ⚠ Timed out waiting for confirm screen")
                            break
                        _debug_visit_msg(app, f"joke{joke_num}_confirm", msg)

                        # Click the checkmark/confirm button
                        check_btn = _find_check_button(msg.components)
                        if not check_btn:
                            app.ui_log("   ⚠ Confirm (✓) button not found — debug above")
                            break
                        try:
                            await check_btn.click()
                            app.ui_log("   🎭 Confirmed (✓)")
                        except Exception as e:
                            app.ui_log(f"   ⚠ Confirm click failed: {e}")
                            break

                        # Wait for result — should return to Actions menu
                        await asyncio.sleep(1.5)
                        try:
                            msg = await channel.fetch_message(msg.id)
                        except Exception as e:
                            app.ui_log(f"   ⚠ Post-joke fetch failed: {e}")
                            break
                        _debug_visit_msg(app, f"joke{joke_num}_result", msg)

                        points = _parse_affection_points(msg)
                        app.ui_log(f"   🎭 Points remaining: {points}")

                    # Exit Actions — click :speech_balloon: to go back to main screen
                    if msg and msg.components:
                        speech_btn = _find_emoji_button(msg.components, "💬", ":speech_balloon:")
                        if speech_btn:
                            try:
                                await speech_btn.click()
                                app.ui_log("   🎭 Clicked :speech_balloon: — exiting Actions")
                            except Exception as e:
                                app.ui_log(f"   ⚠ Exit click failed: {e}")
                        else:
                            app.ui_log("   ⚠ :speech_balloon: not found — may already be on main screen")

    app.ui_log("   ✅ Visit done")


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

    max_print  = max(c["print"] for c in cards) or 1
    # Treat None (failed lookup) as 0 for scoring purposes
    wish_vals  = [c["wishes"] or 0 for c in cards]
    max_wishes = max(wish_vals) or 1

    best_score, best_idx = -1, 0
    for i, card in enumerate(cards):
        w = card["wishes"] or 0
        score = ((1 - card["print"] / max_print) + w / max_wishes) / 2
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

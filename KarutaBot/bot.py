import discord
import asyncio
import re
from config import KARUTA_ID, DROP_COOLDOWN_MIN


# ─────────────────────────────────────────────
#  Discord runner
# ─────────────────────────────────────────────
def run_discord_loop(app, token, channel_id):
    """Called in a background thread. Runs the async discord loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.loop = loop

    client = discord.Client()
    app.client = client

    @client.event
    async def on_ready():
        app.ui_log(f"✅ Logged in as {client.user.name}")
        app.ui_set_status(f"Online as {client.user.name}", online=True)
        loop.create_task(drop_loop(app, client, channel_id))

    async def runner():
        try:
            async with client:
                await client.start(token)
        except discord.LoginFailure:
            app.ui_log("❌ Invalid token — please update your Discord token.")
            app.ui_set_status("Invalid Token", online=False)
            app.app.root.after(0, app.stop_bot)
        except Exception:
            import traceback
            err = traceback.format_exc()
            app.ui_log(f"❌ Error: {err}")
            app.ui_set_status("Error", online=False)

    loop.run_until_complete(runner())


# ─────────────────────────────────────────────
#  Drop loop
# ─────────────────────────────────────────────
async def drop_loop(app, client, channel_id):
    from datetime import datetime, timedelta
    import random

    while app.running:
        app.reset_daily_if_needed()

        if app.drops_today >= app.max_drops_var.get():
            app.ui_log(f"⚠ Daily limit of {app.max_drops_var.get()} drops reached. Waiting...")
            await asyncio.sleep(10 * 60)
            continue

        await do_drop(app, client)

        jitter  = random.uniform(0, app.jitter_var.get() * 60)
        delay   = DROP_COOLDOWN_MIN * 60 + jitter
        app.next_drop_time = datetime.now() + timedelta(seconds=delay)
        mins, secs = int(delay // 60), int(delay % 60)
        app.ui_log(f"⏱ Next drop in {mins}m {secs}s")
        await asyncio.sleep(delay)


# ─────────────────────────────────────────────
#  Single drop + grab
# ─────────────────────────────────────────────
async def do_drop(app, client):
    app.reset_daily_if_needed()
    if app.drops_today >= app.max_drops_var.get():
        return

    try:
        channel = client.get_channel(int(app.channel_var.get().strip()))
        if not channel:
            app.ui_log("❌ Channel not found. Check your Channel ID.")
            return

        await channel.send("k!drop")
        app.drops_today += 1
        app.ui_log(f"🃏 Dropped! ({app.drops_today}/{app.max_drops_var.get()} today)")
        app.app.root.after(0, app.update_drops_label)

        # Wait for the drop message
        drop_msg = await wait_for_drop(client, channel)
        if not drop_msg:
            app.ui_log("⚠ Couldn't find drop message, skipping grab.")
            return

        # Try OCR first, fall back to embed parsing if it fails
        cards = None
        if drop_msg.attachments:
            from ocr import parse_drop_image, check_easyocr
            ok, msg = check_easyocr()
            if ok:
                # Open live OCR viewer window
                viewer = None
                try:
                    from ocr_viewer import OCRViewer
                    viewer = OCRViewer(app.app.root)
                    viewer.set_status("Downloading drop image...")
                except Exception as e:
                    app.ui_log(f"⚠ Viewer failed to open: {e}")

                cards = parse_drop_image(
                    drop_msg.attachments[0].url,
                    log_fn=app.ui_log,
                    viewer=viewer
                )

                if viewer and cards:
                    viewer.show_result(cards)
            else:
                app.ui_log(f"⚠ Tesseract not available: {msg}")

        if not cards:
            cards = parse_drop_embed(app, drop_msg)
        if not cards:
            app.ui_log("⚠ Couldn't parse cards from drop.")
            return

        app.ui_log("📋 Cards: " + ", ".join([f"{c['name']} (#{c['print']})" for c in cards]))

        # Look up wishlist count for each card in order
        for card in cards:
            if card["print"] < 100:
                continue  # skip lookup, will instant grab
            query = card["name"]
            if card.get("series"):
                query += f" {card['series']}"
            app.ui_log(f"🔎 Looking up: {query}")
            wishes = await lookup_wishes(app, client, channel, query)
            card["wishes"] = wishes
            await asyncio.sleep(1.5)

        # Pick best and grab
        best_idx = pick_best_card(app, cards)
        best     = cards[best_idx]
        emoji    = ["1️⃣", "2️⃣", "3️⃣"][best_idx]

        app.ui_log(
            f"⭐ Grabbing card {best_idx+1}: {best['name']} "
            f"(print: {best['print']}, wishes: {best['wishes']})")
        await drop_msg.add_reaction(emoji)

    except Exception:
        import traceback
        app.ui_log(f"❌ Drop failed: {traceback.format_exc()}")


# ─────────────────────────────────────────────
#  Wait for the drop message
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
#  Parse drop embed (text fallback, OCR comes later)
# ─────────────────────────────────────────────
def parse_drop_embed(app, message):
    cards = []
    try:
        # Debug: log full embed structure
        for ei, embed in enumerate(message.embeds):
            app.ui_log(
                f"🔍 Embed {ei}: title={embed.title!r} "
                f"desc={str(embed.description)[:80]!r} "
                f"fields={len(embed.fields)} image={bool(embed.image)}")
            for fi, field in enumerate(embed.fields):
                app.ui_log(f"   Field {fi}: name={field.name!r} value={field.value!r}")

        # Try embed fields first
        for embed in message.embeds:
            for i, field in enumerate(embed.fields[:3]):
                name      = field.name.strip() if field.name else f"Card {i+1}"
                value     = str(field.value or "")
                match     = re.search(r'(\d+)\s*[·•\-]\s*\d', value)
                print_num = int(match.group(1)) if match else 99999
                cards.append({"name": name, "print": print_num, "wishes": 0, "index": i})
            if cards:
                break

        # Fallback: description
        if not cards and message.embeds:
            desc   = str(message.embeds[0].description or "")
            names  = re.findall(r'\*\*(.+?)\*\*', desc)
            prints = re.findall(r'(\d+)\s*[·•\-]\s*\d', desc)
            for i, name in enumerate(names[:3]):
                print_num = int(prints[i]) if i < len(prints) else 99999
                cards.append({"name": name, "print": print_num, "wishes": 0, "index": i})

        # Last resort
        if not cards:
            app.ui_log("⚠ No cards parsed from embed — OCR needed.")
            cards = [{"name": "Unknown", "print": 99999, "wishes": 0, "index": 0}]

    except Exception:
        import traceback
        app.ui_log(f"⚠ Parse error: {traceback.format_exc()}")
        cards = [{"name": "Unknown", "print": 99999, "wishes": 0, "index": 0}]

    return cards


# ─────────────────────────────────────────────
#  k!lu wishlist lookup
# ─────────────────────────────────────────────
async def lookup_wishes(app, client, channel, card_name):
    await channel.send(f"k!lu {card_name}")

    def check(m):
        return (m.channel.id == channel.id and
                m.author.id == KARUTA_ID and
                m.embeds)
    try:
        msg = await client.wait_for("message", check=check, timeout=12)
        for embed in msg.embeds:
            app.ui_log(f"🔍 k!lu response: desc={str(embed.description)[:100]!r}")
            text  = str(embed.description or "") + " ".join(str(f.value) for f in embed.fields)
            match = re.search(r'(\d+)\s*wish', text, re.IGNORECASE)
            if match:
                return int(match.group(1))
    except asyncio.TimeoutError:
        app.ui_log("⚠ k!lu timed out")
    return 0


# ─────────────────────────────────────────────
#  Card scoring
# ─────────────────────────────────────────────
def pick_best_card(app, cards):
    LOW_PRINT = 100

    # Instant grab for ultra low print
    for i, card in enumerate(cards):
        if card["print"] < LOW_PRINT:
            app.ui_log(f"🔥 Auto-grabbing {card['name']} — ultra low print #{card['print']}!")
            return i

    # Score: equal weight on print rank + wish count
    max_print  = max(c["print"]  for c in cards) or 1
    max_wishes = max(c["wishes"] for c in cards) or 1

    best_score, best_idx = -1, 0
    for i, card in enumerate(cards):
        print_score = 1 - (card["print"] / max_print)
        wish_score  = card["wishes"] / max_wishes
        total       = (print_score + wish_score) / 2
        if total > best_score:
            best_score, best_idx = total, i

    return best_idx

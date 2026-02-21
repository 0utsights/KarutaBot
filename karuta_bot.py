import discord
import asyncio
import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import json
import os
import requests
import hashlib
import uuid
import random
from datetime import datetime, timedelta

# ─────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────
SERVER_URL  = "https://karutabot-production.up.railway.app"
CONFIG_FILE = "config.json"

MAX_DROPS_PER_DAY  = 40
DROP_COOLDOWN_MIN  = 30
DROP_JITTER_MAX    = 6

C = {
    "bg":      "#2b2d31",
    "card":    "#313338",
    "dark":    "#1e1f22",
    "accent":  "#5865f2",
    "accent2": "#4752c4",
    "green":   "#23a55a",
    "red":     "#f23f43",
    "yellow":  "#f0b232",
    "text":    "#dbdee1",
    "muted":   "#949ba4",
    "white":   "#ffffff",
}

# ─────────────────────────────────────────────
#  Config file helpers
# ─────────────────────────────────────────────
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {"token": "", "channel_id": "", "max_drops": MAX_DROPS_PER_DAY}

def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f)

# ─────────────────────────────────────────────
#  License / session helpers
# ─────────────────────────────────────────────
def get_hwid():
    raw = str(uuid.getnode())
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

def validate_key(key):
    hwid = get_hwid()
    try:
        r = requests.post(f"{SERVER_URL}/auth", json={"key": key, "hwid": hwid}, timeout=5)
        data = r.json()
        return data.get("success"), data.get("reason", "Unknown error")
    except:
        return False, "Could not reach license server. Check your internet."

def start_heartbeat(key):
    hwid = get_hwid()
    import time
    while True:
        try:
            r = requests.post(f"{SERVER_URL}/heartbeat", json={"key": key, "hwid": hwid}, timeout=5)
            if not r.json().get("success"):
                os._exit(0)
        except:
            pass
        time.sleep(30)

def release_key(key):
    hwid = get_hwid()
    try:
        requests.post(f"{SERVER_URL}/release", json={"key": key, "hwid": hwid}, timeout=5)
    except:
        pass

# ─────────────────────────────────────────────
#  Key Entry Screen
# ─────────────────────────────────────────────
def show_key_screen():
    win = tk.Tk()
    win.title("Karuta Bot — Activate")
    win.geometry("360x220")
    win.resizable(False, False)
    win.configure(bg=C["bg"])
    win.eval("tk::PlaceWindow . center")

    tk.Label(win, text="🔑 Enter License Key", font=("Helvetica", 14, "bold"),
             bg=C["bg"], fg=C["text"]).pack(pady=(28, 8))

    key_var = tk.StringVar()
    entry = tk.Entry(win, textvariable=key_var, font=("Helvetica", 11),
                     bg=C["dark"], fg=C["text"], insertbackground=C["white"],
                     relief="flat", width=30)
    entry.pack(ipady=7, padx=30, fill="x")
    entry.focus()

    status = tk.Label(win, text="", font=("Helvetica", 9), bg=C["bg"], fg=C["red"])
    status.pack(pady=(6, 0))

    result = {"key": None}

    def try_activate(event=None):
        key = key_var.get().strip()
        if not key:
            return
        status.config(text="Validating...", fg=C["muted"])
        win.update()
        success, reason = validate_key(key)
        if success:
            result["key"] = key
            win.destroy()
        else:
            status.config(text=f"❌ {reason}", fg=C["red"])

    entry.bind("<Return>", try_activate)

    tk.Button(win, text="Activate", font=("Helvetica", 11, "bold"),
              bg=C["accent"], fg=C["white"], activebackground=C["accent2"],
              activeforeground=C["white"], relief="flat",
              padx=20, pady=7, cursor="hand2",
              command=try_activate).pack(pady=12)

    win.mainloop()
    return result["key"]

# ─────────────────────────────────────────────
#  Main Bot GUI
# ─────────────────────────────────────────────
class KarutaApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Karuta Bot")
        self.root.geometry("520x700")
        self.root.resizable(False, False)
        self.root.configure(bg=C["bg"])

        self.config         = load_config()
        self.client         = None
        self.loop           = None
        self.bot_thread     = None
        self.running        = False
        self.next_drop_time = None
        self.drops_today    = 0
        self.last_reset     = datetime.now().date()

        self._build_ui()

    def _build_ui(self):
        tk.Label(self.root, text="🃏 Karuta Bot", font=("Helvetica", 18, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(pady=(16, 2))
        tk.Label(self.root, text="Auto drop with randomized timing",
                 font=("Helvetica", 10), bg=C["bg"], fg=C["muted"]).pack(pady=(0, 12))

        # ── Settings card ──
        sf = tk.Frame(self.root, bg=C["card"])
        sf.pack(fill="x", padx=20, pady=6)

        token_row = tk.Frame(sf, bg=C["card"])
        token_row.grid(row=0, column=0, sticky="w", padx=12, pady=(10,2))
        tk.Label(token_row, text="Discord Token", font=("Helvetica", 9, "bold"),
                 bg=C["card"], fg=C["muted"]).pack(side="left")
        tk.Button(token_row, text="❓ How to get my token", font=("Helvetica", 8),
                  bg=C["accent"], fg=C["white"], activebackground=C["accent2"],
                  activeforeground=C["white"], relief="flat",
                  padx=8, pady=1, cursor="hand2",
                  command=self.show_token_help).pack(side="left", padx=(10,0))

        # Token expiry note with hoverable "why?"
        token_note_row = tk.Frame(sf, bg=C["card"])
        token_note_row.grid(row=0, column=1, sticky="w", padx=(0,12), pady=(10,2))
        tk.Label(token_note_row, text="Token is saved & lasts until you change your password.",
                 font=("Helvetica", 8), bg=C["card"], fg=C["muted"]).pack(side="left")
        why_btn = tk.Label(token_note_row, text=" why?", font=("Helvetica", 8, "underline"),
                           bg=C["card"], fg=C["accent"], cursor="hand2")
        why_btn.pack(side="left")
        self._add_tooltip(why_btn,
            "Discord tokens don't expire on their own.\n"
            "They only reset if you:\n"
            "• Change your password\n"
            "• Enable or disable 2FA\n"
            "• Click 'Log out of all devices'\n"
            "• Get suspended by Discord\n\n"
            "If your token stops working, just grab\n"
            "a new one using the ❓ button above.")
        self.token_var = tk.StringVar(value=self.config.get("token", ""))
        tk.Entry(sf, textvariable=self.token_var, show="•",
                 bg=C["dark"], fg=C["text"], insertbackground=C["text"],
                 relief="flat", font=("Helvetica", 10), width=42
                 ).grid(row=1, column=0, padx=12, pady=(0,8), ipady=6)

        tk.Label(sf, text="Channel ID", font=("Helvetica", 9, "bold"),
                 bg=C["card"], fg=C["muted"]).grid(row=2, column=0, sticky="w", padx=12, pady=(4,2))
        self.channel_var = tk.StringVar(value=self.config.get("channel_id", ""))
        tk.Entry(sf, textvariable=self.channel_var,
                 bg=C["dark"], fg=C["text"], insertbackground=C["text"],
                 relief="flat", font=("Helvetica", 10), width=42
                 ).grid(row=3, column=0, padx=12, pady=(0,12), ipady=6)

        # ── Options card ──
        opts = tk.Frame(self.root, bg=C["card"])
        opts.pack(fill="x", padx=20, pady=6)

        tk.Label(opts, text="MAX DROPS / DAY", font=("Helvetica", 8, "bold"),
                 bg=C["card"], fg=C["muted"]).grid(row=0, column=0, sticky="w", padx=12, pady=(10,2))
        self.max_drops_var = tk.IntVar(value=self.config.get("max_drops", MAX_DROPS_PER_DAY))
        tk.Spinbox(opts, from_=1, to=48, textvariable=self.max_drops_var,
                   width=5, bg=C["dark"], fg=C["text"],
                   relief="flat", font=("Helvetica", 10)
                   ).grid(row=1, column=0, padx=12, pady=(0,10), sticky="w", ipady=4)

        tk.Label(opts, text="JITTER (extra mins 0–N)", font=("Helvetica", 8, "bold"),
                 bg=C["card"], fg=C["muted"]).grid(row=0, column=1, sticky="w", padx=12, pady=(10,2))
        self.jitter_var = tk.IntVar(value=DROP_JITTER_MAX)
        tk.Spinbox(opts, from_=0, to=30, textvariable=self.jitter_var,
                   width=5, bg=C["dark"], fg=C["text"],
                   relief="flat", font=("Helvetica", 10)
                   ).grid(row=1, column=1, padx=12, pady=(0,10), sticky="w", ipady=4)

        tk.Label(opts, text="drops fire 30 to 30+N mins apart",
                 font=("Helvetica", 8), bg=C["card"], fg=C["muted"]
                 ).grid(row=1, column=2, padx=8, sticky="w")

        # ── Status card ──
        stf = tk.Frame(self.root, bg=C["card"])
        stf.pack(fill="x", padx=20, pady=6)

        tk.Label(stf, text="STATUS", font=("Helvetica", 8, "bold"),
                 bg=C["card"], fg=C["muted"]).grid(row=0, column=0, sticky="w", padx=12, pady=(10,2))
        self.status_dot = tk.Label(stf, text="⬤", font=("Helvetica", 10),
                                    bg=C["card"], fg=C["red"])
        self.status_dot.grid(row=1, column=0, sticky="w", padx=12)
        self.status_label = tk.Label(stf, text="Offline",
                                      font=("Helvetica", 10), bg=C["card"], fg=C["text"])
        self.status_label.grid(row=1, column=1, sticky="w", padx=4)

        tk.Label(stf, text="NEXT DROP", font=("Helvetica", 8, "bold"),
                 bg=C["card"], fg=C["muted"]).grid(row=0, column=2, sticky="w", padx=20, pady=(10,2))
        self.timer_label = tk.Label(stf, text="--:--",
                                     font=("Helvetica", 14, "bold"), bg=C["card"], fg=C["accent"])
        self.timer_label.grid(row=1, column=2, padx=20)

        tk.Label(stf, text="DROPS TODAY", font=("Helvetica", 8, "bold"),
                 bg=C["card"], fg=C["muted"]).grid(row=0, column=3, sticky="w", padx=20, pady=(10,2))
        self.drops_label = tk.Label(stf, text=f"0 / {MAX_DROPS_PER_DAY}",
                                     font=("Helvetica", 14, "bold"), bg=C["card"], fg=C["green"])
        self.drops_label.grid(row=1, column=3, padx=20)
        tk.Label(stf, text="", bg=C["card"]).grid(row=2, pady=6)

        # ── Buttons ──
        bf = tk.Frame(self.root, bg=C["bg"])
        bf.pack(pady=10)

        self.start_btn = tk.Button(bf, text="▶  Start",
                                    font=("Helvetica", 11, "bold"),
                                    bg=C["green"], fg=C["white"],
                                    activebackground="#1a8a47", activeforeground=C["white"],
                                    relief="flat", padx=24, pady=8, cursor="hand2",
                                    command=self.start_bot)
        self.start_btn.grid(row=0, column=0, padx=8)

        self.stop_btn = tk.Button(bf, text="■  Stop",
                                   font=("Helvetica", 11, "bold"),
                                   bg=C["red"], fg=C["white"],
                                   activebackground="#c0323a", activeforeground=C["white"],
                                   relief="flat", padx=24, pady=8, cursor="hand2",
                                   state="disabled", command=self.stop_bot)
        self.stop_btn.grid(row=0, column=1, padx=8)

        self.drop_btn = tk.Button(bf, text="🃏  Drop Now",
                                   font=("Helvetica", 11, "bold"),
                                   bg=C["accent"], fg=C["white"],
                                   activebackground=C["accent2"], activeforeground=C["white"],
                                   relief="flat", padx=16, pady=8, cursor="hand2",
                                   state="disabled", command=self.manual_drop)
        self.drop_btn.grid(row=0, column=2, padx=8)

        # ── Log ──
        tk.Label(self.root, text="ACTIVITY LOG", font=("Helvetica", 8, "bold"),
                 bg=C["bg"], fg=C["muted"]).pack(anchor="w", padx=22, pady=(6,2))

        self.log_box = scrolledtext.ScrolledText(self.root, height=12, width=60,
                                                  bg=C["dark"], fg=C["text"],
                                                  font=("Courier", 9),
                                                  relief="flat", state="disabled")
        self.log_box.pack(padx=20, pady=(0, 16))

        self._update_timer()

    # ── Helpers ───────────────────────────────
    def _add_tooltip(self, widget, text):
        """Show a tooltip popup on hover."""
        tooltip = None

        def on_enter(e):
            nonlocal tooltip
            x = widget.winfo_rootx() + 20
            y = widget.winfo_rooty() + 20
            tooltip = tk.Toplevel(widget)
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{x}+{y}")
            frame = tk.Frame(tooltip, bg=C["card"], bd=1, relief="solid",
                             highlightbackground=C["accent"], highlightthickness=1)
            frame.pack()
            tk.Label(frame, text=text, font=("Helvetica", 9),
                     bg=C["card"], fg=C["text"],
                     justify="left", padx=10, pady=8).pack()

        def on_leave(e):
            nonlocal tooltip
            if tooltip:
                tooltip.destroy()
                tooltip = None

        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    def show_token_help(self):
        import webbrowser
        win = tk.Toplevel(self.root)
        win.title("How to get your Discord Token")
        win.geometry("440x400")
        win.resizable(False, False)
        win.configure(bg=C["bg"])
        win.grab_set()  # modal

        tk.Label(win, text="🔑 Getting Your Discord Token",
                 font=("Helvetica", 13, "bold"), bg=C["bg"], fg=C["text"]).pack(pady=(20,4))
        tk.Label(win, text="Follow these steps carefully:",
                 font=("Helvetica", 9), bg=C["bg"], fg=C["muted"]).pack(pady=(0,12))

        steps = [
            ("Step 1", "Click the button below to open Discord in your browser"),
            ("Step 2", "Log into your Discord account if needed"),
            ("Step 3", "Press F12 on your keyboard to open DevTools"),
            ("Step 4", "Click the 'Network' tab at the top of DevTools"),
            ("Step 5", "Press Ctrl+R to reload the page"),
            ("Step 6", "In the filter box, type:  api"),
            ("Step 7", "Click any request in the list that appears"),
            ("Step 8", "Click 'Headers' tab → scroll down to find 'authorization'"),
            ("Step 9", "Copy that value and paste it into the Token box"),
        ]

        steps_frame = tk.Frame(win, bg=C["card"])
        steps_frame.pack(fill="x", padx=20, pady=(0,12))

        for i, (label, desc) in enumerate(steps):
            row = tk.Frame(steps_frame, bg=C["card"])
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=label, font=("Helvetica", 8, "bold"),
                     bg=C["card"], fg=C["accent"], width=7, anchor="w").pack(side="left")
            tk.Label(row, text=desc, font=("Helvetica", 9),
                     bg=C["card"], fg=C["text"], anchor="w").pack(side="left")

        tk.Button(win, text="🌐  Open Discord in Browser",
                  font=("Helvetica", 11, "bold"),
                  bg=C["accent"], fg=C["white"], activebackground=C["accent2"],
                  activeforeground=C["white"], relief="flat",
                  padx=20, pady=8, cursor="hand2",
                  command=lambda: webbrowser.open("https://discord.com/app")).pack(pady=(4,4))

        tk.Label(win, text="⚠  Never share your token with anyone.",
                 font=("Helvetica", 9, "bold"), bg=C["bg"], fg=C["red"]).pack(pady=(4,12))

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.config(state="normal")
        self.log_box.insert("end", f"[{timestamp}] {message}\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def set_status(self, text, online=False):
        self.status_label.config(text=text)
        self.status_dot.config(fg=C["green"] if online else C["red"])

    def _update_drops_label(self):
        limit = self.max_drops_var.get()
        color = C["green"] if self.drops_today < limit else C["red"]
        self.drops_label.config(text=f"{self.drops_today} / {limit}", fg=color)

    def _reset_daily_if_needed(self):
        today = datetime.now().date()
        if today != self.last_reset:
            self.drops_today = 0
            self.last_reset  = today
            self.root.after(0, lambda: self.log("🔄 Daily drop counter reset."))
            self.root.after(0, self._update_drops_label)

    def _next_delay(self):
        jitter = random.uniform(0, self.jitter_var.get() * 60)
        return DROP_COOLDOWN_MIN * 60 + jitter

    def _update_timer(self):
        if self.next_drop_time and self.running:
            remaining = self.next_drop_time - datetime.now()
            if remaining.total_seconds() > 0:
                mins, secs = divmod(int(remaining.total_seconds()), 60)
                self.timer_label.config(text=f"{mins:02d}:{secs:02d}")
            else:
                self.timer_label.config(text="Ready!")
        elif not self.running:
            self.timer_label.config(text="--:--")
        self.root.after(1000, self._update_timer)

    # ── Bot control ───────────────────────────
    def start_bot(self):
        token      = self.token_var.get().strip()
        channel_id = self.channel_var.get().strip()
        if not token or not channel_id:
            self.log("⚠ Please enter both Token and Channel ID.")
            return

        save_config({"token": token, "channel_id": channel_id,
                     "max_drops": self.max_drops_var.get()})
        self.running = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.drop_btn.config(state="normal")
        self.set_status("Connecting...", False)
        self.log("Starting bot...")

        self.bot_thread = threading.Thread(
            target=self._run_discord_loop,
            args=(token, int(channel_id)),
            daemon=True
        )
        self.bot_thread.start()

    def stop_bot(self):
        self.running = False
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.drop_btn.config(state="disabled")
        self.set_status("Offline", False)
        self.log("Bot stopped.")
        if self.client and self.loop:
            asyncio.run_coroutine_threadsafe(self.client.close(), self.loop)

    def manual_drop(self):
        if self.client and self.loop:
            asyncio.run_coroutine_threadsafe(self._do_drop(), self.loop)

    # ── Discord logic ─────────────────────────
    def _run_discord_loop(self, token, channel_id):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        self.client = discord.Client()

        @self.client.event
        async def on_ready():
            self.root.after(0, lambda: self.set_status(f"Online as {self.client.user.name}", True))
            self.root.after(0, lambda: self.log(f"✅ Logged in as {self.client.user.name}"))
            self.loop.create_task(self._drop_loop(channel_id))

        async def runner():
            try:
                async with self.client:
                    await self.client.start(token)
            except discord.LoginFailure:
                self.root.after(0, lambda: self.log("❌ Invalid token — please update your Discord token."))
                self.root.after(0, lambda: self.set_status("Invalid Token", False))
                self.root.after(0, self.stop_bot)
            except Exception as e:
                import traceback
                err = traceback.format_exc()
                self.root.after(0, lambda: self.log(f"❌ Error: {err}"))
                self.root.after(0, lambda: self.set_status("Error", False))

        self.loop.run_until_complete(runner())

    async def _drop_loop(self, channel_id):
        while self.running:
            self._reset_daily_if_needed()

            if self.drops_today >= self.max_drops_var.get():
                self.root.after(0, lambda: self.log(
                    f"⚠ Daily limit of {self.max_drops_var.get()} drops reached. Waiting..."))
                await asyncio.sleep(10 * 60)
                continue

            await self._do_drop()

            delay = self._next_delay()
            self.next_drop_time = datetime.now() + timedelta(seconds=delay)
            mins = int(delay // 60)
            secs = int(delay % 60)
            self.root.after(0, lambda m=mins, s=secs: self.log(
                f"⏱ Next drop in {m}m {s}s"))
            await asyncio.sleep(delay)

    async def _do_drop(self):
        self._reset_daily_if_needed()
        if self.drops_today >= self.max_drops_var.get():
            return
        try:
            channel = self.client.get_channel(int(self.channel_var.get().strip()))
            if not channel:
                self.root.after(0, lambda: self.log("❌ Channel not found. Check your Channel ID."))
                return

            await channel.send("k!drop")
            self.drops_today += 1
            self.root.after(0, lambda: self.log(
                f"🃏 Dropped! ({self.drops_today}/{self.max_drops_var.get()} today)"))
            self.root.after(0, self._update_drops_label)

            # Wait for Karuta to respond with the drop embed
            drop_msg = await self._wait_for_drop(channel)
            if not drop_msg:
                self.root.after(0, lambda: self.log("⚠ Couldn't find drop message, skipping grab."))
                return

            # Parse card names and prints from the embed
            cards = self._parse_drop_embed(drop_msg)
            if not cards:
                self.root.after(0, lambda: self.log("⚠ Couldn't parse cards from drop."))
                return

            self.root.after(0, lambda: self.log(f"📋 Cards: {', '.join([c['name'] for c in cards])}"))

            # Look up wishlist counts for each card
            for card in cards:
                wishes = await self._lookup_wishes(channel, card["name"])
                card["wishes"] = wishes
                await asyncio.sleep(1.5)  # small delay between lookups

            # Score and pick best card
            best_idx = self._pick_best_card(cards)
            best = cards[best_idx]
            emoji = ["1️⃣", "2️⃣", "3️⃣"][best_idx]

            self.root.after(0, lambda: self.log(
                f"⭐ Grabbing card {best_idx+1}: {best['name']} "
                f"(print: {best['print']}, wishes: {best['wishes']})"))

            await drop_msg.add_reaction(emoji)

        except Exception as e:
            import traceback
            err = traceback.format_exc()
            self.root.after(0, lambda: self.log(f"❌ Drop failed: {err}"))

    async def _wait_for_drop(self, channel, timeout=15):
        """Wait for Karuta's drop embed message containing the 3 cards."""
        KARUTA_ID = 646937666251915264
        def check(m):
            return (m.channel.id == channel.id and
                    m.author.id == KARUTA_ID and
                    m.embeds and
                    "dropping" in m.content.lower())
        try:
            msg = await self.client.wait_for("message", check=check, timeout=timeout)
            return msg
        except asyncio.TimeoutError:
            return None

    def _parse_drop_embed(self, message):
        """Parse card names and print numbers from Karuta drop embed."""
        cards = []
        try:
            for embed in message.embeds:
                if not embed.image:
                    continue
                # Cards come through as fields or description
                # Karuta drops show cards in embed fields
                for i, field in enumerate(embed.fields[:3]):
                    name = field.name.strip() if field.name else f"Card {i+1}"
                    value = field.value or ""
                    # Extract print number - appears as a number like "79701 · 1"
                    import re
                    print_match = re.search(r'(\d+)\s*[·•]\s*1', value)
                    print_num = int(print_match.group(1)) if print_match else 99999
                    cards.append({"name": name, "print": print_num, "wishes": 0, "index": i})

            # Fallback: try parsing from embed description
            if not cards and message.embeds:
                embed = message.embeds[0]
                desc = embed.description or ""
                import re
                # Look for card names in bold
                names = re.findall(r'\*\*(.+?)\*\*', desc)
                prints = re.findall(r'(\d+)\s*[·•]\s*1', desc)
                for i, name in enumerate(names[:3]):
                    print_num = int(prints[i]) if i < len(prints) else 99999
                    cards.append({"name": name, "print": print_num, "wishes": 0, "index": i})
        except Exception as e:
            self.root.after(0, lambda err=e: self.log(f"⚠ Parse error: {err}"))
        return cards

    async def _lookup_wishes(self, channel, card_name):
        """Send k!lu and parse the wishlist count from response."""
        KARUTA_ID = 646937666251915264
        await channel.send(f"k!lu {card_name}")

        def check(m):
            return (m.channel.id == channel.id and
                    m.author.id == KARUTA_ID and
                    m.embeds)
        try:
            msg = await self.client.wait_for("message", check=check, timeout=8)
            # Parse wish count from embed
            import re
            for embed in msg.embeds:
                text = str(embed.description or "") + str(embed.fields)
                match = re.search(r'(\d+)\s*wish', text, re.IGNORECASE)
                if match:
                    return int(match.group(1))
            return 0
        except asyncio.TimeoutError:
            return 0

    def _pick_best_card(self, cards):
        """Score each card and return index of best one."""
        LOW_PRINT_THRESHOLD = 100

        # Always grab if any card has print under threshold
        for i, card in enumerate(cards):
            if card["print"] < LOW_PRINT_THRESHOLD:
                self.root.after(0, lambda n=card["name"], p=card["print"]: self.log(
                    f"🔥 Auto-grabbing {n} — ultra low print #{p}!"))
                return i

        # Score: lower print = better, higher wishes = better
        # Normalize both to 0-1 scale then average
        prints = [c["print"] for c in cards]
        wishes = [c["wishes"] for c in cards]

        max_print = max(prints) or 1
        max_wishes = max(wishes) or 1

        best_score = -1
        best_idx = 0

        for i, card in enumerate(cards):
            # Lower print = higher score (invert)
            print_score = 1 - (card["print"] / max_print)
            # Higher wishes = higher score
            wish_score = card["wishes"] / max_wishes
            # Equal weight
            total = (print_score + wish_score) / 2

            if total > best_score:
                best_score = total
                best_idx = i

        return best_idx


# ─────────────────────────────────────────────
#  Entry point (called by launcher.py)
# ─────────────────────────────────────────────
def launch():
    key = show_key_screen()
    if not key:
        return

    t = threading.Thread(target=start_heartbeat, args=(key,), daemon=True)
    t.start()

    root = tk.Tk()
    app = KarutaApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: [release_key(key), root.destroy()])
    root.mainloop()


if __name__ == "__main__":
    launch()

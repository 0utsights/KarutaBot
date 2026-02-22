import tkinter as tk
from tkinter import scrolledtext
import threading
import webbrowser
from datetime import datetime

from config import C, MAX_DROPS_PER_DAY, DROP_JITTER_MAX, load_config, save_config
from license import start_heartbeat, release_key
from bot import run_discord_loop, do_drop


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

    # ─────────────────────────────────────────
    #  UI Construction
    # ─────────────────────────────────────────
    def _build_ui(self):
        tk.Label(self.root, text="🃏 Karuta Bot", font=("Helvetica", 18, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(pady=(16, 2))
        tk.Label(self.root, text="Auto drop with randomized timing",
                 font=("Helvetica", 10), bg=C["bg"], fg=C["muted"]).pack(pady=(0, 12))

        # ── Settings card ──
        sf = tk.Frame(self.root, bg=C["card"])
        sf.pack(fill="x", padx=20, pady=6)

        token_row = tk.Frame(sf, bg=C["card"])
        token_row.grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))
        tk.Label(token_row, text="Discord Token", font=("Helvetica", 9, "bold"),
                 bg=C["card"], fg=C["muted"]).pack(side="left")
        tk.Button(token_row, text="❓ How to get my token", font=("Helvetica", 8),
                  bg=C["accent"], fg=C["white"], activebackground=C["accent2"],
                  activeforeground=C["white"], relief="flat",
                  padx=8, pady=1, cursor="hand2",
                  command=self.show_token_help).pack(side="left", padx=(10, 0))

        token_note_row = tk.Frame(sf, bg=C["card"])
        token_note_row.grid(row=0, column=1, sticky="w", padx=(0, 12), pady=(10, 2))
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
                 ).grid(row=1, column=0, padx=12, pady=(0, 8), ipady=6)

        tk.Label(sf, text="Channel ID", font=("Helvetica", 9, "bold"),
                 bg=C["card"], fg=C["muted"]).grid(row=2, column=0, sticky="w", padx=12, pady=(4, 2))
        self.channel_var = tk.StringVar(value=self.config.get("channel_id", ""))
        tk.Entry(sf, textvariable=self.channel_var,
                 bg=C["dark"], fg=C["text"], insertbackground=C["text"],
                 relief="flat", font=("Helvetica", 10), width=42
                 ).grid(row=3, column=0, padx=12, pady=(0, 12), ipady=6)

        # ── Options card ──
        opts = tk.Frame(self.root, bg=C["card"])
        opts.pack(fill="x", padx=20, pady=6)

        tk.Label(opts, text="MAX DROPS / DAY", font=("Helvetica", 8, "bold"),
                 bg=C["card"], fg=C["muted"]).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))
        self.max_drops_var = tk.IntVar(value=self.config.get("max_drops", MAX_DROPS_PER_DAY))
        tk.Spinbox(opts, from_=1, to=48, textvariable=self.max_drops_var,
                   width=5, bg=C["dark"], fg=C["text"],
                   relief="flat", font=("Helvetica", 10)
                   ).grid(row=1, column=0, padx=12, pady=(0, 10), sticky="w", ipady=4)

        tk.Label(opts, text="JITTER (extra mins 0–N)", font=("Helvetica", 8, "bold"),
                 bg=C["card"], fg=C["muted"]).grid(row=0, column=1, sticky="w", padx=12, pady=(10, 2))
        self.jitter_var = tk.IntVar(value=DROP_JITTER_MAX)
        tk.Spinbox(opts, from_=0, to=30, textvariable=self.jitter_var,
                   width=5, bg=C["dark"], fg=C["text"],
                   relief="flat", font=("Helvetica", 10)
                   ).grid(row=1, column=1, padx=12, pady=(0, 10), sticky="w", ipady=4)

        tk.Label(opts, text="drops fire 30 to 30+N mins apart",
                 font=("Helvetica", 8), bg=C["card"], fg=C["muted"]
                 ).grid(row=1, column=2, padx=8, sticky="w")

        # ── Status card ──
        stf = tk.Frame(self.root, bg=C["card"])
        stf.pack(fill="x", padx=20, pady=6)

        tk.Label(stf, text="STATUS", font=("Helvetica", 8, "bold"),
                 bg=C["card"], fg=C["muted"]).grid(row=0, column=0, sticky="w", padx=12, pady=(10, 2))
        self.status_dot = tk.Label(stf, text="⬤", font=("Helvetica", 10),
                                   bg=C["card"], fg=C["red"])
        self.status_dot.grid(row=1, column=0, sticky="w", padx=12)
        self.status_label = tk.Label(stf, text="Offline",
                                     font=("Helvetica", 10), bg=C["card"], fg=C["text"])
        self.status_label.grid(row=1, column=1, sticky="w", padx=4)

        tk.Label(stf, text="NEXT DROP", font=("Helvetica", 8, "bold"),
                 bg=C["card"], fg=C["muted"]).grid(row=0, column=2, sticky="w", padx=20, pady=(10, 2))
        self.timer_label = tk.Label(stf, text="--:--",
                                    font=("Helvetica", 14, "bold"), bg=C["card"], fg=C["accent"])
        self.timer_label.grid(row=1, column=2, padx=20)

        tk.Label(stf, text="DROPS TODAY", font=("Helvetica", 8, "bold"),
                 bg=C["card"], fg=C["muted"]).grid(row=0, column=3, sticky="w", padx=20, pady=(10, 2))
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

        # ── Activity log ──
        tk.Label(self.root, text="ACTIVITY LOG", font=("Helvetica", 8, "bold"),
                 bg=C["bg"], fg=C["muted"]).pack(anchor="w", padx=22, pady=(6, 2))
        self.log_box = scrolledtext.ScrolledText(self.root, height=12, width=60,
                                                 bg=C["dark"], fg=C["text"],
                                                 font=("Courier", 9),
                                                 relief="flat", state="disabled")
        self.log_box.pack(padx=20, pady=(0, 16))

        self._update_timer()

    # ─────────────────────────────────────────
    #  UI helpers (called from bot.py via app.ui_*)
    # ─────────────────────────────────────────
    def ui_log(self, message):
        self.root.after(0, lambda: self.log(message))

    def ui_set_status(self, text, online=False):
        self.root.after(0, lambda: self.set_status(text, online))

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.config(state="normal")
        self.log_box.insert("end", f"[{timestamp}] {message}\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def set_status(self, text, online=False):
        self.status_label.config(text=text)
        self.status_dot.config(fg=C["green"] if online else C["red"])

    def update_drops_label(self):
        limit = self.max_drops_var.get()
        color = C["green"] if self.drops_today < limit else C["red"]
        self.drops_label.config(text=f"{self.drops_today} / {limit}", fg=color)

    def reset_daily_if_needed(self):
        today = datetime.now().date()
        if today != self.last_reset:
            self.drops_today = 0
            self.last_reset  = today
            self.ui_log("🔄 Daily drop counter reset.")
            self.root.after(0, self.update_drops_label)

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

    def _add_tooltip(self, widget, text):
        tooltip = None

        def on_enter(e):
            nonlocal tooltip
            x, y = widget.winfo_rootx() + 20, widget.winfo_rooty() + 20
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
        win = tk.Toplevel(self.root)
        win.title("How to get your Discord Token")
        win.geometry("440x400")
        win.resizable(False, False)
        win.configure(bg=C["bg"])
        win.grab_set()

        tk.Label(win, text="🔑 Getting Your Discord Token",
                 font=("Helvetica", 13, "bold"), bg=C["bg"], fg=C["text"]).pack(pady=(20, 4))
        tk.Label(win, text="Follow these steps carefully:",
                 font=("Helvetica", 9), bg=C["bg"], fg=C["muted"]).pack(pady=(0, 12))

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
        steps_frame.pack(fill="x", padx=20, pady=(0, 12))
        for label, desc in steps:
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
                  command=lambda: webbrowser.open("https://discord.com/app")).pack(pady=(4, 4))

        tk.Label(win, text="⚠  Never share your token with anyone.",
                 font=("Helvetica", 9, "bold"), bg=C["bg"], fg=C["red"]).pack(pady=(4, 12))

    # ─────────────────────────────────────────
    #  Bot control
    # ─────────────────────────────────────────
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
            target=run_discord_loop,
            args=(self, token, int(channel_id)),
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
            import asyncio
            asyncio.run_coroutine_threadsafe(self.client.close(), self.loop)

    def manual_drop(self):
        if self.client and self.loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(do_drop(self, self.client), self.loop)

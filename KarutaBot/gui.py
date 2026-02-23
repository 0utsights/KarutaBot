import tkinter as tk
from tkinter import scrolledtext
import threading
import webbrowser
from datetime import datetime

from config import (C, APP_NAME, APP_VERSION, MAX_DROPS_PER_DAY,
                    DROP_JITTER_MAX, load_config, save_config, default_account)
from license import start_heartbeat, release_key
from bot import run_discord_loop, do_drop


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _entry(parent, var, show=None, width=32):
    e = tk.Entry(parent, textvariable=var, show=show,
                 bg=C["dark"], fg=C["text"],
                 insertbackground=C["accent"],
                 selectbackground=C["accent2"],
                 relief="flat", font=("Segoe UI", 10),
                 width=width, bd=0,
                 highlightthickness=1,
                 highlightbackground=C["border"],
                 highlightcolor=C["accent"])
    return e

def _label(parent, text, size=9, bold=False, color=None, **kw):
    font = ("Segoe UI", size, "bold" if bold else "normal")
    return tk.Label(parent, text=text, font=font,
                    bg=kw.pop("bg", C["card"]),
                    fg=color or C["muted"], **kw)

def _btn(parent, text, command, color=None, width=None, small=False):
    bg = color or C["accent"]
    size = 9 if small else 10
    b = tk.Button(parent, text=text, command=command,
                  font=("Segoe UI", size, "bold"),
                  bg=bg, fg=C["dark"] if bg in (C["accent"], C["accent3"]) else C["white"],
                  activebackground=C["accent2"],
                  activeforeground=C["dark"],
                  relief="flat", cursor="hand2",
                  padx=14 if not small else 8,
                  pady=6 if not small else 3,
                  bd=0)
    if width:
        b.config(width=width)
    # Hover effect
    b.bind("<Enter>", lambda e: b.config(bg=C["accent2"]))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b

def _divider(parent, pady=4):
    tk.Frame(parent, bg=C["border"], height=1).pack(fill="x", pady=pady)

def _glass_frame(parent, **kw):
    """A card-like frame with a subtle border."""
    outer = tk.Frame(parent, bg=C["border"], bd=0)
    inner = tk.Frame(outer, bg=C["card2"], bd=0, padx=16, pady=12)
    inner.pack(fill="both", expand=True, padx=1, pady=1)
    return outer, inner


# ─────────────────────────────────────────────────────────────────────────────
#  AccountPanel — one panel per account in the scrollable list
# ─────────────────────────────────────────────────────────────────────────────
class AccountPanel:
    def __init__(self, parent, app, index, account_data):
        self.app   = app
        self.index = index
        self.data  = account_data

        # Session state (mirrors what bot.py needs)
        self.client         = None
        self.loop           = None
        self.bot_thread     = None
        self.running        = False
        self.next_drop_time = None
        self.drops_today    = 0
        self.last_reset     = datetime.now().date()

        self._build(parent)
        self._update_timer()

    def _build(self, parent):
        # Outer border frame
        self.outer = tk.Frame(parent, bg=C["border"], bd=0)
        self.outer.pack(fill="x", padx=16, pady=6)

        self.frame = tk.Frame(self.outer, bg=C["card2"], bd=0)
        self.frame.pack(fill="both", padx=1, pady=1)

        # ── Header row ──
        header = tk.Frame(self.frame, bg=C["card2"])
        header.pack(fill="x", padx=14, pady=(12, 6))

        self.status_dot = tk.Label(header, text="⬤", font=("Segoe UI", 8),
                                   bg=C["card2"], fg=C["red"])
        self.status_dot.pack(side="left", padx=(0, 6))

        self.name_var = tk.StringVar(value=self.data.get("name", f"Account {self.index+1}"))
        name_entry = tk.Entry(header, textvariable=self.name_var,
                              bg=C["card2"], fg=C["text"],
                              insertbackground=C["accent"],
                              relief="flat", font=("Segoe UI", 11, "bold"),
                              bd=0, highlightthickness=0, width=20)
        name_entry.pack(side="left")

        # Timer badge
        timer_frame = tk.Frame(header, bg=C["border"], bd=0)
        timer_frame.pack(side="right", padx=(0, 4))
        timer_inner = tk.Frame(timer_frame, bg=C["dark"], bd=0, padx=10, pady=2)
        timer_inner.pack(padx=1, pady=1)
        self.timer_label = tk.Label(timer_inner, text="--:--",
                                    font=("Segoe UI", 12, "bold"),
                                    bg=C["dark"], fg=C["accent"])
        self.timer_label.pack()

        # Drops badge
        drops_frame = tk.Frame(header, bg=C["border"], bd=0)
        drops_frame.pack(side="right", padx=(0, 8))
        drops_inner = tk.Frame(drops_frame, bg=C["dark"], bd=0, padx=10, pady=2)
        drops_inner.pack(padx=1, pady=1)
        self.drops_label = tk.Label(drops_inner,
                                    text=f"0 / {self.data.get('max_drops', MAX_DROPS_PER_DAY)}",
                                    font=("Segoe UI", 10, "bold"),
                                    bg=C["dark"], fg=C["accent3"])
        self.drops_label.pack()

        # ── Credentials row ──
        creds = tk.Frame(self.frame, bg=C["card2"])
        creds.pack(fill="x", padx=14, pady=(0, 8))

        # Token
        tk.Label(creds, text="TOKEN", font=("Segoe UI", 7, "bold"),
                 bg=C["card2"], fg=C["muted"]).grid(row=0, column=0, sticky="w")
        self.token_var = tk.StringVar(value=self.data.get("token", ""))
        te = _entry(creds, self.token_var, show="•", width=36)
        te.grid(row=1, column=0, sticky="ew", pady=(2, 6), ipady=5)

        # Channel ID
        tk.Label(creds, text="CHANNEL ID", font=("Segoe UI", 7, "bold"),
                 bg=C["card2"], fg=C["muted"]).grid(row=0, column=1, sticky="w", padx=(16, 0))
        self.channel_var = tk.StringVar(value=self.data.get("channel_id", ""))
        ce = _entry(creds, self.channel_var, width=18)
        ce.grid(row=1, column=1, sticky="ew", pady=(2, 6), padx=(16, 0), ipady=5)

        # ── Settings row ──
        settings = tk.Frame(self.frame, bg=C["card2"])
        settings.pack(fill="x", padx=14, pady=(0, 4))

        tk.Label(settings, text="MAX DROPS", font=("Segoe UI", 7, "bold"),
                 bg=C["card2"], fg=C["muted"]).grid(row=0, column=0, sticky="w")
        self.max_drops_var = tk.IntVar(value=self.data.get("max_drops", MAX_DROPS_PER_DAY))
        tk.Spinbox(settings, from_=1, to=48, textvariable=self.max_drops_var,
                   width=5, bg=C["dark"], fg=C["text"], relief="flat",
                   font=("Segoe UI", 10), buttonbackground=C["card"],
                   ).grid(row=1, column=0, sticky="w", pady=(2, 0), ipady=4)

        tk.Label(settings, text="JITTER (mins)", font=("Segoe UI", 7, "bold"),
                 bg=C["card2"], fg=C["muted"]).grid(row=0, column=1, sticky="w", padx=(20, 0))
        self.jitter_var = tk.IntVar(value=self.data.get("jitter", DROP_JITTER_MAX))
        tk.Spinbox(settings, from_=0, to=30, textvariable=self.jitter_var,
                   width=5, bg=C["dark"], fg=C["text"], relief="flat",
                   font=("Segoe UI", 10), buttonbackground=C["card"],
                   ).grid(row=1, column=1, sticky="w", padx=(20, 0), pady=(2, 0), ipady=4)

        tk.Label(settings, text="drops fire 30 to 30+jitter mins apart",
                 font=("Segoe UI", 8), bg=C["card2"], fg=C["muted"]
                 ).grid(row=1, column=2, padx=(12, 0), sticky="w")

        # ── Button row ──
        _divider(self.frame, pady=6)
        btns = tk.Frame(self.frame, bg=C["card2"])
        btns.pack(fill="x", padx=14, pady=(0, 12))

        self.start_btn = _btn(btns, "▶  Start",  self.start_bot, C["accent3"], small=True)
        self.start_btn.pack(side="left", padx=(0, 6))

        self.stop_btn = _btn(btns, "■  Stop", self.stop_bot, C["red"], small=True)
        self.stop_btn.pack(side="left", padx=(0, 6))
        self.stop_btn.config(state="disabled")

        self.drop_btn = _btn(btns, "🃏 Drop Now", self.manual_drop, C["accent"], small=True)
        self.drop_btn.pack(side="left", padx=(0, 6))
        self.drop_btn.config(state="disabled")

        remove_btn = _btn(btns, "✕ Remove", lambda: self.app.remove_account(self.index),
                          C["card"], small=True)
        remove_btn.config(fg=C["muted"])
        remove_btn.bind("<Enter>", lambda e: remove_btn.config(fg=C["red"]))
        remove_btn.bind("<Leave>", lambda e: remove_btn.config(fg=C["muted"]))
        remove_btn.pack(side="right")

        # ── Log box ──
        self.log_box = scrolledtext.ScrolledText(
            self.frame, height=5, width=70,
            bg=C["dark"], fg=C["text"],
            font=("Cascadia Code", 8) if self._font_exists("Cascadia Code") else ("Courier New", 8),
            relief="flat", state="disabled",
            insertbackground=C["accent"],
            selectbackground=C["accent2"],
        )
        self.log_box.pack(fill="x", padx=14, pady=(0, 14))

    def _font_exists(self, name):
        try:
            import tkinter.font as tkfont
            return name in tkfont.families()
        except:
            return False

    # ── UI helpers ──
    def ui_log(self, msg):
        self.app.root.after(0, lambda: self.log(msg))

    def ui_set_status(self, text, online=False):
        self.app.root.after(0, lambda: self._set_status(text, online))

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_box.config(state="normal")
        self.log_box.insert("end", f"[{ts}] {msg}\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def _set_status(self, text, online=False):
        self.status_dot.config(fg=C["accent3"] if online else C["red"])

    def update_drops_label(self):
        limit = self.max_drops_var.get()
        color = C["accent3"] if self.drops_today < limit else C["red"]
        self.drops_label.config(text=f"{self.drops_today} / {limit}", fg=color)

    def reset_daily_if_needed(self):
        today = datetime.now().date()
        if today != self.last_reset:
            self.drops_today = 0
            self.last_reset  = today
            self.ui_log("Daily drop counter reset.")
            self.app.root.after(0, self.update_drops_label)

    def _update_timer(self):
        if self.next_drop_time and self.running:
            remaining = self.next_drop_time - datetime.now()
            if remaining.total_seconds() > 0:
                mins, secs = divmod(int(remaining.total_seconds()), 60)
                self.timer_label.config(text=f"{mins:02d}:{secs:02d}")
            else:
                self.timer_label.config(text="NOW")
        else:
            self.timer_label.config(text="--:--")
        self.app.root.after(1000, self._update_timer)

    def get_data(self):
        return {
            "name":       self.name_var.get(),
            "token":      self.token_var.get().strip(),
            "channel_id": self.channel_var.get().strip(),
            "max_drops":  self.max_drops_var.get(),
            "jitter":     self.jitter_var.get(),
            "enabled":    True,
        }

    # ── Bot control ──
    def start_bot(self):
        token      = self.token_var.get().strip()
        channel_id = self.channel_var.get().strip()
        if not token or not channel_id:
            self.log("⚠ Please enter Token and Channel ID.")
            return
        self.running = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.drop_btn.config(state="normal")
        self._set_status("Connecting...", False)
        self.log("Starting...")
        self.app.save_all()
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
        self._set_status("Offline", False)
        self.log("Stopped.")
        if self.client and self.loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(self.client.close(), self.loop)

    def manual_drop(self):
        if self.client and self.loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(do_drop(self, self.client), self.loop)


# ─────────────────────────────────────────────────────────────────────────────
#  AeyoriApp — main window
# ─────────────────────────────────────────────────────────────────────────────
class KarutaApp:  # KarutaApp name kept for internal compatibility only
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME}  v{APP_VERSION}")
        self.root.geometry("780x820")
        self.root.minsize(700, 600)
        self.root.configure(bg=C["bg"])

        self.config   = load_config()
        self.panels   = []

        self._build_ui()
        self._load_accounts()

    # ─────────────────────────────────────────
    #  Layout
    # ─────────────────────────────────────────
    def _build_ui(self):
        # ── Top bar ──
        topbar = tk.Frame(self.root, bg=C["bg2"], height=52)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        # Logo / name
        logo_frame = tk.Frame(topbar, bg=C["bg2"])
        logo_frame.pack(side="left", padx=20)

        # Glowing dot
        tk.Label(logo_frame, text="◆", font=("Segoe UI", 14),
                 bg=C["bg2"], fg=C["accent"]).pack(side="left", padx=(0, 8))

        tk.Label(logo_frame, text=APP_NAME.upper(),
                 font=("Segoe UI", 15, "bold"),
                 bg=C["bg2"], fg=C["text"]).pack(side="left")

        tk.Label(logo_frame, text=f"  v{APP_VERSION}",
                 font=("Segoe UI", 8),
                 bg=C["bg2"], fg=C["muted"]).pack(side="left", pady=(6, 0))

        # Top-right buttons
        tr = tk.Frame(topbar, bg=C["bg2"])
        tr.pack(side="right", padx=16)

        _btn(tr, "+ Add Account", self.add_account, C["accent"], small=True).pack(side="left", padx=4)
        _btn(tr, "❓ Token Help",  self.show_token_help, C["card2"], small=True).pack(side="left", padx=4)

        # ── Thin accent line under topbar ──
        tk.Frame(self.root, bg=C["accent"], height=1).pack(fill="x")

        # ── Scrollable accounts area ──
        scroll_container = tk.Frame(self.root, bg=C["bg"])
        scroll_container.pack(fill="both", expand=True, pady=(8, 0))

        canvas = tk.Canvas(scroll_container, bg=C["bg"],
                           highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(scroll_container, orient="vertical",
                                 command=canvas.yview,
                                 bg=C["bg"], troughcolor=C["bg"],
                                 activebackground=C["accent"])
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self.accounts_frame = tk.Frame(canvas, bg=C["bg"])
        self.canvas_window  = canvas.create_window((0, 0), window=self.accounts_frame, anchor="nw")

        def _on_frame_configure(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
        def _on_canvas_configure(e):
            canvas.itemconfig(self.canvas_window, width=e.width)

        self.accounts_frame.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>",              _on_canvas_configure)
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        self.canvas = canvas

        # ── Status footer ──
        tk.Frame(self.root, bg=C["border"], height=1).pack(fill="x")
        footer = tk.Frame(self.root, bg=C["bg2"], height=28)
        footer.pack(fill="x")
        footer.pack_propagate(False)
        tk.Label(footer,
                 text=f"{APP_NAME} — automated card dropping",
                 font=("Segoe UI", 8), bg=C["bg2"], fg=C["muted"]).pack(side="left", padx=16)

    def _load_accounts(self):
        for acc in self.config.get("accounts", []):
            self._add_panel(acc)
        if not self.panels:
            self._add_panel(None)

    def _add_panel(self, data=None):
        idx   = len(self.panels)
        data  = data or default_account()
        panel = AccountPanel(self.accounts_frame, self, idx, data)
        self.panels.append(panel)
        return panel

    def add_account(self):
        self._add_panel()
        self.save_all()
        # Scroll to bottom
        self.canvas.after(100, lambda: self.canvas.yview_moveto(1.0))

    def remove_account(self, index):
        if len(self.panels) <= 1:
            return  # always keep at least one
        panel = self.panels[index]
        if panel.running:
            panel.stop_bot()
        panel.outer.destroy()
        self.panels.pop(index)
        # Re-index remaining panels
        for i, p in enumerate(self.panels):
            p.index = i
        self.save_all()

    def save_all(self):
        accounts = [p.get_data() for p in self.panels]
        save_config({"accounts": accounts})

    # ── Compatibility shims (license.py / main.py use app.root) ──
    def ui_log(self, msg):
        if self.panels:
            self.panels[0].ui_log(msg)

    def ui_set_status(self, text, online=False):
        if self.panels:
            self.panels[0].ui_set_status(text, online)

    # ─────────────────────────────────────────
    #  Token help dialog
    # ─────────────────────────────────────────
    def show_token_help(self):
        win = tk.Toplevel(self.root)
        win.title("Getting Your Discord Token")
        win.geometry("480x440")
        win.resizable(False, False)
        win.configure(bg=C["bg"])
        win.grab_set()

        tk.Frame(win, bg=C["accent"], height=2).pack(fill="x")

        tk.Label(win, text="Getting Your Discord Token",
                 font=("Segoe UI", 13, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(pady=(20, 4))
        tk.Label(win, text="Follow these steps carefully:",
                 font=("Segoe UI", 9), bg=C["bg"], fg=C["muted"]).pack()

        steps_outer = tk.Frame(win, bg=C["border"])
        steps_outer.pack(fill="x", padx=20, pady=12)
        steps_inner = tk.Frame(steps_outer, bg=C["card2"])
        steps_inner.pack(fill="both", padx=1, pady=1)

        steps = [
            ("1", "Click the button below to open Discord in your browser"),
            ("2", "Log into your Discord account if needed"),
            ("3", "Press F12 to open DevTools"),
            ("4", "Click the 'Network' tab"),
            ("5", "Press Ctrl+R to reload the page"),
            ("6", "In the filter box, type:  api"),
            ("7", "Click any request that appears in the list"),
            ("8", "Under 'Headers', find the 'authorization' field"),
            ("9", "Copy that value — paste it into the Token box"),
        ]
        for num, desc in steps:
            row = tk.Frame(steps_inner, bg=C["card2"])
            row.pack(fill="x", padx=12, pady=3)
            tk.Label(row, text=num, font=("Segoe UI", 8, "bold"),
                     bg=C["accent"], fg=C["dark"],
                     width=2, padx=4, pady=1).pack(side="left", padx=(0, 10))
            tk.Label(row, text=desc, font=("Segoe UI", 9),
                     bg=C["card2"], fg=C["text"], anchor="w").pack(side="left")

        _btn(win, "Open Discord in Browser",
             lambda: webbrowser.open("https://discord.com/app"),
             C["accent"]).pack(pady=(8, 4))

        tk.Label(win, text="⚠  Never share your token with anyone.",
                 font=("Segoe UI", 9, "bold"),
                 bg=C["bg"], fg=C["red"]).pack(pady=(4, 16))

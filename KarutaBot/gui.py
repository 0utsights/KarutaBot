import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox
import threading
import webbrowser
import json
import os
from datetime import datetime

from config import (C, APP_NAME, APP_VERSION, MAX_DROPS_PER_DAY,
                    DROP_JITTER_MIN, DROP_JITTER_MAX, load_config, save_config, default_account)
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


class _Tooltip:
    """Hover tooltip attached to a widget."""
    def __init__(self, widget, text):
        self.widget = widget
        self.text   = text
        self.tip    = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)
        widget.bind("<Button-1>", self._show)

    def _show(self, event=None):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + 20
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        frame = tk.Frame(self.tip, bg=C["card2"], bd=0,
                         highlightthickness=1, highlightbackground=C["border"])
        frame.pack()
        tk.Label(frame, text=self.text, font=("Segoe UI", 9),
                 bg=C["card2"], fg=C["text"],
                 wraplength=260, justify="left",
                 padx=10, pady=8).pack()

    def _hide(self, event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


def _tip_label(parent, text, tooltip, row, col, padx=0):
    """Render a muted setting label + a small cyan ? icon with a tooltip, in a parent grid."""
    # Container so label and ? sit side-by-side without disturbing the grid
    frame = tk.Frame(parent, bg=C["card2"])
    frame.grid(row=row, column=col, sticky="w", padx=(padx, 0))
    tk.Label(frame, text=text, font=("Segoe UI", 7, "bold"),
             bg=C["card2"], fg=C["muted"]).pack(side="left")
    tip_icon = tk.Label(frame, text=" ?", font=("Segoe UI", 7, "bold"),
                        bg=C["card2"], fg=C["accent"], cursor="question_arrow")
    tip_icon.pack(side="left")
    _Tooltip(tip_icon, tooltip)


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
        self._reminder_seconds    = {}   # last known values in seconds
        self._reminder_updated_at = None # when they were last fetched

        self._build(parent)
        self._update_timer()
        self._tick_reminders()

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
        _tip_label(creds, "TOKEN", "Your Discord user token. Used to log in as your account.", row=0, col=0)
        self.token_var = tk.StringVar(value=self.data.get("token", ""))
        te = _entry(creds, self.token_var, show="•", width=36)
        te.grid(row=1, column=0, sticky="ew", pady=(2, 6), ipady=5)

        # Channel ID
        _tip_label(creds, "CHANNEL ID", "The Discord channel ID where Karuta commands will be sent.", row=0, col=1, padx=16)
        self.channel_var = tk.StringVar(value=self.data.get("channel_id", ""))
        ce = _entry(creds, self.channel_var, width=18)
        ce.grid(row=1, column=1, sticky="ew", pady=(2, 6), padx=(16, 0), ipady=5)

        # Visit Card Code
        _tip_label(creds, "VISIT CARD CODE",
                   "Optional. Pin a specific card code to always visit (e.g. nkkmpd).\n"
                   "If set, skips k!affectionlist entirely and visits only this card.",
                   row=0, col=2, padx=16)
        self.visit_card_var = tk.StringVar(value=self.data.get("visit_card_code", ""))
        ve = _entry(creds, self.visit_card_var, width=12)
        ve.grid(row=1, column=2, sticky="ew", pady=(2, 6), padx=(16, 0), ipady=5)

        # Visit Tag
        _tip_label(creds, "VISIT TAG",
                   "Optional. A card tag name to prioritise during visits.\n"
                   "Cards in this tag that aren't on your affectionlist are visited first "
                   "(to add them). Cards in the tag that are on the affectionlist are "
                   "prioritised over non-tag cards. Energy ≥5 is still required for "
                   "affectionlist cards.",
                   row=0, col=3, padx=16)
        self.visit_tag_var = tk.StringVar(value=self.data.get("visit_tag", ""))
        vte = _entry(creds, self.visit_tag_var, width=14)
        vte.grid(row=1, column=3, sticky="ew", pady=(2, 6), padx=(16, 0), ipady=5)

        # ── Settings row ──
        settings = tk.Frame(self.frame, bg=C["card2"])
        settings.pack(fill="x", padx=14, pady=(0, 4))

        _tip_label(settings, "MAX DROPS",
                   "Maximum k!drop commands per day.\n"
                   "The bot stops dropping once this limit is reached and waits until midnight.",
                   row=0, col=0)
        self.max_drops_var = tk.IntVar(value=self.data.get("max_drops", MAX_DROPS_PER_DAY))
        tk.Spinbox(settings, from_=1, to=48, textvariable=self.max_drops_var,
                   width=5, bg=C["dark"], fg=C["text"], relief="flat",
                   font=("Segoe UI", 10), buttonbackground=C["card"],
                   ).grid(row=1, column=0, sticky="w", pady=(2, 0), ipady=4)

        _tip_label(settings, "JITTER MIN (mins)",
                   "Minimum random minutes added on top of the k!reminders drop cooldown.\n"
                   "Adds human-like variation to avoid a fixed timing pattern.",
                   row=0, col=1, padx=20)
        self.jitter_min_var = tk.IntVar(value=self.data.get("jitter_min", DROP_JITTER_MIN))
        tk.Spinbox(settings, from_=0, to=30, textvariable=self.jitter_min_var,
                   width=5, bg=C["dark"], fg=C["text"], relief="flat",
                   font=("Segoe UI", 10), buttonbackground=C["card"],
                   ).grid(row=1, column=1, sticky="w", padx=(20, 0), pady=(2, 0), ipady=4)

        _tip_label(settings, "JITTER MAX (mins)",
                   "Maximum random minutes added on top of the k!reminders drop cooldown.\n"
                   "A random value between JITTER MIN and JITTER MAX is chosen each cycle.",
                   row=0, col=2, padx=12)
        self.jitter_max_var = tk.IntVar(value=self.data.get("jitter_max", DROP_JITTER_MAX))
        tk.Spinbox(settings, from_=0, to=60, textvariable=self.jitter_max_var,
                   width=5, bg=C["dark"], fg=C["text"], relief="flat",
                   font=("Segoe UI", 10), buttonbackground=C["card"],
                   ).grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(2, 0), ipady=4)

        _tip_label(settings, "VOTE MODE",
                   "Controls how k!vote is handled when the vote timer is ready.\n\n"
                   "Auto — Fully automatic. Launches a headless browser behind "
                   "the scenes, logs into top.gg via your Discord token, clicks "
                   "the vote button, and handles the captcha. Zero interaction "
                   "needed. Requires Chrome/Chromium installed.\n\n"
                   "Semi — Opens the top.gg vote page in your default browser. "
                   "You just click the captcha checkbox (~5 seconds).\n\n"
                   "Off — Ignores voting entirely.",
                   row=0, col=3, padx=16)
        self.vote_mode_var = tk.StringVar(value=self.data.get("vote_mode", "auto"))
        vote_menu = tk.OptionMenu(settings, self.vote_mode_var, "auto", "semi", "off")
        vote_menu.config(bg=C["dark"], fg=C["text"], relief="flat",
                         font=("Segoe UI", 9), activebackground=C["accent2"],
                         activeforeground=C["dark"], highlightthickness=0,
                         width=5, bd=0, padx=4)
        vote_menu["menu"].config(bg=C["dark"], fg=C["text"],
                                 activebackground=C["accent"],
                                 activeforeground=C["dark"],
                                 font=("Segoe UI", 9))
        vote_menu.grid(row=1, column=3, sticky="w", padx=(16, 0), pady=(2, 0), ipady=2)

        # "Show Browser" checkbox — makes the vote browser visible for debugging
        self.show_browser_var = tk.BooleanVar(value=self.data.get("show_browser", False))
        show_cb = tk.Checkbutton(settings, text="Show Browser",
                                 variable=self.show_browser_var,
                                 bg=C["card2"], fg=C["muted"],
                                 selectcolor=C["dark"],
                                 activebackground=C["card2"],
                                 activeforeground=C["text"],
                                 font=("Segoe UI", 8))
        show_cb.grid(row=1, column=4, sticky="w", padx=(8, 0), pady=(2, 0))

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

        # ── Reminders status bar ──
        rem_frame = tk.Frame(self.frame, bg=C["card2"])
        rem_frame.pack(fill="x", padx=14, pady=(0, 6))

        self._reminder_labels = {}
        for key in ["Daily", "Vote", "Drop", "Grab", "Work", "Visit"]:
            col = tk.Frame(rem_frame, bg=C["dark"], padx=8, pady=4)
            col.pack(side="left", padx=(0, 4))
            tk.Label(col, text=key.upper(), font=("Segoe UI", 6, "bold"),
                     bg=C["dark"], fg=C["muted"]).pack()
            lbl = tk.Label(col, text="?", font=("Segoe UI", 7, "bold"),
                           bg=C["dark"], fg=C["muted"])
            lbl.pack()
            self._reminder_labels[key] = lbl

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

    def update_reminders(self, reminders):
        """Store new reminder values from a fresh k!reminders fetch and reset the tick clock."""
        self._reminder_seconds    = dict(reminders)
        self._reminder_updated_at = datetime.now()

    def _tick_reminders(self):
        """Run every second — decrement stored reminder values and refresh badge text."""
        if self._reminder_updated_at is not None and self._reminder_seconds:
            elapsed = (datetime.now() - self._reminder_updated_at).total_seconds()
            for key, lbl in self._reminder_labels.items():
                raw = self._reminder_seconds.get(key)
                if raw is None:
                    lbl.config(text="?", fg=C["muted"])
                elif raw == 0:
                    lbl.config(text="READY", fg=C["accent3"])
                else:
                    remaining = max(0, int(raw) - int(elapsed))
                    if remaining == 0:
                        lbl.config(text="READY", fg=C["accent3"])
                    else:
                        h = remaining // 3600
                        m = (remaining % 3600) // 60
                        s = remaining % 60
                        if h > 0:
                            txt = f"{h}h {m}m"
                        elif m > 0:
                            txt = f"{m}m {s:02d}s"
                        else:
                            txt = f"{s}s"
                        lbl.config(text=txt, fg=C["yellow"])
        self.app.root.after(1000, self._tick_reminders)

    def reset_daily_if_needed(self):
        today = datetime.now().date()
        if today != self.last_reset:
            self.drops_today = 0
            self.last_reset  = today
            self.ui_log("Daily drop counter reset.")
            self.app.root.after(0, self.update_drops_label)

    def _update_timer(self):
        try:
            if not self.timer_label.winfo_exists():
                return
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
        except tk.TclError:
            pass  # widget destroyed — stop updating

    def get_data(self):
        return {
            "name":            self.name_var.get(),
            "token":           self.token_var.get().strip(),
            "channel_id":      self.channel_var.get().strip(),
            "max_drops":       self.max_drops_var.get(),
            "jitter_min":      self.jitter_min_var.get(),
            "jitter_max":      self.jitter_max_var.get(),
            "vote_mode":       self.vote_mode_var.get(),
            "show_browser":    self.show_browser_var.get(),
            "visit_card_code": self.visit_card_var.get().strip(),
            "visit_tag":       self.visit_tag_var.get().strip(),
            "enabled":         True,
        }

    # ── Bot control ──
    def start_bot(self):
        token      = self.token_var.get().strip()
        channel_id = self.channel_var.get().strip()

        if not token or not channel_id:
            self.log("⚠ Please enter Token and Channel ID.")
            return

        # Token sanity check — Discord tokens have two dots and are reasonably long
        if token.count(".") < 2 or len(token) < 50:
            self.log("⚠ Token looks invalid. Make sure you copied the full token, not a partial or URL.")
            return

        # Channel ID must be a plain integer — catch the case where user pastes a URL
        # or a server_id/channel_id path like '123456789/987654321'
        if "/" in channel_id or not channel_id.isdigit():
            self.log("⚠ Channel ID looks invalid. It should be a plain number like 1234567890123456789.")
            self.log("   Tip: right-click the channel in Discord → Copy Channel ID (enable Developer Mode first).")
            return

        if len(channel_id) < 17:
            self.log("⚠ Channel ID is too short — Discord IDs are 17-19 digits.")
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
            from bot import do_drop_manual
            asyncio.run_coroutine_threadsafe(do_drop_manual(self, self.client), self.loop)


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
        _btn(tr, "📂 Import",     self.import_config, C["card2"], small=True).pack(side="left", padx=4)
        _btn(tr, "💾 Export",     self.export_config, C["card2"], small=True).pack(side="left", padx=4)
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

    def import_config(self):
        """Load accounts from a JSON config file, replacing current accounts."""
        path = filedialog.askopenfilename(
            title="Import Aeyori Config",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as e:
            messagebox.showerror("Import Failed", f"Could not read file:\n{e}")
            return

        if isinstance(data, list):
            accounts = data
        elif isinstance(data, dict) and "accounts" in data:
            accounts = data["accounts"]
        else:
            messagebox.showerror("Import Failed", "File format not recognised.\nExpected {\"accounts\": [...]} or a list of account objects.")
            return

        if not accounts:
            messagebox.showwarning("Import", "No accounts found in file.")
            return

        confirm = messagebox.askyesno(
            "Import Config",
            f"This will replace all {len(self.panels)} current account(s) with "
            f"{len(accounts)} account(s) from the file.\n\nContinue?"
        )
        if not confirm:
            return

        for panel in list(self.panels):
            if getattr(panel, "running", False):
                panel.running = False
            panel.outer.destroy()
        self.panels.clear()

        for acc in accounts:
            self._add_panel(acc)

        self.save_all()
        messagebox.showinfo("Import Complete", f"Loaded {len(accounts)} account(s) from file.")

    def export_config(self):
        """Save current account config to a JSON file."""
        path = filedialog.asksaveasfilename(
            title="Export Aeyori Config",
            defaultextension=".json",
            initialfile="aeyori_config.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        accounts = [p.get_data() for p in self.panels]
        strip = messagebox.askyesno(
            "Export Config",
            "Remove tokens from export?\n\n"
            "(Recommended if sharing — you can re-enter them after importing.)"
        )
        if strip:
            for acc in accounts:
                acc["token"] = ""
        try:
            with open(path, "w") as f:
                json.dump({"accounts": accounts}, f, indent=2)
            messagebox.showinfo("Export Complete", f"Config saved to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not save file:\n{e}")

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

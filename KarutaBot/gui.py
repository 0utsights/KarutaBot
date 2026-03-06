import tkinter as tk
from tkinter import scrolledtext, filedialog, messagebox, ttk
import threading
import webbrowser
import json
import os
from datetime import datetime

from config import (C, APP_NAME, APP_VERSION, MAX_DROPS_PER_DAY,
                    DROP_JITTER_MIN, DROP_JITTER_MAX, load_config, save_config, default_account)
from license import start_heartbeat, release_key
from bot import run_discord_loop, do_drop


# ─────────────────────────────────────────────
#  Admin password (must match admin_dashboard)
# ─────────────────────────────────────────────
# Admin panel is now in admin_dashboard.py


# ─────────────────────────────────────────────────────────────────────────────
#  Themed scrollbar — replaces the ugly default OS scrollbar everywhere
# ─────────────────────────────────────────────────────────────────────────────
def _apply_scrollbar_style(root_widget):
    """Configure a ttk Style for flat dark scrollbars. Call once at app start."""
    style = ttk.Style(root_widget)
    style.theme_use("clam")
    style.configure(
        "Dark.Vertical.TScrollbar",
        gripcount=0,
        background=C["card2"],       # thumb colour
        darkcolor=C["bg"],
        lightcolor=C["bg"],
        troughcolor=C["bg"],         # track
        bordercolor=C["bg"],
        arrowcolor=C["muted"],       # arrow buttons
        relief="flat",
        borderwidth=0,
        arrowsize=12,
    )
    style.map(
        "Dark.Vertical.TScrollbar",
        background=[("active", C["accent2"]), ("pressed", C["accent"])],
        arrowcolor=[("active", C["accent"])],
    )
    style.configure(
        "Dark.Horizontal.TScrollbar",
        gripcount=0,
        background=C["card2"],
        darkcolor=C["bg"],
        lightcolor=C["bg"],
        troughcolor=C["bg"],
        bordercolor=C["bg"],
        arrowcolor=C["muted"],
        relief="flat",
        borderwidth=0,
        arrowsize=12,
    )
    style.map(
        "Dark.Horizontal.TScrollbar",
        background=[("active", C["accent2"]), ("pressed", C["accent"])],
        arrowcolor=[("active", C["accent"])],
    )


def _themed_scrollbar(parent, orient="vertical", **kw):
    """Return a ttk Scrollbar using the dark theme style."""
    s = "Dark.Vertical.TScrollbar" if orient == "vertical" else "Dark.Horizontal.TScrollbar"
    return ttk.Scrollbar(parent, orient=orient, style=s, **kw)


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
    b.bind("<Enter>", lambda e: b.config(bg=C["accent2"]))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b

def _divider(parent, pady=4):
    tk.Frame(parent, bg=C["border"], height=1).pack(fill="x", pady=pady)


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
    frame = tk.Frame(parent, bg=C["card2"])
    frame.grid(row=row, column=col, sticky="w", padx=(padx, 0))
    tk.Label(frame, text=text, font=("Segoe UI", 7, "bold"),
             bg=C["card2"], fg=C["muted"]).pack(side="left")
    tip_icon = tk.Label(frame, text=" ?", font=("Segoe UI", 7, "bold"),
                        bg=C["card2"], fg=C["accent"], cursor="question_arrow")
    tip_icon.pack(side="left")
    _Tooltip(tip_icon, tooltip)


# ─────────────────────────────────────────────────────────────────────────────
#  Activity message classifier
#  Translates raw debug log messages into user-friendly status lines.
#  Returns (icon, friendly_text) or None to suppress the message entirely.
# ─────────────────────────────────────────────────────────────────────────────
_ACTIVITY_MAP = [
    # (substring_match, icon, friendly_text_template)
    # Order matters — first match wins

    # ── Startup / connection ──
    ("Logged in as",          "✅", lambda m: m.split("✅ ")[-1] if "✅" in m else m),
    ("Starting...",           "🔄", lambda m: "Starting bot..."),
    ("Invalid token",         "❌", lambda m: "Login failed — check your token"),
    ("Connecting",            "🔄", lambda m: "Connecting to Discord..."),
    ("Online as",             "✅", lambda m: m),

    # ── Reminders ──
    ("📋 Reminders:",         "📋", lambda m: "Checked reminders"),

    # ── Dropping ──
    ("🃏 Dropped!",           "🃏", lambda m: m.split("🃏 ")[-1]),
    ("📋 Cards:",             "🃏", lambda m: "Cards: " + m.split("Cards: ")[-1] if "Cards:" in m else m),
    ("⭐ Grabbing card",      "⭐", lambda m: m.split("⭐ ")[-1] if "⭐" in m else m),
    ("🔥 Auto-grabbing",      "🔥", lambda m: m.split("🔥 ")[-1] if "🔥" in m else m),

    # ── Voting ──
    ("Vote is ready",         "🗳", lambda m: "Vote is ready — voting now..."),
    ("Vote completed",        "✅", lambda m: "Vote completed!"),
    ("Vote page opened",      "🗳", lambda m: "Vote page opened — click to complete"),
    ("Headless vote failed",  "⚠️",  lambda m: "Auto-vote failed, trying manual..."),
    ("vote.py not found",     "⚠️",  lambda m: "Auto-vote unavailable"),

    # ── Daily ──
    ("📅 Claiming daily",     "📅", lambda m: "Claiming daily reward..."),
    ("Daily answered",        "✅", lambda m: "Daily reward claimed!"),
    ("Daily already claimed", "📅", lambda m: "Daily already claimed"),

    # ── Work ──
    ("💼 Work:",              "💼", lambda m: "Optimizing work board..."),
    ("Work confirmed",        "✅", lambda m: "Work submitted!"),
    ("Work started",          "✅", lambda m: "Work started!"),

    # ── Visit ──
    ("🏛 Visiting shrine",    "🏛", lambda m: "Visiting shrine..."),
    ("🏛 Selected:",          "🏛", lambda m: "Selected: " + m.split("Selected: ")[-1] if "Selected:" in m else m),
    ("Visit done",            "✅", lambda m: "Shrine visit complete!"),
    ("Visit round",           "🏛", lambda m: "Talking..."),

    # ── Burn ──
    ("Burned",                "🔥", lambda m: m.split("🔥 ")[-1] if "🔥" in m else m),
    ("eligible for burn",     "🔥", lambda m: "Burning low-value card..."),

    # ── Wishlist ──
    ("♥ Wishlisted:",         "♥",  lambda m: m.split("♥ ")[-1] if "♥" in m else m),

    # ── Sleep / timer ──
    ("⏱ Next cycle in",      "⏱",  lambda m: m.split("⏱ ")[-1] if "⏱" in m else m),
    ("⏱ Next drop in",       "⏱",  lambda m: m.split("⏱ ")[-1] if "⏱" in m else m),
    ("⏱ Drop on cooldown",   "⏱",  lambda m: "Drop on cooldown — waiting..."),
    ("Daily drop limit",      "⚠️",  lambda m: "Daily drop limit reached"),
    ("Daily drop counter reset", "🔄", lambda m: "Daily drop counter reset"),

    # ── Errors (always show) ──
    ("❌",                    "❌", lambda m: m.split("❌ ")[-1] if "❌" in m else m),
    ("Discord 503",           "⚠️",  lambda m: "Discord temporarily unavailable — retrying..."),
    ("Rate limited",          "⚠️",  lambda m: "Rate limited — waiting..."),
    ("Stopped.",              "⏹",  lambda m: "Bot stopped"),
]


def _classify_activity(raw_msg):
    """Return (icon, friendly_text) for a raw log message, or None to suppress."""
    for substr, icon, formatter in _ACTIVITY_MAP:
        if substr in raw_msg:
            return icon, formatter(raw_msg)
    return None


# ─────────────────────────────────────────────────────────────────────────────
#  Toggle Switch — custom Canvas-based on/off switch
# ─────────────────────────────────────────────────────────────────────────────
class _ToggleSwitch(tk.Canvas):
    """A smooth on/off toggle switch widget bound to a BooleanVar."""
    def __init__(self, parent, variable, on_color=None, off_color=None,
                 width=44, height=22):
        super().__init__(parent, width=width, height=height,
                         bg=C["card2"], highlightthickness=0, bd=0)
        self.var = variable
        self.on_color  = on_color  or C["accent3"]
        self.off_color = off_color or C["muted"]
        self.w = width
        self.h = height
        self.r = height // 2  # radius

        self.bind("<Button-1>", self._toggle)
        self.var.trace_add("write", lambda *a: self._draw())
        self._draw()

    def _toggle(self, event=None):
        self.var.set(not self.var.get())

    def _draw(self):
        self.delete("all")
        on = self.var.get()
        bg = self.on_color if on else self.off_color

        # Track (rounded rect via two circles + rect)
        r = self.r
        self.create_oval(1, 1, 2*r, 2*r, fill=bg, outline=bg)
        self.create_oval(self.w - 2*r, 1, self.w - 1, 2*r, fill=bg, outline=bg)
        self.create_rectangle(r, 1, self.w - r, 2*r, fill=bg, outline=bg)

        # Knob
        knob_x = self.w - r - 2 if on else r + 1
        knob_r = r - 3
        self.create_oval(knob_x - knob_r, r - knob_r,
                         knob_x + knob_r, r + knob_r,
                         fill=C["white"], outline=C["white"])


# ─────────────────────────────────────────────────────────────────────────────
#  AccountPanel — one panel per account
# ─────────────────────────────────────────────────────────────────────────────
class AccountPanel:
    def __init__(self, parent, app, index, account_data):
        self.app   = app
        self.index = index
        self.data  = account_data

        # Session state
        self.client         = None
        self.loop           = None
        self.bot_thread     = None
        self.running        = False
        self.next_drop_time = None
        self.drops_today    = 0
        self.last_reset     = datetime.now().date()
        self._reminder_seconds    = {}
        self._reminder_updated_at = None

        # ── Per-account macro toggles ──
        macros = account_data.get("macros", {})
        self.macro_daily  = tk.BooleanVar(value=macros.get("daily", True))
        self.macro_vote   = tk.BooleanVar(value=macros.get("vote", True))
        self.macro_work   = tk.BooleanVar(value=macros.get("work", True))
        self.macro_drop   = tk.BooleanVar(value=macros.get("drop", True))
        self.macro_grab   = tk.BooleanVar(value=macros.get("grab", True))
        self.macro_visit  = tk.BooleanVar(value=macros.get("visit", True))

        self._build(parent)
        self._update_timer()
        self._tick_reminders()

    def _build(self, parent):
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

        _tip_label(creds, "TOKEN", "Your Discord user token.", row=0, col=0)
        self.token_var = tk.StringVar(value=self.data.get("token", ""))
        te = _entry(creds, self.token_var, show="•", width=40)
        te.grid(row=1, column=0, sticky="ew", pady=(2, 6), ipady=5)

        _tip_label(creds, "CHANNEL ID", "The Discord channel ID for Karuta commands.", row=0, col=1, padx=16)
        self.channel_var = tk.StringVar(value=self.data.get("channel_id", ""))
        ce = _entry(creds, self.channel_var, width=20)
        ce.grid(row=1, column=1, sticky="ew", pady=(2, 6), padx=(16, 0), ipady=5)

        # ── Hidden vars (edited via Settings popup) ──
        self.visit_card_var   = tk.StringVar(value=self.data.get("visit_card_code", ""))
        self.visit_tag_var    = tk.StringVar(value=self.data.get("visit_tag", ""))
        self.max_drops_var    = tk.IntVar(value=self.data.get("max_drops", MAX_DROPS_PER_DAY))
        self.jitter_min_var   = tk.IntVar(value=self.data.get("jitter_min", DROP_JITTER_MIN))
        self.jitter_max_var   = tk.IntVar(value=self.data.get("jitter_max", DROP_JITTER_MAX))
        self.vote_mode_var    = tk.StringVar(value=self.data.get("vote_mode", "auto"))
        self.show_browser_var = tk.BooleanVar(value=self.data.get("show_browser", False))
        self.auto_burn_var    = tk.BooleanVar(value=self.data.get("auto_burn", False))

        # ── Button row ──
        _divider(self.frame, pady=6)
        btns = tk.Frame(self.frame, bg=C["card2"])
        btns.pack(fill="x", padx=14, pady=(0, 6))

        self.start_btn = _btn(btns, "▶  Start",  self.start_bot, C["accent3"], small=True)
        self.start_btn.pack(side="left", padx=(0, 6))

        self.stop_btn = _btn(btns, "■  Stop", self.stop_bot, C["red"], small=True)
        self.stop_btn.pack(side="left", padx=(0, 6))
        self.stop_btn.config(state="disabled")

        self.drop_btn = _btn(btns, "🃏 Drop Now", self.manual_drop, C["accent"], small=True)
        self.drop_btn.pack(side="left", padx=(0, 6))
        self.drop_btn.config(state="disabled")

        settings_btn = _btn(btns, "⚙ Settings", self._open_account_settings, C["card"], small=True)
        settings_btn.config(fg=C["accent"])
        settings_btn.pack(side="left", padx=(0, 6))

        remove_btn = _btn(btns, "✕ Remove", lambda: self.app.remove_account(self.index),
                          C["card"], small=True)
        remove_btn.config(fg=C["muted"])
        remove_btn.bind("<Enter>", lambda e: remove_btn.config(fg=C["red"]))
        remove_btn.bind("<Leave>", lambda e: remove_btn.config(fg=C["muted"]))
        remove_btn.pack(side="right")

        # ── Macro status badges ──
        macro_frame = tk.Frame(self.frame, bg=C["card2"])
        macro_frame.pack(fill="x", padx=14, pady=(0, 6))
        tk.Label(macro_frame, text="MACROS", font=("Segoe UI", 6, "bold"),
                 bg=C["card2"], fg=C["muted"]).pack(side="left", padx=(0, 8))

        self._macro_badges = {}
        macro_map = [
            ("daily", self.macro_daily),
            ("vote",  self.macro_vote),
            ("work",  self.macro_work),
            ("drop",  self.macro_drop),
            ("grab",  self.macro_grab),
            ("visit", self.macro_visit),
        ]
        for name, var in macro_map:
            badge = tk.Label(macro_frame, text=name.upper(),
                             font=("Segoe UI", 7, "bold"),
                             bg=C["dark"], fg=C["accent3"] if var.get() else C["muted"],
                             padx=8, pady=2)
            badge.pack(side="left", padx=(0, 4))
            self._macro_badges[name] = badge
            # Update badge color when toggle changes
            var.trace_add("write", lambda *a, n=name, v=var: self._update_badge(n, v))

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

        # ── User-friendly Activity Feed ──
        activity_header = tk.Frame(self.frame, bg=C["card2"])
        activity_header.pack(fill="x", padx=14, pady=(4, 2))
        tk.Label(activity_header, text="ACTIVITY", font=("Segoe UI", 7, "bold"),
                 bg=C["card2"], fg=C["muted"]).pack(side="left")

        _act_frame = tk.Frame(self.frame, bg=C["dark"],
                              highlightthickness=1, highlightbackground=C["border"])
        _act_frame.pack(fill="x", padx=14, pady=(0, 4))
        self.activity_box = tk.Text(
            _act_frame, height=4, width=70,
            bg=C["dark"], fg=C["text"],
            font=("Segoe UI", 9),
            relief="flat", state="disabled",
            insertbackground=C["accent"],
            selectbackground=C["accent2"],
            wrap="word", bd=0,
        )
        _act_sb = _themed_scrollbar(_act_frame, orient="vertical",
                                    command=self.activity_box.yview)
        self.activity_box.configure(yscrollcommand=_act_sb.set)
        _act_sb.pack(side="right", fill="y")
        self.activity_box.pack(side="left", fill="both", expand=True)

        # Tag colors for activity feed
        self.activity_box.tag_configure("icon", foreground=C["accent"])
        self.activity_box.tag_configure("time", foreground=C["muted"], font=("Segoe UI", 8))
        self.activity_box.tag_configure("success", foreground=C["green"])
        self.activity_box.tag_configure("warning", foreground=C["yellow"])
        self.activity_box.tag_configure("error", foreground=C["red"])

        # ── Debug log — ADMIN ONLY (hidden by default) ──
        self.debug_frame = tk.Frame(self.frame, bg=C["card2"])
        # NOT packed by default

        debug_header = tk.Frame(self.debug_frame, bg=C["card2"])
        debug_header.pack(fill="x", padx=14, pady=(4, 2))
        tk.Label(debug_header, text="DEBUG LOG (Admin)", font=("Segoe UI", 7, "bold"),
                 bg=C["card2"], fg=C["red"]).pack(side="left")

        _log_font = ("Cascadia Code", 8) if self._font_exists("Cascadia Code") else ("Courier New", 8)
        _log_frame = tk.Frame(self.debug_frame, bg=C["dark"],
                              highlightthickness=1, highlightbackground=C["border"])
        _log_frame.pack(fill="x", padx=14, pady=(0, 14))
        self.log_box = tk.Text(
            _log_frame, height=6, width=70,
            bg=C["dark"], fg=C["text"],
            font=_log_font,
            relief="flat", state="disabled",
            insertbackground=C["accent"],
            selectbackground=C["accent2"],
            bd=0,
        )
        _log_sb = _themed_scrollbar(_log_frame, orient="vertical",
                                    command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=_log_sb.set)
        _log_sb.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)

        # Bottom spacer
        self._bottom_spacer = tk.Frame(self.frame, bg=C["card2"], height=8)
        self._bottom_spacer.pack(fill="x")

    def _font_exists(self, name):
        try:
            import tkinter.font as tkfont
            return name in tkfont.families()
        except:
            return False

    def _update_badge(self, name, var):
        badge = self._macro_badges.get(name)
        if badge:
            badge.config(fg=C["accent3"] if var.get() else C["muted"])

    # ── Per-account settings popup ──
    def _open_account_settings(self):
        win = tk.Toplevel(self.app.root)
        win.title(f"Settings — {self.name_var.get()}")
        win.geometry("440x700")
        win.resizable(False, True)
        win.configure(bg=C["bg"])
        win.grab_set()

        tk.Frame(win, bg=C["accent"], height=2).pack(fill="x")

        # ── Scrollable content ──
        canvas = tk.Canvas(win, bg=C["bg"], highlightthickness=0, bd=0)
        scrollbar = _themed_scrollbar(win, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        content = tk.Frame(canvas, bg=C["bg"])
        canvas_win = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(canvas_win, width=e.width))
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        # ── Header ──
        tk.Label(content, text=f"⚙  {self.name_var.get()}",
                 font=("Segoe UI", 14, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(pady=(16, 4))
        tk.Label(content, text="Configure macros and settings for this account",
                 font=("Segoe UI", 9), bg=C["bg"], fg=C["muted"]).pack(pady=(0, 12))

        # ════════════════════════════════════════════
        #  MACRO TOGGLES
        # ════════════════════════════════════════════
        macros_section = tk.Frame(content, bg=C["card2"])
        macros_section.pack(fill="x", padx=20, pady=(0, 10))
        tk.Label(macros_section, text="MACRO TOGGLES", font=("Segoe UI", 8, "bold"),
                 bg=C["card2"], fg=C["muted"]).pack(anchor="w", padx=12, pady=(10, 6))

        macro_info = [
            ("drop",  self.macro_drop,  "🃏 Drop",  "Automatically use k!drop on cooldown (30m cycle)"),
            ("grab",  self.macro_grab,  "⭐ Grab",  "Auto-grab the best card from drops (OCR + wishlist)"),
            ("daily", self.macro_daily, "📅 Daily", "Claim k!daily reward and answer quiz (24h cycle)"),
            ("vote",  self.macro_vote,  "🗳 Vote",  "Vote on top.gg (12h cycle)"),
            ("work",  self.macro_work,  "💼 Work",  "Optimize job board and run k!work (12h cycle)"),
            ("visit", self.macro_visit, "🏛 Visit", "Visit shrine, talk, and use actions (2h cycle)"),
        ]

        for key, var, label, desc in macro_info:
            row = tk.Frame(macros_section, bg=C["card2"])
            row.pack(fill="x", padx=12, pady=3)
            toggle_frame = tk.Frame(row, bg=C["card2"])
            toggle_frame.pack(side="right", padx=(8, 0))
            _ToggleSwitch(toggle_frame, var, on_color=C["accent3"], off_color=C["muted"]).pack()
            info_frame = tk.Frame(row, bg=C["card2"])
            info_frame.pack(side="left", fill="x", expand=True)
            tk.Label(info_frame, text=label, font=("Segoe UI", 10, "bold"),
                     bg=C["card2"], fg=C["text"], anchor="w").pack(anchor="w")
            tk.Label(info_frame, text=desc, font=("Segoe UI", 8),
                     bg=C["card2"], fg=C["muted"], anchor="w").pack(anchor="w")

        tk.Frame(macros_section, bg=C["card2"], height=6).pack()

        # Quick actions
        quick_btns = tk.Frame(macros_section, bg=C["card2"])
        quick_btns.pack(fill="x", padx=12, pady=(0, 10))

        def enable_all():
            for _, v, _, _ in macro_info:
                v.set(True)
        def disable_all():
            for _, v, _, _ in macro_info:
                v.set(False)
        def drops_only():
            for k, v, _, _ in macro_info:
                v.set(k in ("drop", "grab"))

        _btn(quick_btns, "Enable All", enable_all, C["accent3"], small=True).pack(side="left", padx=(0, 6))
        _btn(quick_btns, "Disable All", disable_all, C["red"], small=True).pack(side="left", padx=(0, 6))
        _btn(quick_btns, "Drops Only", drops_only, C["accent"], small=True).pack(side="left", padx=(0, 6))

        # ════════════════════════════════════════════
        #  DROP SETTINGS
        # ════════════════════════════════════════════
        drop_section = tk.Frame(content, bg=C["card2"])
        drop_section.pack(fill="x", padx=20, pady=(0, 10))
        tk.Label(drop_section, text="DROP SETTINGS", font=("Segoe UI", 8, "bold"),
                 bg=C["card2"], fg=C["muted"]).pack(anchor="w", padx=12, pady=(10, 6))

        drop_grid = tk.Frame(drop_section, bg=C["card2"])
        drop_grid.pack(fill="x", padx=12, pady=(0, 10))

        # Max Drops
        tk.Label(drop_grid, text="Max Drops / Day", font=("Segoe UI", 9),
                 bg=C["card2"], fg=C["text"]).grid(row=0, column=0, sticky="w", pady=2)
        tk.Spinbox(drop_grid, from_=1, to=48, textvariable=self.max_drops_var,
                   width=5, bg=C["dark"], fg=C["text"], relief="flat",
                   font=("Segoe UI", 10), buttonbackground=C["card"],
                   ).grid(row=0, column=1, sticky="w", padx=(8, 0), pady=2, ipady=3)

        # Jitter Min
        tk.Label(drop_grid, text="Jitter Min (mins)", font=("Segoe UI", 9),
                 bg=C["card2"], fg=C["text"]).grid(row=1, column=0, sticky="w", pady=2)
        tk.Spinbox(drop_grid, from_=0, to=30, textvariable=self.jitter_min_var,
                   width=5, bg=C["dark"], fg=C["text"], relief="flat",
                   font=("Segoe UI", 10), buttonbackground=C["card"],
                   ).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=2, ipady=3)

        # Jitter Max
        tk.Label(drop_grid, text="Jitter Max (mins)", font=("Segoe UI", 9),
                 bg=C["card2"], fg=C["text"]).grid(row=2, column=0, sticky="w", pady=2)
        tk.Spinbox(drop_grid, from_=0, to=60, textvariable=self.jitter_max_var,
                   width=5, bg=C["dark"], fg=C["text"], relief="flat",
                   font=("Segoe UI", 10), buttonbackground=C["card"],
                   ).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=2, ipady=3)

        # Auto Burn toggle
        burn_row = tk.Frame(drop_section, bg=C["card2"])
        burn_row.pack(fill="x", padx=12, pady=(0, 10))
        burn_toggle_frame = tk.Frame(burn_row, bg=C["card2"])
        burn_toggle_frame.pack(side="right", padx=(8, 0))
        _ToggleSwitch(burn_toggle_frame, self.auto_burn_var, on_color=C["red"], off_color=C["muted"]).pack()
        burn_info = tk.Frame(burn_row, bg=C["card2"])
        burn_info.pack(side="left", fill="x", expand=True)
        tk.Label(burn_info, text="🔥 Auto Burn", font=("Segoe UI", 10, "bold"),
                 bg=C["card2"], fg=C["text"], anchor="w").pack(anchor="w")
        tk.Label(burn_info, text="Burn low-wish high-print cards after grabbing (k!burn)",
                 font=("Segoe UI", 8), bg=C["card2"], fg=C["muted"], anchor="w").pack(anchor="w")

        # ════════════════════════════════════════════
        #  VOTE SETTINGS
        # ════════════════════════════════════════════
        vote_section = tk.Frame(content, bg=C["card2"])
        vote_section.pack(fill="x", padx=20, pady=(0, 10))
        tk.Label(vote_section, text="VOTE SETTINGS", font=("Segoe UI", 8, "bold"),
                 bg=C["card2"], fg=C["muted"]).pack(anchor="w", padx=12, pady=(10, 6))

        vote_grid = tk.Frame(vote_section, bg=C["card2"])
        vote_grid.pack(fill="x", padx=12, pady=(0, 10))

        tk.Label(vote_grid, text="Vote Mode", font=("Segoe UI", 9),
                 bg=C["card2"], fg=C["text"]).grid(row=0, column=0, sticky="w", pady=2)
        vote_menu = tk.OptionMenu(vote_grid, self.vote_mode_var, "auto", "semi", "off")
        vote_menu.config(bg=C["dark"], fg=C["text"], relief="flat",
                         font=("Segoe UI", 9), activebackground=C["accent2"],
                         activeforeground=C["dark"], highlightthickness=0,
                         width=6, bd=0)
        vote_menu["menu"].config(bg=C["dark"], fg=C["text"],
                                 activebackground=C["accent"],
                                 activeforeground=C["dark"],
                                 font=("Segoe UI", 9))
        vote_menu.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=2)

        tk.Label(vote_grid, text="Auto — headless browser   Semi — opens page   Off — skip",
                 font=("Segoe UI", 7), bg=C["card2"], fg=C["muted"]).grid(
                     row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))

        # Show Browser (debug) — admin only, hidden by default
        self._show_browser_row = tk.Frame(vote_section, bg=C["card2"])
        # NOT packed by default — revealed by set_admin_mode
        show_toggle_frame = tk.Frame(self._show_browser_row, bg=C["card2"])
        show_toggle_frame.pack(side="right", padx=(8, 0))
        _ToggleSwitch(show_toggle_frame, self.show_browser_var, on_color=C["accent"], off_color=C["muted"]).pack()
        show_info = tk.Frame(self._show_browser_row, bg=C["card2"])
        show_info.pack(side="left", fill="x", expand=True)
        tk.Label(show_info, text="🔧 Show Browser", font=("Segoe UI", 9, "bold"),
                 bg=C["card2"], fg=C["accent"], anchor="w").pack(anchor="w")
        tk.Label(show_info, text="Show Chrome window during auto-vote (admin/debug only)",
                 font=("Segoe UI", 8), bg=C["card2"], fg=C["muted"], anchor="w").pack(anchor="w")

        # ════════════════════════════════════════════
        #  VISIT SETTINGS
        # ════════════════════════════════════════════
        visit_section = tk.Frame(content, bg=C["card2"])
        visit_section.pack(fill="x", padx=20, pady=(0, 10))
        tk.Label(visit_section, text="VISIT SETTINGS", font=("Segoe UI", 8, "bold"),
                 bg=C["card2"], fg=C["muted"]).pack(anchor="w", padx=12, pady=(10, 6))

        visit_grid = tk.Frame(visit_section, bg=C["card2"])
        visit_grid.pack(fill="x", padx=12, pady=(0, 10))

        tk.Label(visit_grid, text="Visit Card Code", font=("Segoe UI", 9),
                 bg=C["card2"], fg=C["text"]).grid(row=0, column=0, sticky="w", pady=2)
        _entry(visit_grid, self.visit_card_var, width=14).grid(
            row=0, column=1, sticky="w", padx=(8, 0), pady=2, ipady=4)

        tk.Label(visit_grid, text="Visit Tag", font=("Segoe UI", 9),
                 bg=C["card2"], fg=C["text"]).grid(row=1, column=0, sticky="w", pady=2)
        _entry(visit_grid, self.visit_tag_var, width=14).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=2, ipady=4)

        tk.Label(visit_grid, text="Card code pins a specific card. Tag prioritises cards with that tag.",
                 font=("Segoe UI", 7), bg=C["card2"], fg=C["muted"]).grid(
                     row=2, column=0, columnspan=2, sticky="w", pady=(0, 4))

        # ════════════════════════════════════════════
        #  SAVE & CLOSE
        # ════════════════════════════════════════════
        btn_frame = tk.Frame(content, bg=C["bg"])
        btn_frame.pack(fill="x", padx=20, pady=(8, 20))

        def close_and_save():
            self.app.save_all()
            win.destroy()

        _btn(btn_frame, "Save & Close", close_and_save, C["accent"]).pack()

    # ── Admin mode toggle ──
    def set_admin_mode(self, is_admin):
        if is_admin:
            self.debug_frame.pack(fill="x", before=self._bottom_spacer)
            self._show_browser_row.pack(fill="x", padx=12, pady=(0, 10))
        else:
            self.debug_frame.pack_forget()
            self._show_browser_row.pack_forget()
            self.show_browser_var.set(False)  # reset so it can't persist after logout

    # ── UI helpers ──
    def ui_log(self, msg):
        self.app.root.after(0, lambda: self._log_both(msg))

    def ui_set_status(self, text, online=False):
        self.app.root.after(0, lambda: self._set_status(text, online))

    def _log_both(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")

        # Always write to debug log
        self.log_box.config(state="normal")
        self.log_box.insert("end", f"[{ts}] {msg}\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

        # Classify for activity feed
        result = _classify_activity(msg)
        if result:
            icon, friendly = result
            self.activity_box.config(state="normal")

            self.activity_box.insert("end", f"  {ts}  ", "time")

            if icon in ("✅",):
                tag = "success"
            elif icon in ("⚠️", "⚠"):
                tag = "warning"
            elif icon in ("❌",):
                tag = "error"
            else:
                tag = ""

            self.activity_box.insert("end", f"{icon}  ", "icon")
            if tag:
                self.activity_box.insert("end", f"{friendly}\n", tag)
            else:
                self.activity_box.insert("end", f"{friendly}\n")

            self.activity_box.see("end")
            self.activity_box.config(state="disabled")

    def log(self, msg):
        self._log_both(msg)

    def _set_status(self, text, online=False):
        self.status_dot.config(fg=C["accent3"] if online else C["red"])

    def update_drops_label(self):
        limit = self.max_drops_var.get()
        color = C["accent3"] if self.drops_today < limit else C["red"]
        self.drops_label.config(text=f"{self.drops_today} / {limit}", fg=color)

    def update_reminders(self, reminders):
        self._reminder_seconds    = dict(reminders)
        self._reminder_updated_at = datetime.now()

    def _tick_reminders(self):
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
            pass

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
            "auto_burn":       self.auto_burn_var.get(),
            "enabled":         True,
            "macros": {
                "daily":  self.macro_daily.get(),
                "vote":   self.macro_vote.get(),
                "work":   self.macro_work.get(),
                "drop":   self.macro_drop.get(),
                "grab":   self.macro_grab.get(),
                "visit":  self.macro_visit.get(),
            },
        }

    # ── Bot control ──
    def start_bot(self):
        token      = self.token_var.get().strip()
        channel_id = self.channel_var.get().strip()

        if not token or not channel_id:
            self.log("⚠ Please enter Token and Channel ID.")
            return

        if token.count(".") < 2 or len(token) < 50:
            self.log("⚠ Token looks invalid. Make sure you copied the full token.")
            return

        if "/" in channel_id or not channel_id.isdigit():
            self.log("⚠ Channel ID looks invalid. It should be a plain number.")
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
#  KarutaApp — main window
# ─────────────────────────────────────────────────────────────────────────────
class KarutaApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_NAME}  v{APP_VERSION}")
        _apply_scrollbar_style(root)
        self.root.geometry("780x820")
        self.root.minsize(700, 600)
        self.root.configure(bg=C["bg"])

        self.config     = load_config()
        self.panels     = []
        self.admin_mode = False

        self._build_ui()
        self._load_accounts()

    def _build_ui(self):
        # ── Top bar ──
        topbar = tk.Frame(self.root, bg=C["bg2"], height=52)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)

        logo_frame = tk.Frame(topbar, bg=C["bg2"])
        logo_frame.pack(side="left", padx=20)

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

        _btn(tr, "⚙ Settings", self._open_settings, C["card2"], small=True).pack(side="left", padx=4)
        _btn(tr, "+ Add Account", self.add_account, C["accent"], small=True).pack(side="left", padx=4)
        _btn(tr, "📂 Import",     self.import_config, C["card2"], small=True).pack(side="left", padx=4)
        _btn(tr, "💾 Export",     self.export_config, C["card2"], small=True).pack(side="left", padx=4)
        _btn(tr, "❓ Token Help",  self.show_token_help, C["card2"], small=True).pack(side="left", padx=4)

        tk.Frame(self.root, bg=C["accent"], height=1).pack(fill="x")

        # ── Scrollable accounts area ──
        scroll_container = tk.Frame(self.root, bg=C["bg"])
        scroll_container.pack(fill="both", expand=True, pady=(8, 0))

        canvas = tk.Canvas(scroll_container, bg=C["bg"], highlightthickness=0, bd=0)
        scrollbar = _themed_scrollbar(scroll_container, orient="vertical",
                                   command=canvas.yview)
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

        self._admin_indicator = tk.Label(footer, text="",
                                          font=("Segoe UI", 8, "bold"),
                                          bg=C["bg2"], fg=C["red"])
        self._admin_indicator.pack(side="right", padx=16)

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

    # ─────────────────────────────────────────
    #  Settings Window
    # ─────────────────────────────────────────
    def _open_settings(self):
        win = tk.Toplevel(self.root)
        win.title(f"{APP_NAME} — Settings")
        win.geometry("420x480")
        win.resizable(False, False)
        win.configure(bg=C["bg"])
        win.grab_set()

        tk.Frame(win, bg=C["accent"], height=2).pack(fill="x")

        tk.Label(win, text="Settings",
                 font=("Segoe UI", 14, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(pady=(20, 16))

        # ── General ──
        section = tk.Frame(win, bg=C["card2"])
        section.pack(fill="x", padx=20, pady=(0, 12))
        tk.Label(section, text="GENERAL", font=("Segoe UI", 8, "bold"),
                 bg=C["card2"], fg=C["muted"]).pack(anchor="w", padx=12, pady=(10, 6))

        row1 = tk.Frame(section, bg=C["card2"])
        row1.pack(fill="x", padx=12, pady=4)
        tk.Label(row1, text="Config auto-saves when you start a bot or close the app.",
                 font=("Segoe UI", 9), bg=C["card2"], fg=C["text"]).pack(anchor="w")

        row2 = tk.Frame(section, bg=C["card2"])
        row2.pack(fill="x", padx=12, pady=(4, 10))
        _btn(row2, "💾 Save Config Now", self.save_all, C["accent3"], small=True).pack(anchor="w")

        # ── Admin Mode ──
        admin_section = tk.Frame(win, bg=C["card2"])
        admin_section.pack(fill="x", padx=20, pady=(0, 12))
        tk.Label(admin_section, text="ADMIN MODE", font=("Segoe UI", 8, "bold"),
                 bg=C["card2"], fg=C["muted"]).pack(anchor="w", padx=12, pady=(10, 4))

        tk.Label(admin_section,
                 text="Enables debug log and Show Browser toggle.\n"
                      "Enter the admin password to activate.",
                 font=("Segoe UI", 9), bg=C["card2"], fg=C["text"],
                 justify="left").pack(anchor="w", padx=12, pady=(0, 8))

        pass_frame = tk.Frame(admin_section, bg=C["card2"])
        pass_frame.pack(fill="x", padx=12, pady=(0, 4))

        tk.Label(pass_frame, text="Password:", font=("Segoe UI", 9),
                 bg=C["card2"], fg=C["muted"]).pack(side="left", padx=(0, 8))
        admin_pass_var = tk.StringVar()
        admin_entry = tk.Entry(pass_frame, textvariable=admin_pass_var, show="•",
                               bg=C["dark"], fg=C["text"],
                               insertbackground=C["accent"],
                               relief="flat", font=("Segoe UI", 10),
                               width=20, bd=0,
                               highlightthickness=1,
                               highlightbackground=C["border"],
                               highlightcolor=C["accent"])
        admin_entry.pack(side="left", ipady=5)

        admin_status = tk.Label(admin_section, text="", font=("Segoe UI", 9),
                                bg=C["card2"], fg=C["muted"])
        admin_status.pack(anchor="w", padx=12, pady=(4, 4))

        def toggle_admin():
            if self.admin_mode:
                self.admin_mode = False
                for panel in self.panels:
                    panel.set_admin_mode(False)
                self._admin_indicator.config(text="")
                admin_status.config(text="Admin mode disabled", fg=C["muted"])
                toggle_btn.config(text="🔓 Enable Admin Mode")
            else:
                pw = admin_pass_var.get().strip()
                if pw == ADMIN_PASSWORD:
                    self.admin_mode = True
                    for panel in self.panels:
                        panel.set_admin_mode(True)
                    self._admin_indicator.config(text="🔧 ADMIN")
                    admin_status.config(text="Admin mode enabled!", fg=C["green"])
                    toggle_btn.config(text="🔒 Disable Admin Mode")
                else:
                    admin_status.config(text="Wrong password", fg=C["red"])

        btn_frame = tk.Frame(admin_section, bg=C["card2"])
        btn_frame.pack(fill="x", padx=12, pady=(0, 10))

        toggle_text = "🔒 Disable Admin Mode" if self.admin_mode else "🔓 Enable Admin Mode"
        toggle_btn = _btn(btn_frame, toggle_text, toggle_admin, C["accent"], small=True)
        toggle_btn.pack(anchor="w")

        # ── About ──
        about_section = tk.Frame(win, bg=C["card2"])
        about_section.pack(fill="x", padx=20, pady=(0, 12))
        tk.Label(about_section, text="ABOUT", font=("Segoe UI", 8, "bold"),
                 bg=C["card2"], fg=C["muted"]).pack(anchor="w", padx=12, pady=(10, 4))
        tk.Label(about_section,
                 text=f"{APP_NAME} v{APP_VERSION}\n"
                      f"Automated Karuta card dropping & management",
                 font=("Segoe UI", 9), bg=C["card2"], fg=C["text"],
                 justify="left").pack(anchor="w", padx=12, pady=(0, 10))

        _btn(win, "Close", win.destroy, C["card2"]).pack(pady=(8, 16))

    # ─────────────────────────────────────────
    #  Account management
    # ─────────────────────────────────────────
    def import_config(self):
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
            messagebox.showerror("Import Failed", "File format not recognised.")
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
            if self.admin_mode:
                self.panels[-1].set_admin_mode(True)

        self.save_all()
        messagebox.showinfo("Import Complete", f"Loaded {len(accounts)} account(s) from file.")

    def export_config(self):
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
        panel = self._add_panel()
        if self.admin_mode:
            panel.set_admin_mode(True)
        self.save_all()
        self.canvas.after(100, lambda: self.canvas.yview_moveto(1.0))

    def remove_account(self, index):
        if len(self.panels) <= 1:
            return
        panel = self.panels[index]
        if panel.running:
            panel.stop_bot()
        panel.outer.destroy()
        self.panels.pop(index)
        for i, p in enumerate(self.panels):
            p.index = i
        self.save_all()

    def save_all(self):
        accounts = [p.get_data() for p in self.panels]
        save_config({"accounts": accounts})

    # ── Compatibility shims ──
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

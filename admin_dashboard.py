import tkinter as tk
from tkinter import ttk, messagebox
import requests
import json
import threading
import time
from datetime import datetime

# ─────────────────────────────────────────────
#  CONFIG — change these to match your server
# ─────────────────────────────────────────────
SERVER_URL = "https://karutabot-production.up.railway.app"
ADMIN_PASSWORD = "changeme"

# ─────────────────────────────────────────────
#  Color Palette (Discord-inspired dark theme)
# ─────────────────────────────────────────────
C = {
    "bg":       "#1e1f22",
    "surface":  "#2b2d31",
    "card":     "#313338",
    "border":   "#3f4147",
    "accent":   "#5865f2",
    "accent2":  "#4752c4",
    "green":    "#23a55a",
    "red":      "#f23f43",
    "yellow":   "#f0b232",
    "text":     "#dbdee1",
    "muted":    "#949ba4",
    "white":    "#ffffff",
}

def api(endpoint, payload={}):
    payload = {**payload, "password": ADMIN_PASSWORD}
    try:
        r = requests.post(f"{SERVER_URL}/{endpoint}", json=payload, timeout=5)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


class AdminDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Karuta Bot — Admin Dashboard")
        self.root.geometry("780x620")
        self.root.resizable(True, True)
        self.root.configure(bg=C["bg"])
        self.root.minsize(700, 500)

        self._build_ui()
        self.refresh_keys()

        # Auto-refresh every 10s
        self._auto_refresh()

    # ─────────────────────────────────────────
    #  UI BUILD
    # ─────────────────────────────────────────
    def _build_ui(self):
        # ── Header ──
        header = tk.Frame(self.root, bg=C["surface"], height=64)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text="🃏", font=("Helvetica", 22),
                 bg=C["surface"], fg=C["accent"]).pack(side="left", padx=(20, 6), pady=12)
        tk.Label(header, text="Karuta Bot Admin", font=("Helvetica", 16, "bold"),
                 bg=C["surface"], fg=C["text"]).pack(side="left", pady=12)

        self.server_status = tk.Label(header, text="⬤  Checking...",
                                       font=("Helvetica", 10), bg=C["surface"], fg=C["muted"])
        self.server_status.pack(side="right", padx=20)

        # ── Stats Bar ──
        stats_bar = tk.Frame(self.root, bg=C["bg"])
        stats_bar.pack(fill="x", padx=16, pady=(12, 4))

        self.stat_total  = self._stat_card(stats_bar, "TOTAL KEYS",   "0", C["accent"])
        self.stat_active = self._stat_card(stats_bar, "ACTIVE",       "0", C["green"])
        self.stat_revoked= self._stat_card(stats_bar, "REVOKED",      "0", C["red"])
        self.stat_online = self._stat_card(stats_bar, "ONLINE NOW",   "0", C["yellow"])

        # ── Main Content ──
        content = tk.Frame(self.root, bg=C["bg"])
        content.pack(fill="both", expand=True, padx=16, pady=8)

        # Left — Key list
        left = tk.Frame(content, bg=C["bg"])
        left.pack(side="left", fill="both", expand=True)

        list_header = tk.Frame(left, bg=C["bg"])
        list_header.pack(fill="x", pady=(0, 6))
        tk.Label(list_header, text="LICENSE KEYS", font=("Helvetica", 9, "bold"),
                 bg=C["bg"], fg=C["muted"]).pack(side="left")
        tk.Button(list_header, text="↻ Refresh", font=("Helvetica", 8),
                  bg=C["border"], fg=C["text"], relief="flat",
                  padx=8, pady=2, cursor="hand2",
                  command=self.refresh_keys).pack(side="right")

        # Treeview (table)
        tree_frame = tk.Frame(left, bg=C["card"])
        tree_frame.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.Treeview",
                         background=C["card"],
                         foreground=C["text"],
                         fieldbackground=C["card"],
                         rowheight=32,
                         font=("Courier", 9))
        style.configure("Dark.Treeview.Heading",
                         background=C["surface"],
                         foreground=C["muted"],
                         font=("Helvetica", 8, "bold"),
                         relief="flat")
        style.map("Dark.Treeview",
                  background=[("selected", C["accent2"])],
                  foreground=[("selected", C["white"])])

        cols = ("key", "label", "status", "created")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                  style="Dark.Treeview", selectmode="browse")
        self.tree.heading("key",     text="KEY")
        self.tree.heading("label",   text="USER")
        self.tree.heading("status",  text="STATUS")
        self.tree.heading("created", text="CREATED")
        self.tree.column("key",     width=190, minwidth=150)
        self.tree.column("label",   width=100, minwidth=80)
        self.tree.column("status",  width=80,  minwidth=60)
        self.tree.column("created", width=130, minwidth=100)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.tag_configure("active",  foreground=C["green"])
        self.tree.tag_configure("revoked", foreground=C["red"])

        # ── Action Buttons ──
        actions = tk.Frame(left, bg=C["bg"])
        actions.pack(fill="x", pady=(8, 0))

        tk.Button(actions, text="🗑  Revoke Selected",
                  font=("Helvetica", 10, "bold"),
                  bg=C["red"], fg=C["white"], activebackground="#c0323a",
                  activeforeground=C["white"], relief="flat",
                  padx=14, pady=6, cursor="hand2",
                  command=self.revoke_selected).pack(side="left", padx=(0, 8))

        tk.Button(actions, text="✓  Reactivate Selected",
                  font=("Helvetica", 10, "bold"),
                  bg=C["green"], fg=C["white"], activebackground="#1a8a47",
                  activeforeground=C["white"], relief="flat",
                  padx=14, pady=6, cursor="hand2",
                  command=self.reactivate_selected).pack(side="left")

        # Right — Generate panel
        right = tk.Frame(content, bg=C["surface"], width=220)
        right.pack(side="right", fill="y", padx=(12, 0))
        right.pack_propagate(False)

        tk.Label(right, text="GENERATE KEY", font=("Helvetica", 9, "bold"),
                 bg=C["surface"], fg=C["muted"]).pack(anchor="w", padx=16, pady=(16, 8))

        tk.Label(right, text="Friend's Name / Label",
                 font=("Helvetica", 9), bg=C["surface"], fg=C["muted"]).pack(anchor="w", padx=16)

        self.label_var = tk.StringVar()
        label_entry = tk.Entry(right, textvariable=self.label_var,
                               bg=C["card"], fg=C["text"], insertbackground=C["text"],
                               relief="flat", font=("Helvetica", 10), width=22)
        label_entry.pack(padx=16, pady=(4, 12), ipady=6, fill="x")

        tk.Button(right, text="+ Generate Key",
                  font=("Helvetica", 10, "bold"),
                  bg=C["accent"], fg=C["white"], activebackground=C["accent2"],
                  activeforeground=C["white"], relief="flat",
                  padx=12, pady=8, cursor="hand2",
                  command=self.generate_key).pack(padx=16, fill="x")

        # Generated key display
        tk.Label(right, text="LAST GENERATED", font=("Helvetica", 9, "bold"),
                 bg=C["surface"], fg=C["muted"]).pack(anchor="w", padx=16, pady=(20, 4))

        self.gen_key_var = tk.StringVar(value="—")
        gen_frame = tk.Frame(right, bg=C["card"])
        gen_frame.pack(fill="x", padx=16)

        self.gen_key_label = tk.Label(gen_frame, textvariable=self.gen_key_var,
                                       font=("Courier", 8), bg=C["card"],
                                       fg=C["accent"], wraplength=180, justify="left")
        self.gen_key_label.pack(side="left", padx=8, pady=8)

        tk.Button(right, text="📋 Copy Key",
                  font=("Helvetica", 9),
                  bg=C["border"], fg=C["text"], relief="flat",
                  padx=10, pady=4, cursor="hand2",
                  command=self.copy_key).pack(padx=16, pady=(4, 0), fill="x")

        # Server config
        tk.Label(right, text="SERVER CONFIG", font=("Helvetica", 9, "bold"),
                 bg=C["surface"], fg=C["muted"]).pack(anchor="w", padx=16, pady=(20, 4))

        tk.Label(right, text="Server URL", font=("Helvetica", 9),
                 bg=C["surface"], fg=C["muted"]).pack(anchor="w", padx=16)

        self.server_var = tk.StringVar(value=SERVER_URL)
        server_entry = tk.Entry(right, textvariable=self.server_var,
                                bg=C["card"], fg=C["text"], insertbackground=C["text"],
                                relief="flat", font=("Helvetica", 9), width=22)
        server_entry.pack(padx=16, pady=(4, 8), ipady=5, fill="x")

        tk.Label(right, text="Admin Password", font=("Helvetica", 9),
                 bg=C["surface"], fg=C["muted"]).pack(anchor="w", padx=16)

        self.pass_var = tk.StringVar(value=ADMIN_PASSWORD)
        pass_entry = tk.Entry(right, textvariable=self.pass_var, show="•",
                              bg=C["card"], fg=C["text"], insertbackground=C["text"],
                              relief="flat", font=("Helvetica", 9), width=22)
        pass_entry.pack(padx=16, pady=(4, 8), ipady=5, fill="x")

        tk.Button(right, text="💾 Save Config",
                  font=("Helvetica", 9),
                  bg=C["border"], fg=C["text"], relief="flat",
                  padx=10, pady=4, cursor="hand2",
                  command=self.save_config).pack(padx=16, fill="x")

        # ── Status bar ──
        self.statusbar = tk.Label(self.root, text="Ready",
                                   font=("Helvetica", 8), bg=C["surface"],
                                   fg=C["muted"], anchor="w", padx=12)
        self.statusbar.pack(fill="x", side="bottom", ipady=4)

    def _stat_card(self, parent, label, value, color):
        frame = tk.Frame(parent, bg=C["card"], padx=20, pady=12)
        frame.pack(side="left", fill="x", expand=True, padx=(0, 8))

        val_lbl = tk.Label(frame, text=value, font=("Helvetica", 22, "bold"),
                            bg=C["card"], fg=color)
        val_lbl.pack(anchor="w")
        tk.Label(frame, text=label, font=("Helvetica", 8, "bold"),
                 bg=C["card"], fg=C["muted"]).pack(anchor="w")
        return val_lbl

    # ─────────────────────────────────────────
    #  Actions
    # ─────────────────────────────────────────
    def set_status(self, msg):
        self.statusbar.config(text=msg)

    def api_call(self, endpoint, payload={}):
        global SERVER_URL, ADMIN_PASSWORD
        SERVER_URL = self.server_var.get().strip()
        ADMIN_PASSWORD = self.pass_var.get().strip()
        return api(endpoint, payload)

    def refresh_keys(self):
        def _fetch():
            data = self.api_call("admin/list")
            self.root.after(0, lambda: self._populate_keys(data))

        threading.Thread(target=_fetch, daemon=True).start()
        self._check_server_status()

    def _populate_keys(self, data):
        if "error" in data:
            self.set_status(f"❌ Error: {data['error']}")
            return

        keys = data.get("keys", {})
        sessions = data.get("sessions", {})

        # Clear tree
        for row in self.tree.get_children():
            self.tree.delete(row)

        total = len(keys)
        active = sum(1 for v in keys.values() if v.get("active"))
        revoked = total - active
        online = sum(1 for k in sessions if k in keys and keys[k].get("active"))

        self.stat_total.config(text=str(total))
        self.stat_active.config(text=str(active))
        self.stat_revoked.config(text=str(revoked))
        self.stat_online.config(text=str(online))

        for key, info in sorted(keys.items(), key=lambda x: x[1].get("created", 0), reverse=True):
            is_active = info.get("active", False)
            is_online = key in sessions and is_active

            status_text = "🟢 online" if is_online else ("✅ active" if is_active else "❌ revoked")
            created = datetime.fromtimestamp(info.get("created", 0)).strftime("%Y-%m-%d %H:%M")
            tag = "active" if is_active else "revoked"

            self.tree.insert("", "end", iid=key,
                              values=(key, info.get("label", "—"), status_text, created),
                              tags=(tag,))

        self.set_status(f"Refreshed at {datetime.now().strftime('%H:%M:%S')}  •  {total} keys total")

    def generate_key(self):
        label = self.label_var.get().strip()
        if not label:
            messagebox.showwarning("Missing Label", "Please enter a name/label for this key.")
            return

        def _gen():
            data = self.api_call("admin/generate", {"label": label})
            self.root.after(0, lambda: self._on_generated(data))

        threading.Thread(target=_gen, daemon=True).start()
        self.set_status("Generating key...")

    def _on_generated(self, data):
        if "error" in data:
            messagebox.showerror("Error", data["error"])
            return
        key = data.get("key", "")
        self.gen_key_var.set(key)
        self.label_var.set("")
        self.set_status(f"✅ Generated key for {data.get('label')}")
        self.refresh_keys()

    def copy_key(self):
        key = self.gen_key_var.get()
        if key and key != "—":
            self.root.clipboard_clear()
            self.root.clipboard_append(key)
            self.set_status("📋 Key copied to clipboard!")

    def revoke_selected(self):
        selected = self.tree.focus()
        if not selected:
            messagebox.showinfo("No Selection", "Select a key first.")
            return

        label = self.tree.item(selected)["values"][1]
        if not messagebox.askyesno("Revoke Key", f"Revoke key for '{label}'? They won't be able to use the bot."):
            return

        def _revoke():
            data = self.api_call("admin/revoke", {"key": selected})
            self.root.after(0, lambda: self._handle_result(data, "revoked"))

        threading.Thread(target=_revoke, daemon=True).start()

    def reactivate_selected(self):
        selected = self.tree.focus()
        if not selected:
            messagebox.showinfo("No Selection", "Select a key first.")
            return

        def _activate():
            data = self.api_call("admin/reactivate", {"key": selected})
            self.root.after(0, lambda: self._handle_result(data, "reactivated"))

        threading.Thread(target=_activate, daemon=True).start()

    def _handle_result(self, data, action):
        if data.get("success"):
            self.set_status(f"✅ Key {action} successfully.")
            self.refresh_keys()
        else:
            messagebox.showerror("Error", data.get("error", "Something went wrong."))

    def save_config(self):
        global SERVER_URL, ADMIN_PASSWORD
        SERVER_URL = self.server_var.get().strip()
        ADMIN_PASSWORD = self.pass_var.get().strip()
        self.set_status("✅ Config saved for this session.")

    def _check_server_status(self):
        def _ping():
            try:
                r = requests.get(f"{self.server_var.get().strip()}/ping", timeout=3)
                online = r.status_code == 200
            except:
                online = False
            self.root.after(0, lambda: self.server_status.config(
                text="⬤  Server Online" if online else "⬤  Server Offline",
                fg=C["green"] if online else C["red"]
            ))
        threading.Thread(target=_ping, daemon=True).start()

    def _auto_refresh(self):
        self.refresh_keys()
        self.root.after(10_000, self._auto_refresh)


if __name__ == "__main__":
    root = tk.Tk()
    app = AdminDashboard(root)
    root.mainloop()

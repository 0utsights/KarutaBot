import tkinter as tk
from tkinter import ttk, messagebox
import requests
import threading
from datetime import datetime

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
SERVER_URL     = "https://aeyori-production.up.railway.app"
ADMIN_PASSWORD = "8764abc213"

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

def api_get(endpoint, params={}):
    try:
        r = requests.get(f"{SERVER_URL}{endpoint}", params=params, timeout=5)
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def api_post(endpoint, payload={}):
    try:
        r = requests.post(f"{SERVER_URL}{endpoint}", params=payload, timeout=5)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


class AdminDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("Aeyori — Admin Dashboard")
        self.root.geometry("820x640")
        self.root.resizable(True, True)
        self.root.configure(bg=C["bg"])
        self.root.minsize(700, 500)
        self._build_ui()
        self.refresh_keys()
        self._auto_refresh()

    def _build_ui(self):
        # Header
        header = tk.Frame(self.root, bg=C["surface"], height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="🃏", font=("Helvetica", 22),
                 bg=C["surface"], fg=C["accent"]).pack(side="left", padx=(20, 6), pady=12)
        tk.Label(header, text="Aeyori Admin", font=("Helvetica", 16, "bold"),
                 bg=C["surface"], fg=C["text"]).pack(side="left", pady=12)
        self.server_status = tk.Label(header, text="⬤  Checking...",
                                       font=("Helvetica", 10), bg=C["surface"], fg=C["muted"])
        self.server_status.pack(side="right", padx=20)

        # Stats bar
        stats_bar = tk.Frame(self.root, bg=C["bg"])
        stats_bar.pack(fill="x", padx=16, pady=(12, 4))
        self.stat_total  = self._stat_card(stats_bar, "TOTAL KEYS", "0", C["accent"])
        self.stat_active = self._stat_card(stats_bar, "ACTIVE",     "0", C["green"])
        self.stat_expired= self._stat_card(stats_bar, "EXPIRED",    "0", C["red"])

        # Content
        content = tk.Frame(self.root, bg=C["bg"])
        content.pack(fill="both", expand=True, padx=16, pady=8)

        # Left — key list
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

        tree_frame = tk.Frame(left, bg=C["card"])
        tree_frame.pack(fill="both", expand=True)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.Treeview",
                         background=C["card"], foreground=C["text"],
                         fieldbackground=C["card"], rowheight=32,
                         font=("Courier", 9))
        style.configure("Dark.Treeview.Heading",
                         background=C["surface"], foreground=C["muted"],
                         font=("Helvetica", 8, "bold"), relief="flat")
        style.map("Dark.Treeview",
                  background=[("selected", C["accent2"])],
                  foreground=[("selected", C["white"])])

        cols = ("key", "tier", "user", "expires", "status")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                  style="Dark.Treeview", selectmode="browse")
        self.tree.heading("key",     text="KEY")
        self.tree.heading("tier",    text="TIER")
        self.tree.heading("user",    text="USER ID")
        self.tree.heading("expires", text="EXPIRES")
        self.tree.heading("status",  text="STATUS")
        self.tree.column("key",     width=200, minwidth=160)
        self.tree.column("tier",    width=80,  minwidth=60)
        self.tree.column("user",    width=120, minwidth=80)
        self.tree.column("expires", width=140, minwidth=100)
        self.tree.column("status",  width=80,  minwidth=60)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.tree.tag_configure("active",  foreground=C["green"])
        self.tree.tag_configure("expired", foreground=C["red"])
        self.tree.tag_configure("unused",  foreground=C["muted"])

        # Action buttons
        actions = tk.Frame(left, bg=C["bg"])
        actions.pack(fill="x", pady=(8, 0))
        tk.Button(actions, text="🗑  Revoke Selected",
                  font=("Helvetica", 10, "bold"),
                  bg=C["red"], fg=C["white"], activebackground="#c0323a",
                  activeforeground=C["white"], relief="flat",
                  padx=14, pady=6, cursor="hand2",
                  command=self.revoke_selected).pack(side="left", padx=(0, 8))

        # Right — generate panel
        right = tk.Frame(content, bg=C["surface"], width=240)
        right.pack(side="right", fill="y", padx=(12, 0))
        right.pack_propagate(False)

        tk.Label(right, text="GENERATE KEY", font=("Helvetica", 9, "bold"),
                 bg=C["surface"], fg=C["muted"]).pack(anchor="w", padx=16, pady=(16, 8))

        tk.Label(right, text="Tier", font=("Helvetica", 9),
                 bg=C["surface"], fg=C["muted"]).pack(anchor="w", padx=16)
        self.tier_var = tk.StringVar(value="basic")
        tier_menu = ttk.Combobox(right, textvariable=self.tier_var,
                                  values=["basic", "standard", "premium"],
                                  state="readonly", width=20)
        tier_menu.pack(padx=16, pady=(4, 12), fill="x")

        tk.Label(right, text="Admin Password", font=("Helvetica", 9),
                 bg=C["surface"], fg=C["muted"]).pack(anchor="w", padx=16)
        self.pass_var = tk.StringVar(value=ADMIN_PASSWORD)
        tk.Entry(right, textvariable=self.pass_var, show="•",
                 bg=C["card"], fg=C["text"], insertbackground=C["text"],
                 relief="flat", font=("Helvetica", 9), width=22).pack(
                 padx=16, pady=(4, 12), ipady=5, fill="x")

        tk.Button(right, text="+ Generate Key",
                  font=("Helvetica", 10, "bold"),
                  bg=C["accent"], fg=C["white"], activebackground=C["accent2"],
                  activeforeground=C["white"], relief="flat",
                  padx=12, pady=8, cursor="hand2",
                  command=self.generate_key).pack(padx=16, fill="x")

        tk.Label(right, text="LAST GENERATED", font=("Helvetica", 9, "bold"),
                 bg=C["surface"], fg=C["muted"]).pack(anchor="w", padx=16, pady=(20, 4))

        self.gen_key_var = tk.StringVar(value="—")
        gen_frame = tk.Frame(right, bg=C["card"])
        gen_frame.pack(fill="x", padx=16)
        tk.Label(gen_frame, textvariable=self.gen_key_var,
                 font=("Courier", 8), bg=C["card"],
                 fg=C["accent"], wraplength=180, justify="left").pack(padx=8, pady=8)

        tk.Button(right, text="📋 Copy Key",
                  font=("Helvetica", 9),
                  bg=C["border"], fg=C["text"], relief="flat",
                  padx=10, pady=4, cursor="hand2",
                  command=self.copy_key).pack(padx=16, pady=(4, 0), fill="x")

        # Status bar
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

    def set_status(self, msg):
        self.statusbar.config(text=msg)

    def refresh_keys(self):
        def _fetch():
            data = api_get("/api/admin/keys",
                           {"x_admin_password": self.pass_var.get().strip()})
            self.root.after(0, lambda: self._populate_keys(data))
        threading.Thread(target=_fetch, daemon=True).start()
        self._check_server_status()

    def _populate_keys(self, data):
        if "error" in data or "detail" in data:
            self.set_status(f"❌ {data.get('error', data.get('detail', 'Error'))}")
            return

        keys = data.get("keys", [])
        now = datetime.utcnow()

        for row in self.tree.get_children():
            self.tree.delete(row)

        active = 0
        expired = 0

        for k in keys:
            expires_raw = k.get("expires_at")
            if expires_raw:
                try:
                    expires_dt = datetime.fromisoformat(expires_raw.replace("Z", ""))
                    is_active = expires_dt > now
                    expires_str = expires_dt.strftime("%Y-%m-%d %H:%M")
                except:
                    is_active = False
                    expires_str = expires_raw
            else:
                is_active = False
                expires_str = "Not activated"

            has_user = bool(k.get("user_id"))
            if is_active:
                status = "✅ active"
                tag = "active"
                active += 1
            elif has_user:
                status = "❌ expired"
                tag = "expired"
                expired += 1
            else:
                status = "⏳ unused"
                tag = "unused"

            user_display = (k.get("user_id") or "—")[:12] + "..."  if k.get("user_id") else "—"

            self.tree.insert("", "end", iid=k["key"],
                              values=(k["key"], k.get("tier", "?"),
                                      user_display, expires_str, status),
                              tags=(tag,))

        self.stat_total.config(text=str(len(keys)))
        self.stat_active.config(text=str(active))
        self.stat_expired.config(text=str(expired))
        self.set_status(f"Refreshed — {len(keys)} keys total")

    def generate_key(self):
        tier = self.tier_var.get()
        pw   = self.pass_var.get().strip()
        if not pw:
            messagebox.showwarning("Password Required", "Enter your admin password first.")
            return

        def _gen():
            data = api_post("/api/admin/keys/generate",
                            {"tier": tier, "x_admin_password": pw})
            self.root.after(0, lambda: self._on_generated(data))

        threading.Thread(target=_gen, daemon=True).start()
        self.set_status("Generating key...")

    def _on_generated(self, data):
        if "error" in data or "detail" in data:
            messagebox.showerror("Error", data.get("error", data.get("detail")))
            return
        key = data.get("key", "")
        self.gen_key_var.set(key)
        self.set_status(f"✅ Generated {data.get('tier')} key")
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
        if not messagebox.askyesno("Revoke Key", f"Revoke key:\n{selected}?"):
            return

        def _revoke():
            data = api_post("/api/admin/keys/revoke",
                            {"key": selected,
                             "x_admin_password": self.pass_var.get().strip()})
            self.root.after(0, lambda: self._handle_result(data, "revoked"))

        threading.Thread(target=_revoke, daemon=True).start()

    def _handle_result(self, data, action):
        if "error" in data or "detail" in data:
            messagebox.showerror("Error", data.get("error", data.get("detail")))
        else:
            self.set_status(f"✅ Key {action}")
            self.refresh_keys()

    def _check_server_status(self):
        def _ping():
            try:
                r = requests.get(f"{SERVER_URL}/", timeout=3)
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
        self.root.after(15_000, self._auto_refresh)


if __name__ == "__main__":
    root = tk.Tk()
    app = AdminDashboard(root)
    root.mainloop()

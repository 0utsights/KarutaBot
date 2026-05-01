import threading
import tkinter as tk

from license import start_heartbeat, release_key, validate_key
from config import C, FULL_ACCESS_FEATURES, LICENSED_MODE
from gui import KarutaApp


def show_key_screen():
    win = tk.Tk()
    win.title("Aeyori — Activate")
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

    result = {"key": None, "features": {}}

    def try_activate(event=None):
        key = key_var.get().strip()
        if not key:
            return
        status.config(text="Validating...", fg=C["muted"])
        win.update()
        success, reason, features = validate_key(key)
        if success:
            result["key"] = key
            result["features"] = features
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
    return result["key"], result["features"]


def launch():
    key = None
    features = dict(FULL_ACCESS_FEATURES)

    if LICENSED_MODE:
        key, features = show_key_screen()
        if not key:
            return
        threading.Thread(target=start_heartbeat, args=(key,), daemon=True).start()

    root = tk.Tk()
    app  = KarutaApp(root, features=features)

    if LICENSED_MODE:
        root.protocol("WM_DELETE_WINDOW", lambda: [release_key(key), root.destroy()])
    else:
        root.protocol("WM_DELETE_WINDOW", root.destroy)

    root.mainloop()


if __name__ == "__main__":
    launch()

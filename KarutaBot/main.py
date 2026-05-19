import threading
import tkinter as tk

from config import C, FULL_ACCESS_FEATURES, LICENSED_MODE
from gui import KarutaApp


def _load_license_api():
    try:
        from license import release_key, start_heartbeat, validate_key
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "LICENSED_MODE is enabled, but license.py is not available in this build."
        ) from exc

    return release_key, start_heartbeat, validate_key


def show_key_screen():
    _, _, validate_key = _load_license_api()

    win = tk.Tk()
    win.title("Aeyori — Activate")
    win.geometry("360x220")
    win.resizable(False, False)
    win.configure(bg=C["bg"])
    win.eval("tk::PlaceWindow . center")

    tk.Label(
        win,
        text="🔑 Enter License Key",
        font=("Helvetica", 14, "bold"),
        bg=C["bg"],
        fg=C["text"],
    ).pack(pady=(28, 8))

    key_var = tk.StringVar()
    entry = tk.Entry(
        win,
        textvariable=key_var,
        font=("Helvetica", 11),
        bg=C["dark"],
        fg=C["text"],
        insertbackground=C["white"],
        relief="flat",
        width=30,
    )
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

    tk.Button(
        win,
        text="Activate",
        font=("Helvetica", 11, "bold"),
        bg=C["accent"],
        fg=C["white"],
        activebackground=C["accent2"],
        activeforeground=C["white"],
        relief="flat",
        padx=20,
        pady=7,
        cursor="hand2",
        command=try_activate,
    ).pack(pady=12)

    win.mainloop()
    return result["key"], result["features"]


def launch():
    key = None
    features = dict(FULL_ACCESS_FEATURES)
    release_key = None

    if LICENSED_MODE:
        release_key, start_heartbeat, _ = _load_license_api()
        key, features = show_key_screen()
        if not key:
            return
        threading.Thread(target=start_heartbeat, args=(key,), daemon=True).start()

    root = tk.Tk()
    app = KarutaApp(root, features=features)

    if LICENSED_MODE:
        def _on_close():
            try:
                release_key(key)
            except Exception:
                pass
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", _on_close)
    else:
        root.protocol("WM_DELETE_WINDOW", root.destroy)

    root.mainloop()


if __name__ == "__main__":
    launch()

import sys
import subprocess
import importlib
import os
import multiprocessing
multiprocessing.freeze_support()

# ─────────────────────────────────────────────────────────
#  This is the ENTRY POINT that PyInstaller compiles.
#  It checks/installs dependencies silently, shows a
#  friendly loading screen, then launches the real app.
# ─────────────────────────────────────────────────────────

REQUIRED_PACKAGES = [
    ("discord",    "discord.py-self"),
    ("requests",   "requests"),
    ("PIL",        "Pillow"),
    ("cv2",        "opencv-python-headless"),
    ("torch",      "torch"),
    ("torchvision","torchvision"),
    ("easyocr",    "easyocr"),
]

def check_and_install():
    """Returns list of packages that needed installing."""
    needed = []
    for import_name, pip_name in REQUIRED_PACKAGES:
        try:
            importlib.import_module(import_name)
        except ImportError:
            needed.append((import_name, pip_name))
    return needed

def install_package(pip_name, log_callback):
    log_callback(f"Installing {pip_name}...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", pip_name, "--quiet"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        log_callback(f"❌ Failed to install {pip_name}: {result.stderr}")
        return False
    log_callback(f"✅ {pip_name} installed!")
    return True


# ─────────────────────────────────────────────────────────
#  Loading Screen (shown while installing)
# ─────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import ttk

C = {
    "bg":      "#1e1f22",
    "card":    "#2b2d31",
    "accent":  "#5865f2",
    "green":   "#23a55a",
    "red":     "#f23f43",
    "text":    "#dbdee1",
    "muted":   "#949ba4",
}

class LoadingScreen:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Aeyori")
        self.root.geometry("400x280")
        self.root.resizable(False, False)
        self.root.configure(bg=C["bg"])
        self.root.eval("tk::PlaceWindow . center")

        # Prevent closing during install
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)

        self._build()

    def _build(self):
        tk.Label(self.root, text="🃏", font=("Helvetica", 36),
                 bg=C["bg"], fg=C["accent"]).pack(pady=(28, 4))

        tk.Label(self.root, text="Aeyori", font=("Helvetica", 18, "bold"),
                 bg=C["bg"], fg=C["text"]).pack()

        self.status_label = tk.Label(self.root, text="Checking requirements...",
                                      font=("Helvetica", 10), bg=C["bg"], fg=C["muted"])
        self.status_label.pack(pady=(16, 6))

        # Progress bar
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Accent.Horizontal.TProgressbar",
                         troughcolor=C["card"],
                         background=C["accent"],
                         bordercolor=C["card"],
                         lightcolor=C["accent"],
                         darkcolor=C["accent"])

        self.progress = ttk.Progressbar(self.root, style="Accent.Horizontal.TProgressbar",
                                         orient="horizontal", length=300, mode="determinate")
        self.progress.pack(pady=4)

        self.log_label = tk.Label(self.root, text="",
                                   font=("Courier", 8), bg=C["bg"], fg=C["muted"])
        self.log_label.pack(pady=(8, 0))

    def set_status(self, text):
        self.status_label.config(text=text)
        self.root.update()

    def set_log(self, text):
        self.log_label.config(text=text)
        self.root.update()

    def set_progress(self, value):
        self.progress["value"] = value
        self.root.update()

    def close(self):
        self.root.destroy()

    def show_error(self, msg):
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self.status_label.config(text="Setup Failed :(", fg=C["red"])
        self.log_label.config(text=msg, fg=C["red"], wraplength=350)
        tk.Button(self.root, text="Close", font=("Helvetica", 10),
                  bg=C["red"], fg="white", relief="flat",
                  padx=20, pady=6, command=self.root.destroy).pack(pady=12)
        self.root.mainloop()


# ─────────────────────────────────────────────────────────
#  Main Bootstrap Logic
# ─────────────────────────────────────────────────────────
def main():
    screen = LoadingScreen()
    all_ok = True
    screen.set_status("Checking requirements...")
    screen.set_progress(10)
    screen.root.update()

    needed = check_and_install()

    if not needed:
        # All good, go straight in
        screen.set_status("All good! Launching...")
        screen.set_progress(100)
        screen.root.update()
        screen.root.after(600, screen.close)
        screen.root.mainloop()
    else:
        # Need to install some packages
        screen.set_status(f"First time setup — installing {len(needed)} package(s) (may take a few minutes)...")
        screen.set_progress(20)

        step = 70 / len(needed)
        current = 20
        all_ok = True

        for import_name, pip_name in needed:
            screen.set_log(f"Installing {pip_name}...")
            ok = install_package(pip_name, screen.set_log)
            if not ok:
                screen.show_error(f"Could not install '{pip_name}'.\nPlease check your internet connection and try again.")
                return
            current += step
            screen.set_progress(int(current))

        screen.set_progress(95)
        screen.set_status("Almost ready...")
        screen.set_log("Setup complete!")
        screen.root.update()
        screen.root.after(800, screen.close)
        screen.root.mainloop()

    if not all_ok:
        return

    # ── Launch the real app ──
    import main  # your main app file
    main.launch()


if __name__ == "__main__":
    main()

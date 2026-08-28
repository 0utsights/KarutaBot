import sys
import os
import importlib
import multiprocessing
multiprocessing.freeze_support()

# ─────────────────────────────────────────────────────────
#  Single-instance guard — exit immediately if already running
# ─────────────────────────────────────────────────────────
import ctypes
_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "AeyoriAppMutex")
if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
    sys.exit(0)

# ─────────────────────────────────────────────────────────
#  Find real Python (not the frozen exe)
# ─────────────────────────────────────────────────────────
def _find_python():
    """Return path to a real python.exe, not the frozen exe."""
    # If not frozen, sys.executable is already Python
    if not getattr(sys, "frozen", False):
        return sys.executable
    # Search PATH for python
    import shutil
    for name in ("python", "python3", "python.exe", "python3.exe"):
        p = shutil.which(name)
        if p and p != sys.executable:
            return p
    return None

PYTHON = _find_python()

REQUIRED_PACKAGES = [
    ("discord",     "discord.py-self"),
    ("requests",    "requests"),
    ("PIL",         "Pillow"),
    ("cv2",         "opencv-python-headless"),
    ("torch",       "torch"),
    ("torchvision", "torchvision"),
    ("easyocr",     "easyocr"),
]

def check_needed():
    needed = []
    for import_name, pip_name in REQUIRED_PACKAGES:
        try:
            importlib.import_module(import_name)
        except ImportError:
            needed.append((import_name, pip_name))
    return needed

def install_package(pip_name, log_callback):
    if not PYTHON:
        log_callback("❌ Python not found on PATH — cannot install packages.")
        return False
    import subprocess
    log_callback(f"Installing {pip_name}...")
    result = subprocess.run(
        [PYTHON, "-m", "pip", "install", pip_name, "--quiet"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        log_callback(f"❌ Failed: {result.stderr.strip()}")
        return False
    log_callback(f"✅ {pip_name} installed")
    return True


# ─────────────────────────────────────────────────────────
#  Loading Screen
# ─────────────────────────────────────────────────────────
import tkinter as tk
from tkinter import ttk

C = {
    "bg":    "#1e1f22",
    "card":  "#2b2d31",
    "accent":"#5865f2",
    "green": "#23a55a",
    "red":   "#f23f43",
    "text":  "#dbdee1",
    "muted": "#949ba4",
}

class LoadingScreen:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Aeyori")
        self.root.geometry("400x280")
        self.root.resizable(False, False)
        self.root.configure(bg=C["bg"])
        self.root.eval("tk::PlaceWindow . center")
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
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("A.Horizontal.TProgressbar",
                        troughcolor=C["card"], background=C["accent"],
                        bordercolor=C["card"], lightcolor=C["accent"], darkcolor=C["accent"])
        self.progress = ttk.Progressbar(self.root, style="A.Horizontal.TProgressbar",
                                        orient="horizontal", length=300, mode="determinate")
        self.progress.pack(pady=4)
        self.log_label = tk.Label(self.root, text="", font=("Courier", 8),
                                  bg=C["bg"], fg=C["muted"])
        self.log_label.pack(pady=(8, 0))

    def set_status(self, text):
        self.status_label.config(text=text)
        self.root.update()

    def set_log(self, text):
        self.log_label.config(text=text[-60:])  # truncate long lines
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
#  Main
# ─────────────────────────────────────────────────────────
def main():
    screen = LoadingScreen()
    screen.set_status("Checking requirements...")
    screen.set_progress(10)
    screen.root.update()

    needed = check_needed()

    if not needed:
        screen.set_status("All good! Launching...")
        screen.set_progress(100)
        screen.root.update()
        screen.root.after(600, screen.close)
        screen.root.mainloop()
    else:
        screen.set_status(f"First time setup — installing {len(needed)} package(s)...")
        screen.set_progress(20)
        step = 70 / len(needed)
        current = 20

        for import_name, pip_name in needed:
            screen.set_log(f"Installing {pip_name}...")
            ok = install_package(pip_name, screen.set_log)
            if not ok:
                screen.show_error(
                    f"Could not install '{pip_name}'.\n"
                    "Please check your internet connection and try again."
                )
                return
            current += step
            screen.set_progress(int(current))

        screen.set_progress(95)
        screen.set_status("Almost ready...")
        screen.set_log("Setup complete!")
        screen.root.update()
        screen.root.after(800, screen.close)
        screen.root.mainloop()

    import main
    main.launch()


if __name__ == "__main__":
    main()

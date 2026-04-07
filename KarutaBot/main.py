import tkinter as tk
from gui import KarutaApp


def launch():
    root = tk.Tk()
    app  = KarutaApp(root)
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()


if __name__ == "__main__":
    launch()

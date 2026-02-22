"""
ocr_viewer.py — Live OCR visualization window

Shows a popup during drop processing with:
- The 3 card crops side by side
- Name / series / print regions highlighted
- What OCR read from each region
"""

import tkinter as tk
from PIL import Image, ImageTk, ImageDraw
from config import C


class OCRViewer:
    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title("OCR Live View")
        self.win.configure(bg=C["bg"])
        self.win.resizable(False, False)
        self.win.geometry("860x520")

        tk.Label(self.win, text="🔍 OCR Processing",
                 font=("Helvetica", 13, "bold"),
                 bg=C["bg"], fg=C["text"]).pack(pady=(12, 4))

        self.status = tk.Label(self.win, text="Waiting for drop...",
                               font=("Helvetica", 9), bg=C["bg"], fg=C["muted"])
        self.status.pack()

        # Card frames
        cards_frame = tk.Frame(self.win, bg=C["bg"])
        cards_frame.pack(fill="x", padx=16, pady=10)

        self.card_frames = []
        self.card_images = []   # keep refs alive
        self.card_labels = []   # image labels
        self.card_texts  = []   # text result labels

        for i in range(3):
            cf = tk.Frame(cards_frame, bg=C["card"], padx=8, pady=8)
            cf.grid(row=0, column=i, padx=6)

            tk.Label(cf, text=f"Card {i+1}", font=("Helvetica", 9, "bold"),
                     bg=C["card"], fg=C["muted"]).pack()

            # Image display (will show annotated crop)
            img_label = tk.Label(cf, bg=C["dark"])
            img_label.pack(pady=4)

            # Text results
            result_frame = tk.Frame(cf, bg=C["card"])
            result_frame.pack(fill="x")

            rows = {}
            for field, colour in [("name", C["red"]), ("series", C["green"]), ("print", C["accent"])]:
                row = tk.Frame(result_frame, bg=C["card"])
                row.pack(fill="x", pady=1)
                tk.Label(row, text=f"{field}:", font=("Courier", 8, "bold"),
                         bg=C["card"], fg=colour, width=7, anchor="w").pack(side="left")
                val = tk.Label(row, text="—", font=("Courier", 8),
                               bg=C["card"], fg=C["text"], anchor="w", wraplength=200)
                val.pack(side="left")
                rows[field] = val

            self.card_frames.append(cf)
            self.card_images.append(None)
            self.card_labels.append(img_label)
            self.card_texts.append(rows)

        # Bottom status bar
        self.bottom = tk.Label(self.win, text="",
                               font=("Helvetica", 10, "bold"),
                               bg=C["bg"], fg=C["green"])
        self.bottom.pack(pady=8)

    def set_status(self, text):
        self.status.config(text=text)
        self.win.update()

    def show_full_image(self, pil_img):
        """Show the full drop image (annotated with region boxes) on all card slots."""
        w, h = pil_img.size
        card_w = w // 3
        target_h = 240

        for i in range(3):
            x0 = i * card_w
            crop = pil_img.crop((x0, 0, x0 + card_w, h))
            # Scale to fit display
            scale = target_h / h
            new_size = (int(card_w * scale), target_h)
            crop = crop.resize(new_size, Image.LANCZOS)
            tk_img = ImageTk.PhotoImage(crop)
            self.card_images[i] = tk_img
            self.card_labels[i].config(image=tk_img)

        self.win.update()

    def update_card(self, card_idx, field, raw_text, cleaned):
        """Update a single field result for a card."""
        rows = self.card_texts[card_idx]
        if field in rows:
            display = str(cleaned) if cleaned else f"({raw_text[:20]!r})"
            rows[field].config(text=display)
        self.win.update()

    def show_result(self, cards):
        """Show final grab decision."""
        parts = []
        for c in cards:
            parts.append(f"#{c['index']+1} {c['name']} | #{c['print']} | {c['wishes']}♥")
        self.bottom.config(text="  ·  ".join(parts))
        self.win.update()

    def highlight_processing(self, card_idx, field):
        """Flash a field label to show it's being processed."""
        rows = self.card_texts[card_idx]
        if field in rows:
            rows[field].config(text="scanning...", fg=C["yellow"])
        self.win.update()

    def close(self):
        try:
            self.win.destroy()
        except:
            pass


def annotate_image(pil_img, name_top, name_bottom, series_top, series_bottom, print_top, print_bottom):
    """Draw coloured region boxes on the full drop image for display."""
    vis = pil_img.copy()
    draw = ImageDraw.Draw(vis, "RGBA")
    w, h = vis.size
    card_w = w // 3

    regions = {
        "name":   (name_top,   name_bottom,   (255, 80,  80,  100)),
        "series": (series_top, series_bottom, (80,  200, 80,  100)),
        "print":  (print_top,  print_bottom,  (80,  80,  255, 100)),
    }

    for i in range(3):
        x0 = i * card_w
        x1 = x0 + card_w
        for label, (top, bot, colour) in regions.items():
            y0 = int(h * top)
            y1 = int(h * bot)
            draw.rectangle([x0, y0, x1, y1], fill=colour)

    return vis

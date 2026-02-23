"""
debug_crops.py — imports from ocr.py so debug always matches production.
Usage: C:\Python313\python.exe debug_crops.py "<image_url>"
"""

import sys
import os
import requests
from io import BytesIO
from PIL import Image, ImageDraw

# ── TUNE THESE ────────────────────────────────────────────────────────────────
NAME_TOP      = 0.12
NAME_BOTTOM   = 0.26
SERIES_TOP    = 0.76
SERIES_BOTTOM = 0.89
PRINT_TOP     = 0.87
PRINT_BOTTOM  = 0.94
# ─────────────────────────────────────────────────────────────────────────────

OUT_DIR = "ocr_debug"
os.makedirs(OUT_DIR, exist_ok=True)


def download(url):
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGB")


def annotate(img):
    width, height = img.size
    card_w = width // 3
    vis = img.copy()
    draw = ImageDraw.Draw(vis, "RGBA")
    regions = {
        "name":   (NAME_TOP,   NAME_BOTTOM,   (255, 60,  60,  140)),
        "series": (SERIES_TOP, SERIES_BOTTOM, (60,  200, 60,  140)),
        "print":  (PRINT_TOP,  PRINT_BOTTOM,  (60,  60,  255, 140)),
    }
    for card_i in range(3):
        x0 = card_i * card_w
        x1 = x0 + card_w
        for label, (top, bot, colour) in regions.items():
            y0 = int(height * top)
            y1 = int(height * bot)
            draw.rectangle([x0, y0, x1, y1], fill=colour)
            draw.text((x0 + 4, y0 + 2), f"[{label}]", fill=(255, 255, 255, 255))
    for i in [1, 2]:
        draw.line([(i * card_w, 0), (i * card_w, height)], fill=(255, 255, 0, 200), width=2)
    path = os.path.join(OUT_DIR, "annotated.png")
    vis.save(path)
    print(f"Saved: {path}  ({width}x{height}  card_w={card_w})")


def crop_and_ocr(img):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ocr import _preprocess, _preprocess_print, _clean_name, _clean_print, _get_reader, _ocr_text, _ocr_print

    reader = _get_reader(log_fn=print)

    width, height = img.size
    card_w = width // 3
    regions = {
        "name":   (NAME_TOP,   NAME_BOTTOM),
        "series": (SERIES_TOP, SERIES_BOTTOM),
        "print":  (PRINT_TOP,  PRINT_BOTTOM),
    }

    print()
    for card_i in range(3):
        x0 = card_i * card_w
        print(f"── Card {card_i+1} ──────────────────────────")
        for label, (top, bot) in regions.items():
            y0 = int(height * top)
            y1 = int(height * bot)
            crop = img.crop((x0, y0, x0 + card_w, y1))
            crop.save(os.path.join(OUT_DIR, f"card{card_i+1}_{label}.png"))

            proc = _preprocess_print(crop) if label == "print" else _preprocess(crop)
            proc.save(os.path.join(OUT_DIR, f"card{card_i+1}_{label}_processed.png"))

            raw     = _ocr_print(reader, proc) if label == "print" else _ocr_text(reader, proc)
            cleaned = _clean_print(raw) if label == "print" else _clean_name(raw)
            print(f"   {label:6s}: raw={raw!r:30s}  ->  {cleaned!r}")
        print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: C:\\Python313\\python.exe debug_crops.py \"<url>\"")
        sys.exit(1)
    img = download(sys.argv[1])
    print(f"Downloaded: {img.size[0]}x{img.size[1]}px")
    annotate(img)
    crop_and_ocr(img)
    print(f"All debug images saved to ./{OUT_DIR}/")

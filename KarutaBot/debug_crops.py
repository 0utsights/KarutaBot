"""
debug_crops.py — Run this standalone to tune OCR crop regions.

Usage:
    python debug_crops.py <image_url>

It will:
  1. Download the image
  2. Save annotated.png showing current crop regions as coloured overlays
  3. Save all 9 individual crops (3 cards x name/series/print)
  4. Run OCR on each and print results

Adjust the percentages at the top of this file until annotated.png
looks correct, then copy them into ocr.py.
"""

import sys
import os
import re
import requests
from io import BytesIO
from PIL import Image, ImageDraw

# ── TUNE THESE ────────────────────────────────────────────────────────────────
NAME_TOP      = 0.12   # top of name banner
NAME_BOTTOM   = 0.26   # bottom of name banner
SERIES_TOP    = 0.74   # top of series name
SERIES_BOTTOM = 0.89   # bottom of series name
PRINT_TOP     = 0.87   # top of print number
PRINT_BOTTOM  = 0.94   # bottom of print number
# ─────────────────────────────────────────────────────────────────────────────

OUT_DIR = "ocr_debug"
os.makedirs(OUT_DIR, exist_ok=True)

def download(url):
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGB")

def annotate(img):
    """Save image with coloured overlays showing crop regions."""
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

    # Draw card dividers
    for i in [1, 2]:
        x = i * card_w
        draw.line([(x, 0), (x, height)], fill=(255, 255, 0, 200), width=2)

    path = os.path.join(OUT_DIR, "annotated.png")
    vis.save(path)
    print(f"\n✅ Saved annotated image → {path}")
    print(f"   Image size: {width}x{height}   Card width: {card_w}px")
    print(f"\n   Current regions (px):")
    print(f"   NAME   y={int(height*NAME_TOP):3d} → {int(height*NAME_BOTTOM):3d}  ({NAME_TOP*100:.0f}%-{NAME_BOTTOM*100:.0f}%)")
    print(f"   SERIES y={int(height*SERIES_TOP):3d} → {int(height*SERIES_BOTTOM):3d}  ({SERIES_TOP*100:.0f}%-{SERIES_BOTTOM*100:.0f}%)")
    print(f"   PRINT  y={int(height*PRINT_TOP):3d} → {int(height*PRINT_BOTTOM):3d}  ({PRINT_TOP*100:.0f}%-{PRINT_BOTTOM*100:.0f}%)")

def crop_and_ocr(img):
    """Crop all regions, save them, run OCR, print results."""
    try:
        import pytesseract
        tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(tesseract_path):
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
        ocr_available = True
    except ImportError:
        print("\n⚠ pytesseract not installed — crops saved but no OCR output.")
        ocr_available = False

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
        x1 = x0 + card_w
        print(f"── Card {card_i+1} ──────────────────────────")
        for label, (top, bot) in regions.items():
            y0 = int(height * top)
            y1 = int(height * bot)
            crop = img.crop((x0, y0, x1, y1))

            # Save raw crop
            raw_path = os.path.join(OUT_DIR, f"card{card_i+1}_{label}.png")
            crop.save(raw_path)

            # Save upscaled greyscale (what tesseract actually sees)
            proc = crop.resize((crop.width * 3, crop.height * 3), Image.LANCZOS).convert("L")
            proc_path = os.path.join(OUT_DIR, f"card{card_i+1}_{label}_processed.png")
            proc.save(proc_path)

            if ocr_available:
                if label == "print":
                    raw = pytesseract.image_to_string(proc, config="--psm 7 -c tessedit_char_whitelist=0123456789·•.O ").strip()
                    # Clean: fix O->0, take only first number group
                    fixed = raw.replace('O','0').replace('o','0')
                    parts = re.split(r'[·•\*\.]\s*\d', fixed)
                    m = re.search(r'(\d{3,})', parts[0])
                    cleaned = int(m.group(1)) if m else "??"
                else:
                    raw = pytesseract.image_to_string(proc, config="--psm 7").strip()
                    cleaned = re.sub(r'\s+', ' ', re.sub(r'[^\x20-\x7E]', '', raw)).strip()
                print(f"   {label:6s}: raw={raw!r:30s}  →  {cleaned!r}")
            else:
                print(f"   {label:6s}: saved to {raw_path}")
        print()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_crops.py <image_url>")
        print("Example: python debug_crops.py https://cdn.discordapp.com/attachments/.../card.webp")
        sys.exit(1)

    url = sys.argv[1]
    print(f"Downloading: {url[:80]}...")
    img = download(url)
    print(f"Downloaded: {img.size[0]}x{img.size[1]}px")

    annotate(img)
    crop_and_ocr(img)

    print(f"\n📁 All debug images saved to ./{OUT_DIR}/")
    print("Open annotated.png to see the coloured crop regions.")
    print("Red=name  Green=series  Blue=print")
    print("\nIf regions are off, edit the percentages at the top of this file and re-run.")

"""
ocr.py — Karuta drop image parser

Layout of a Karuta drop image (3 cards side by side):
  ┌──────────┬──────────┬──────────┐
  │ [NAME  ] │ [NAME  ] │ [NAME  ] │  ← name banner (~top 12%)
  │          │          │          │
  │  [art]   │  [art]   │  [art]   │  ← card art
  │          │          │          │
  │ [series] │ [series] │ [series] │  ← series name
  │ [print ] │ [print ] │ [print ] │  ← print number (~bottom 8%)
  └──────────┴──────────┴──────────┘

We crop each card into its own column, then crop the name and print
regions within each column and run Tesseract on them.
"""

import re
import os
import requests
from io import BytesIO
from PIL import Image

# ── Tesseract config ──────────────────────────────────────────────────────────
# Tesseract must be installed separately:
#   Windows: https://github.com/UB-Mannheim/tesseract/wiki
#   Add to PATH or set TESSERACT_PATH below
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def _setup_tesseract():
    import pytesseract
    if os.path.exists(TESSERACT_PATH):
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    return pytesseract

# ── Card region percentages (relative to each card column) ───────────────────
# Adjust these if OCR is reading wrong areas
NAME_TOP    = 0.00   # name banner starts at top
NAME_BOTTOM = 0.13   # name banner ends at ~13% down
PRINT_TOP   = 0.88   # print number starts at ~88% down
PRINT_BOTTOM = 1.00  # print number goes to bottom

# ── Debug mode: save crops to disk so you can inspect them ───────────────────
DEBUG_CROPS = True
DEBUG_DIR   = "ocr_debug"


def parse_drop_image(image_url, log_fn=None):
    """
    Download a Karuta drop image and return list of 3 card dicts:
        [{"name": str, "print": int, "wishes": 0, "index": int}, ...]
    Returns None if anything fails.
    """
    def log(msg):
        if log_fn:
            log_fn(msg)

    try:
        pytesseract = _setup_tesseract()
    except ImportError:
        log("⚠ pytesseract not installed. Run: pip install pytesseract")
        return None
    except Exception as e:
        log(f"⚠ Tesseract setup error: {e}")
        return None

    # ── Download image ────────────────────────────────────────────────────────
    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content)).convert("RGB")
        log(f"🖼 Downloaded drop image: {img.size[0]}x{img.size[1]}px")
    except Exception as e:
        log(f"⚠ Failed to download drop image: {e}")
        return None

    if DEBUG_CROPS:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        img.save(os.path.join(DEBUG_DIR, "full_drop.png"))

    width, height = img.size
    card_width = width // 3

    cards = []

    for i in range(3):
        # ── Crop card column ──────────────────────────────────────────────────
        x_start = i * card_width
        x_end   = x_start + card_width
        card_img = img.crop((x_start, 0, x_end, height))

        if DEBUG_CROPS:
            card_img.save(os.path.join(DEBUG_DIR, f"card_{i+1}_full.png"))

        # ── Crop name region ──────────────────────────────────────────────────
        name_crop = card_img.crop((
            0,
            int(height * NAME_TOP),
            card_width,
            int(height * NAME_BOTTOM)
        ))

        # ── Crop print number region ──────────────────────────────────────────
        print_crop = card_img.crop((
            0,
            int(height * PRINT_TOP),
            card_width,
            int(height * PRINT_BOTTOM)
        ))

        if DEBUG_CROPS:
            name_crop.save(os.path.join(DEBUG_DIR, f"card_{i+1}_name.png"))
            print_crop.save(os.path.join(DEBUG_DIR, f"card_{i+1}_print.png"))

        # ── Preprocess: upscale + greyscale for better OCR accuracy ──────────
        name_crop  = _preprocess(name_crop)
        print_crop = _preprocess(print_crop)

        # ── Run OCR ───────────────────────────────────────────────────────────
        ocr_config = "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -!:'.,- "
        raw_name  = pytesseract.image_to_string(name_crop,  config="--psm 7").strip()
        raw_print = pytesseract.image_to_string(print_crop, config="--psm 7 -c tessedit_char_whitelist=0123456789·•.O ").strip()

        log(f"🔍 Card {i+1} raw OCR — name: {raw_name!r}  print: {raw_print!r}")

        name      = _clean_name(raw_name)
        print_num = _clean_print(raw_print)

        log(f"   → name: {name!r}  print: #{print_num}")

        cards.append({
            "name":   name if name else f"Card {i+1}",
            "print":  print_num,
            "wishes": 0,
            "index":  i,
        })

    return cards


# ── Image preprocessing ───────────────────────────────────────────────────────
def _preprocess(img):
    """Upscale and convert to greyscale — significantly improves OCR accuracy."""
    scale = 3
    new_size = (img.width * scale, img.height * scale)
    img = img.resize(new_size, Image.LANCZOS)
    img = img.convert("L")  # greyscale
    return img


# ── Text cleanup ──────────────────────────────────────────────────────────────
def _clean_name(raw):
    """Strip junk from OCR'd card name."""
    # Remove non-printable characters
    name = re.sub(r'[^\x20-\x7E]', '', raw)
    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _clean_print(raw):
    """
    Extract print number from OCR output.
    Format in image: '80299 · 1'  or  '80299·1'
    OCR might return: '8O299 . 1' or '80299 1' etc.
    We want just the first number (the print number, not the edition).
    """
    # Fix common OCR substitutions
    fixed = raw.replace('O', '0').replace('o', '0').replace('l', '1').replace('I', '1')
    # Find first sequence of digits
    match = re.search(r'(\d{3,})', fixed)
    if match:
        return int(match.group(1))
    return 99999  # unknown — treated as worst card


# ── Tesseract installation check ──────────────────────────────────────────────
def check_tesseract():
    """Returns (installed: bool, message: str)"""
    try:
        pytesseract = _setup_tesseract()
        pytesseract.get_tesseract_version()
        return True, "Tesseract is installed and ready."
    except Exception as e:
        return False, str(e)

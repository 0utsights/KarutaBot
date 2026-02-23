"""
ocr.py — Aeyori image parser using EasyOCR

EasyOCR is installed via pip and downloads its model automatically on first run.
No separate program installation required.
"""

import re
import os
import requests
from io import BytesIO
from PIL import Image

# ── Card region percentages ────────────────────────────────────────────────────
NAME_TOP      = 0.12
NAME_BOTTOM   = 0.26
SERIES_TOP    = 0.76
SERIES_BOTTOM = 0.89
PRINT_TOP     = 0.87
PRINT_BOTTOM  = 0.94

DEBUG_CROPS = True
DEBUG_DIR   = "ocr_debug"

# ── EasyOCR reader (loaded once, reused) ──────────────────────────────────────
_reader = None

def _get_reader(log_fn=None):
    """Load EasyOCR reader, downloading model on first use (~100MB, one time)."""
    global _reader
    if _reader is not None:
        return _reader
    try:
        import easyocr
    except ImportError:
        raise RuntimeError(
            "EasyOCR not installed. Run: pip install easyocr"
        )
    if log_fn:
        log_fn("Loading OCR model (first run may take a moment)...")
    _reader = easyocr.Reader(["en"], verbose=False)
    if log_fn:
        log_fn("OCR model loaded.")
    return _reader


def check_easyocr():
    """Returns (available: bool, message: str)"""
    try:
        import easyocr
        return True, "EasyOCR is available."
    except ImportError:
        return False, "EasyOCR not installed. Run: pip install easyocr"


# ── Text cleanup ───────────────────────────────────────────────────────────────
def _fix_mid_word_caps(name):
    """Lowercase a capital letter that follows another capital and precedes lowercase.
    Fixes OCR artefacts like MObile->Mobile, ZEta->Zeta, GOdfather->Godfather.
    Leaves intentional all-caps (ARMS, DBZ) and normal title-case untouched.
    """
    return re.sub(r'(?<=[A-Z])([A-Z])(?=[a-z])', lambda m: m.group(1).lower(), name)


def _clean_name(raw):
    """Strip junk, fix mid-word stray caps, and restore missing spaces from OCR output."""
    name = re.sub(r'[^\x20-\x7E]', ' ', raw)
    name = re.sub(r'^[^A-Z]+', '', name)
    name = re.sub(r'[^A-Za-z0-9!?:.]+$', '', name)
    name = re.sub(r'\s+', ' ', name).strip()

    # Fix mid-word stray caps first (MObile->Mobile).
    # Must run before prefix strip so M in MObile isn't mistaken for a junk prefix.
    name = _fix_mid_word_caps(name)

    # Strip 2+ leading all-caps chars before lowercase — frame border noise (CUlifis->Lifis).
    # After fix_mid_word_caps, real words like "Mobile" are clean so this won't touch them.
    name = re.sub(r'^[A-Z]{2,}(?=[a-z])', '', name)

    # Capitalise if strip left a lowercase start
    if name and name[0].islower():
        name = name[0].upper() + name[1:]

    # Fix lone ! misread as I between words (e.g. "The Girl ! Like" -> "The Girl I Like")
    name = re.sub(r'(?<= )!(?= )', 'I', name)

    # Restore spaces EasyOCR dropped between words
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    name = re.sub(r'([A-Z])([A-Z][a-z])', r'\1 \2', name)
    name = re.sub(r'([A-Za-z])(\d)', r'\1 \2', name)
    return name.strip()


def _clean_print(raw):
    """Return print number, splitting off edition digit when dot separator present."""
    fixed = raw.strip().replace('O', '0').replace('o', '0').replace('l', '1')
    if '.' in fixed:
        before = fixed.split('.')[0]
        m = re.search(r'\d{3,}', before)
        if m:
            return int(m.group())
    for group in re.findall(r'\d+', fixed):
        if len(group) >= 3:
            return int(group)
    return 99999


# ── Image preprocessing ────────────────────────────────────────────────────────
def _preprocess(img, trim_sides=0.18):
    """Trim frame edges and upscale for better OCR accuracy."""
    from PIL import ImageEnhance
    w, h = img.size
    trim = int(w * trim_sides)
    img = img.crop((trim, 0, w - trim, h))
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    return img


def _preprocess_print(img):
    """Upscale print region — EasyOCR handles the binarization internally."""
    w, h = img.size
    img = img.crop((int(w * 0.25), 0, w - int(w * 0.05), h))
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    return img


# ── EasyOCR helpers ────────────────────────────────────────────────────────────
def _ocr_text(reader, img):
    """Run EasyOCR on an image, return concatenated text."""
    import numpy as np
    arr = np.array(img.convert("RGB"))
    results = reader.readtext(arr, detail=0, paragraph=True)
    return " ".join(results).strip()


def _ocr_print(reader, img):
    """Run EasyOCR on print region, allow only digits and dot."""
    import numpy as np
    arr = np.array(img.convert("RGB"))
    results = reader.readtext(arr, detail=0, allowlist="0123456789.")
    return " ".join(results).strip()


# ── Main parser ────────────────────────────────────────────────────────────────
def parse_drop_image(image_url, log_fn=None, viewer=None):
    def log(msg):
        if log_fn:
            log_fn(msg)

    try:
        reader = _get_reader(log_fn=log_fn)
    except Exception as e:
        log(f"OCR setup error: {e}")
        return None

    try:
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content)).convert("RGB")
        log(f"Downloaded drop image: {img.size[0]}x{img.size[1]}px")
    except Exception as e:
        log(f"Failed to download drop image: {e}")
        return None

    if DEBUG_CROPS:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        img.save(os.path.join(DEBUG_DIR, "full_drop.png"))

    if viewer:
        try:
            from ocr_viewer import annotate_image
            viewer.show_full_image(annotate_image(img,
                NAME_TOP, NAME_BOTTOM, SERIES_TOP, SERIES_BOTTOM, PRINT_TOP, PRINT_BOTTOM))
            viewer.set_status("Scanning cards...")
        except Exception as e:
            log(f"Viewer error: {e}")

    width, height = img.size
    card_width = width // 3
    cards = []

    for i in range(3):
        x_start  = i * card_width
        card_img = img.crop((x_start, 0, x_start + card_width, height))

        name_crop   = card_img.crop((0, int(height * NAME_TOP),    card_width, int(height * NAME_BOTTOM)))
        series_crop = card_img.crop((0, int(height * SERIES_TOP),  card_width, int(height * SERIES_BOTTOM)))
        print_crop  = card_img.crop((0, int(height * PRINT_TOP),   card_width, int(height * PRINT_BOTTOM)))

        if DEBUG_CROPS:
            name_crop.save(os.path.join(DEBUG_DIR,   f"card{i+1}_name.png"))
            series_crop.save(os.path.join(DEBUG_DIR, f"card{i+1}_series.png"))
            print_crop.save(os.path.join(DEBUG_DIR,  f"card{i+1}_print.png"))

        name_crop   = _preprocess(name_crop)
        series_crop = _preprocess(series_crop)
        print_crop  = _preprocess_print(print_crop)

        if DEBUG_CROPS:
            name_crop.save(os.path.join(DEBUG_DIR,   f"card{i+1}_name_processed.png"))
            series_crop.save(os.path.join(DEBUG_DIR, f"card{i+1}_series_processed.png"))
            print_crop.save(os.path.join(DEBUG_DIR,  f"card{i+1}_print_processed.png"))

        if viewer: viewer.highlight_processing(i, "name")
        raw_name   = _ocr_text(reader, name_crop)

        if viewer: viewer.highlight_processing(i, "series")
        raw_series = _ocr_text(reader, series_crop)

        if viewer: viewer.highlight_processing(i, "print")
        raw_print  = _ocr_print(reader, print_crop)

        log(f"Card {i+1} raw — name: {raw_name!r}  series: {raw_series!r}  print: {raw_print!r}")

        name      = _clean_name(raw_name)
        series    = _clean_name(raw_series)
        print_num = _clean_print(raw_print)

        log(f"   -> name: {name!r}  series: {series!r}  print: #{print_num}")

        if viewer:
            viewer.update_card(i, "name",   raw_name,   name)
            viewer.update_card(i, "series", raw_series, series)
            viewer.update_card(i, "print",  raw_print,  f"#{print_num}")

        cards.append({
            "name":   name if name else f"Card {i+1}",
            "series": series,
            "print":  print_num,
            "wishes": 0,
            "index":  i,
        })

    return cards

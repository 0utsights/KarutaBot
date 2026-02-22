"""
ocr.py — Karuta drop image parser
"""

import re
import os
import requests
from io import BytesIO
from PIL import Image

# ── Tesseract config ───────────────────────────────────────────────────────────
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

def _setup_tesseract():
    import pytesseract
    if os.path.exists(TESSERACT_PATH):
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
    return pytesseract

# ── Card region percentages ────────────────────────────────────────────────────
NAME_TOP      = 0.12
NAME_BOTTOM   = 0.26
SERIES_TOP    = 0.76
SERIES_BOTTOM = 0.89
PRINT_TOP     = 0.87
PRINT_BOTTOM  = 0.94

DEBUG_CROPS = True
DEBUG_DIR   = "ocr_debug"


# ── Text cleanup ───────────────────────────────────────────────────────────────
def _clean_name(raw):
    """Strip junk and restore missing spaces from OCR output."""
    # Replace non-printable chars and newlines with space
    name = re.sub(r'[^\x20-\x7E]', ' ', raw)
    # Strip everything before the first capital letter
    name = re.sub(r'^[^A-Z]+', '', name)
    # Strip trailing non-alphanumeric junk
    name = re.sub(r'[^A-Za-z0-9!?:.]+$', '', name)
    # Collapse whitespace
    name = re.sub(r'\s+', ' ', name).strip()
    # Restore spaces Tesseract dropped:
    # lowercase->uppercase: ShihoMatsuura -> Shiho Matsuura
    name = re.sub(r'([a-z])([A-Z])', r'\1 \2', name)
    # UPPER->Upper after another upper: ARMSProject -> ARMS Project
    name = re.sub(r'([A-Z])([A-Z][a-z])', r'\1 \2', name)
    # letter->digit: Thracia776 -> Thracia 776
    name = re.sub(r'([A-Za-z])(\d)', r'\1 \2', name)
    return name


def _clean_print(raw):
    """Return the first digit group with 3+ digits (the print number)."""
    fixed = raw.strip().replace('O', '0').replace('o', '0').replace('l', '1')
    for group in re.findall(r'\d+', fixed):
        if len(group) >= 3:
            return int(group)
    return 99999


# ── Image preprocessing ────────────────────────────────────────────────────────
def _otsu_threshold(arr):
    import numpy as np
    hist, _ = np.histogram(arr.flatten(), bins=256, range=(0, 256))
    total = arr.size
    sum_total = np.dot(np.arange(256), hist)
    current_max, threshold, sum_bg, weight_bg = 0, 128, 0, 0
    for t in range(256):
        weight_bg += hist[t]
        if weight_bg == 0 or weight_bg == total:
            continue
        weight_fg = total - weight_bg
        sum_bg += t * hist[t]
        mean_bg = sum_bg / weight_bg
        mean_fg = (sum_total - sum_bg) / weight_fg
        variance = weight_bg * weight_fg * (mean_bg - mean_fg) ** 2
        if variance > current_max:
            current_max, threshold = variance, t
    return threshold


def _preprocess(img, trim_sides=0.18):
    import numpy as np
    from PIL import ImageEnhance
    w, h = img.size
    trim = int(w * trim_sides)
    img = img.crop((trim, 0, w - trim, h))
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.0)
    arr = np.array(img)
    threshold = _otsu_threshold(arr)
    binarized = arr > threshold
    if np.mean(binarized) > 0.6:
        binarized = ~binarized
    return Image.fromarray(np.where(binarized, 255, 0).astype(np.uint8))


def _preprocess_print(img):
    import numpy as np
    from PIL import ImageEnhance
    w, h = img.size
    img = img.crop((int(w * 0.35), 0, w - int(w * 0.05), h))
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.5)
    arr = np.array(img)
    threshold = _otsu_threshold(arr)
    try:
        import pytesseract
        normal   = Image.fromarray(np.where(arr > threshold,  255, 0).astype(np.uint8))
        inverted = Image.fromarray(np.where(arr <= threshold, 255, 0).astype(np.uint8))
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789."
        raw_n = pytesseract.image_to_string(normal,   config=cfg).strip()
        raw_i = pytesseract.image_to_string(inverted, config=cfg).strip()
        digits_n = sum(c.isdigit() for c in raw_n)
        digits_i = sum(c.isdigit() for c in raw_i)
        return inverted if digits_i > digits_n else normal
    except Exception:
        binarized = arr > threshold
        if np.mean(binarized) > 0.6:
            binarized = ~binarized
        return Image.fromarray(np.where(binarized, 255, 0).astype(np.uint8))


# ── Main parser ────────────────────────────────────────────────────────────────
def parse_drop_image(image_url, log_fn=None, viewer=None):
    def log(msg):
        if log_fn:
            log_fn(msg)

    try:
        pytesseract = _setup_tesseract()
    except Exception as e:
        log(f"Tesseract setup error: {e}")
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

    name_cfg   = "--psm 13 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 !?:-."
    series_cfg = "--psm 13 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 !?:-."
    print_cfg  = "--psm 7 -c tessedit_char_whitelist=0123456789."

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
        raw_name   = pytesseract.image_to_string(name_crop,   config=name_cfg).strip()

        if viewer: viewer.highlight_processing(i, "series")
        raw_series = pytesseract.image_to_string(series_crop, config=series_cfg).strip()

        if viewer: viewer.highlight_processing(i, "print")
        raw_print  = pytesseract.image_to_string(print_crop,  config=print_cfg).strip()

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


# ── Tesseract check ────────────────────────────────────────────────────────────
def check_tesseract():
    try:
        pytesseract = _setup_tesseract()
        pytesseract.get_tesseract_version()
        return True, "Tesseract is installed and ready."
    except Exception as e:
        return False, str(e)

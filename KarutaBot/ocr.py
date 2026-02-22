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
NAME_TOP     = 0.12  # name banner starts slightly below top border
NAME_BOTTOM  = 0.26  # name banner ends at ~14% down
SERIES_TOP   = 0.76  # series name starts where art ends
SERIES_BOTTOM= 0.89  # series name ends just above print
PRINT_TOP    = 0.87  # print number starts at ~88% down
PRINT_BOTTOM = 0.94  # print number goes to bottom

# ── Debug mode: save crops to disk so you can inspect them ───────────────────
DEBUG_CROPS = True
DEBUG_DIR   = "ocr_debug"


def parse_drop_image(image_url, log_fn=None, viewer=None):
    """
    Download a Karuta drop image and return list of 3 card dicts:
        [{"name": str, "print": int, "wishes": 0, "index": int}, ...]
    Returns None if anything fails.
    viewer: optional OCRViewer instance for live visualization.
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

    # Show annotated image in viewer
    if viewer:
        try:
            from ocr_viewer import annotate_image
            annotated = annotate_image(img,
                NAME_TOP, NAME_BOTTOM, SERIES_TOP, SERIES_BOTTOM, PRINT_TOP, PRINT_BOTTOM)
            viewer.show_full_image(annotated)
            viewer.set_status("Scanning cards...")
        except Exception as e:
            log(f"⚠ Viewer error: {e}")

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

        # ── Crop regions ──────────────────────────────────────────────────────
        name_crop   = card_img.crop((0, int(height * NAME_TOP),    card_width, int(height * NAME_BOTTOM)))
        series_crop = card_img.crop((0, int(height * SERIES_TOP),  card_width, int(height * SERIES_BOTTOM)))
        print_crop  = card_img.crop((0, int(height * PRINT_TOP),   card_width, int(height * PRINT_BOTTOM)))

        if DEBUG_CROPS:
            name_crop.save(os.path.join(DEBUG_DIR,   f"card_{i+1}_name.png"))
            series_crop.save(os.path.join(DEBUG_DIR, f"card_{i+1}_series.png"))
            print_crop.save(os.path.join(DEBUG_DIR,  f"card_{i+1}_print.png"))

        # ── Preprocess: upscale + greyscale for better OCR accuracy ──────────
        name_crop   = _preprocess(name_crop)
        series_crop = _preprocess(series_crop)
        print_crop  = _preprocess_print(print_crop)

        # ── Run OCR ───────────────────────────────────────────────────────────
        if viewer: viewer.highlight_processing(i, "name")
        raw_name   = pytesseract.image_to_string(name_crop,   config="--psm 7").strip()

        if viewer: viewer.highlight_processing(i, "series")
        raw_series = pytesseract.image_to_string(series_crop, config="--psm 6").strip()

        if viewer: viewer.highlight_processing(i, "print")
        raw_print  = pytesseract.image_to_string(print_crop,  config="--psm 7 -c tessedit_char_whitelist=0123456789·•.O ").strip()

        log(f"🔍 Card {i+1} raw OCR — name: {raw_name!r}  series: {raw_series!r}  print: {raw_print!r}")

        name      = _clean_name(raw_name)
        series    = _clean_name(raw_series)
        print_num = _clean_print(raw_print)

        log(f"   → name: {name!r}  series: {series!r}  print: #{print_num}")

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


# ── Image preprocessing ───────────────────────────────────────────────────────
def _otsu_threshold(arr):
    """Compute Otsu optimal threshold for a numpy array."""
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


def _preprocess(img, trim_sides=0.15):
    """
    Preprocess a crop for OCR:
    1. Trim left/right edges to cut off frame decorations
    2. Upscale 3x
    3. Convert to greyscale
    4. Adaptive binarize using Otsu's method — works for any banner color
    5. Ensure text is dark on light background (what Tesseract expects)
    """
    import numpy as np
    from PIL import ImageEnhance

    # Trim sides more aggressively to remove frame border artifacts
    w, h = img.size
    trim = int(w * trim_sides)
    img = img.crop((trim, 0, w - trim, h))

    # Upscale
    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)

    # Greyscale + contrast boost
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.0)

    # Otsu threshold
    arr = np.array(img)
    threshold = _otsu_threshold(arr)
    binarized = (arr > threshold)

    # Ensure text is BLACK on WHITE background for Tesseract
    # The text region should be the minority (fewer pixels than background)
    # If more than 60% of pixels are "foreground", we have it inverted
    if np.mean(binarized) > 0.6:
        binarized = ~binarized

    result = np.where(binarized, 255, 0).astype(np.uint8)
    return Image.fromarray(result)


def _preprocess_print(img):
    """Special preprocessing for print number region — more aggressive side trim."""
    import numpy as np
    from PIL import ImageEnhance

    # Print number is in the right ~40% of the region, trim left heavily
    w, h = img.size
    img = img.crop((int(w * 0.35), 0, w - int(w * 0.05), h))

    img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.5)

    arr = np.array(img)
    threshold = _otsu_threshold(arr)

    # Try both normal and inverted — pick whichever Tesseract reads digits from
    try:
        import pytesseract
        normal   = Image.fromarray(np.where(arr > threshold, 255, 0).astype(np.uint8))
        inverted = Image.fromarray(np.where(arr <= threshold, 255, 0).astype(np.uint8))
        cfg = "--psm 7 -c tessedit_char_whitelist=0123456789·•.O "
        raw_n = pytesseract.image_to_string(normal,   config=cfg).strip()
        raw_i = pytesseract.image_to_string(inverted, config=cfg).strip()
        digits_n = len([c for c in raw_n if c.isdigit()])
        digits_i = len([c for c in raw_i if c.isdigit()])
        return inverted if digits_i > digits_n else normal
    except:
        # Fallback: use pixel ratio method
        binarized = arr > threshold
        if np.mean(binarized) > 0.6:
            binarized = ~binarized
        return Image.fromarray(np.where(binarized, 255, 0).astype(np.uint8))


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
    We want just the FIRST number (print), not the edition after the dot/separator.
    """
    # Fix common OCR substitutions
    fixed = raw.replace('O', '0').replace('o', '0').replace('l', '1').replace('I', '1')
    # Find ALL digit groups
    all_nums = re.findall(r'\d+', fixed)
    if not all_nums:
        return 99999
    # The print number is always the larger number (edition is 1, 2, 3 etc)
    # Filter to only numbers with 3+ digits (actual print numbers)
    big_nums = [int(n) for n in all_nums if len(n) >= 3]
    if big_nums:
        return big_nums[0]  # take first big number
    return 99999


# ── Visual region debugger ────────────────────────────────────────────────────
def save_annotated_debug(image_url):
    """
    Downloads drop image and saves a copy with coloured rectangles showing
    exactly which pixel regions are being cropped for name/series/print.
    Saves to ocr_debug/annotated.png — open this to tune the percentages.
    """
    from PIL import ImageDraw, ImageFont
    try:
        response = requests.get(image_url, timeout=10)
        img = Image.open(BytesIO(response.content)).convert("RGB")
    except Exception as e:
        print(f"Could not download: {e}")
        return

    width, height = img.size
    card_width = width // 3
    draw = ImageDraw.Draw(img, "RGBA")

    colours = {
        "name":   (255, 80,  80,  120),   # red
        "series": (80,  200, 80,  120),   # green
        "print":  (80,  80,  255, 120),   # blue
    }

    regions = {
        "name":   (NAME_TOP,    NAME_BOTTOM),
        "series": (SERIES_TOP,  SERIES_BOTTOM),
        "print":  (PRINT_TOP,   PRINT_BOTTOM),
    }

    for card_i in range(3):
        x0 = card_i * card_width
        x1 = x0 + card_width
        for label, (top_pct, bot_pct) in regions.items():
            y0 = int(height * top_pct)
            y1 = int(height * bot_pct)
            draw.rectangle([x0, y0, x1, y1], fill=colours[label])
            draw.text((x0 + 4, y0 + 2), label, fill=(255, 255, 255, 255))

    os.makedirs(DEBUG_DIR, exist_ok=True)
    out_path = os.path.join(DEBUG_DIR, "annotated.png")
    img.save(out_path)
    print(f"Saved annotated debug image to: {out_path}")
    print(f"Image size: {width}x{height}  Card width: {card_width}")
    print(f"Name   region: y={int(height*NAME_TOP)} to y={int(height*NAME_BOTTOM)}  ({NAME_TOP*100:.0f}%-{NAME_BOTTOM*100:.0f}%)")
    print(f"Series region: y={int(height*SERIES_TOP)} to y={int(height*SERIES_BOTTOM)}  ({SERIES_TOP*100:.0f}%-{SERIES_BOTTOM*100:.0f}%)")
    print(f"Print  region: y={int(height*PRINT_TOP)} to y={int(height*PRINT_BOTTOM)}  ({PRINT_TOP*100:.0f}%-{PRINT_BOTTOM*100:.0f}%)")


# ── Tesseract installation check ──────────────────────────────────────────────
def check_tesseract():
    """Returns (installed: bool, message: str)"""
    try:
        pytesseract = _setup_tesseract()
        pytesseract.get_tesseract_version()
        return True, "Tesseract is installed and ready."
    except Exception as e:
        return False, str(e)

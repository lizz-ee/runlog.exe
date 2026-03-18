"""
Minimal OCR for Marathon game state detection.

Detects:
  - SEARCHING  -> start recording (matchmaking screen, sits for 10s-3min)
  - PREPARE    -> stop recording  (yellow button, back in lobby)
  - READY UP   -> stop recording  (yellow button, back in lobby)
  - DEPLOYING  -> stop recording  (yellow button, back in lobby)
  - RUN        -> stop recording  (yellow button, back in lobby)

Uses easyocr with GPU acceleration. Model loads once, stays in memory.
"""

import easyocr
import numpy as np
from PIL import Image, ImageEnhance
import io
import time

# -- Singleton OCR reader ---------------------------------------------

_reader = None


def get_reader():
    """Lazy-load the easyocr reader (GPU). Takes ~3s on first call."""
    global _reader
    if _reader is None:
        print("[ocr] Loading easyocr (GPU)...")
        t0 = time.time()
        _reader = easyocr.Reader(['en'], gpu=True)
        print(f"[ocr] Loaded in {time.time()-t0:.1f}s")
    return _reader


# -- Scan regions (percentages of screen dimensions) -------------------

# Bottom center: yellow button bar (PREPARE, READY UP, RUN, DEPLOYING)
BUTTON_REGION = (0.30, 0.82, 0.70, 0.96)

# Center: matchmaking text (SEARCHING...)
SEARCH_REGION = (0.30, 0.50, 0.70, 0.65)


def detect_button_text(jpeg_bytes: bytes) -> str | None:
    """Check for game state text in known screen regions.

    Scans two regions:
    1. Bottom center — yellow button bar (lobby buttons)
    2. Center — matchmaking "SEARCHING..." text

    Returns:
        'SEARCHING', 'READY_UP', 'DEPLOYING', 'PREPARE', 'RUN', or None.
    """
    try:
        img = Image.open(io.BytesIO(jpeg_bytes))
        w, h = img.size
        reader = get_reader()

        # --- Check button region first (lobby yellow buttons) ---
        x1, y1, x2, y2 = BUTTON_REGION
        crop = img.crop((int(w * x1), int(h * y1), int(w * x2), int(h * y2)))
        crop = ImageEnhance.Contrast(crop).enhance(2.0)
        arr = np.array(crop)
        results = reader.readtext(arr)

        texts = [r[1] for r in results if r[2] > 0.4]
        joined = ' '.join(texts).upper().strip()

        if joined:
            print(f"[ocr] Button: \"{joined}\"")

        if 'READY UP' in joined or 'READYUP' in joined or 'READY_UP' in joined:
            return 'READY_UP'
        if 'DEPLOYING' in joined:
            return 'DEPLOYING'
        if 'PREPARE' in joined and 'PREPARED' not in joined:
            return 'PREPARE'
        if joined == 'RUN' or ' RUN ' in f' {joined} ':
            return 'RUN'

        # --- Check center region for SEARCHING (matchmaking) ---
        x1, y1, x2, y2 = SEARCH_REGION
        crop2 = img.crop((int(w * x1), int(h * y1), int(w * x2), int(h * y2)))
        crop2 = ImageEnhance.Contrast(crop2).enhance(2.0)
        arr2 = np.array(crop2)
        results2 = reader.readtext(arr2)

        texts2 = [r[1] for r in results2 if r[2] > 0.4]
        joined2 = ' '.join(texts2).upper().strip()

        if joined2:
            print(f"[ocr] Center: \"{joined2}\"")

        if 'SEARCHING' in joined2:
            return 'SEARCHING'

        return None
    except Exception:
        return None

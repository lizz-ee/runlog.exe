"""
Minimal OCR for Marathon game state detection.

Only detects two button texts:
  - READY UP  -> start recording (player is in lobby, run is about to begin)
  - PREPARE   -> stop recording  (player returned to menu, run is over)

Also detects DEPLOYING (countdown after READY UP) and RUN (rare variant).
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


# -- Button region ----------------------------------------------------
# Bottom center of screen where READY UP / PREPARE buttons appear.
# Coordinates are percentages of screen dimensions (works at any resolution).
BUTTON_REGION = (0.30, 0.82, 0.70, 0.92)


def detect_button_text(jpeg_bytes: bytes) -> str | None:
    """Check the button region for READY UP or PREPARE text.

    Args:
        jpeg_bytes: Raw JPEG image bytes from the detection capture.

    Returns:
        'READY_UP', 'DEPLOYING', 'PREPARE', 'RUN', or None.
    """
    try:
        img = Image.open(io.BytesIO(jpeg_bytes))
        w, h = img.size
        x1, y1, x2, y2 = BUTTON_REGION
        crop = img.crop((int(w * x1), int(h * y1), int(w * x2), int(h * y2)))

        # Boost contrast to make button text pop
        crop = ImageEnhance.Contrast(crop).enhance(2.0)

        arr = np.array(crop)
        reader = get_reader()
        results = reader.readtext(arr)

        # Join all detected text fragments with confidence > 0.4
        texts = [r[1] for r in results if r[2] > 0.4]
        joined = ' '.join(texts).upper()

        # Match against known button labels
        if 'READY UP' in joined or 'READYUP' in joined or 'READY_UP' in joined:
            return 'READY_UP'
        if 'DEPLOYING' in joined:
            return 'DEPLOYING'
        if 'PREPARE' in joined:
            return 'PREPARE'
        if 'RUN' in joined and len(joined) < 15:
            return 'RUN'

        return None
    except Exception:
        return None

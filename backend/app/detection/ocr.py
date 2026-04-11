"""
OCR detection for Marathon game state.

Three scan regions:
  - OCR.DEPLOY (center)  — map name on deployment loading screen → START recording
  - OCR.ENDGAME (upper)  — //RUN_COMPLETE banner → log timestamp for stats extraction
  - OCR.LOBBY (bottom)   — PREPARE/READY_UP buttons → STOP recording / capture loadout

Uses Windows.Media.Ocr via winocr (~16ms per call, hardware-accelerated).
EasyOCR is NOT used here — it stays in the alpha stats pipeline only.
"""

import io

from PIL import Image

# -- Windows OCR (winocr) -----------------------------------------------------

try:
    from winocr import recognize_pil_sync as _winocr_sync
    _WINOCR_AVAILABLE = True
except ImportError:
    _WINOCR_AVAILABLE = False
    print("[ocr] WARNING: winocr not available — install it: pip install winocr")


def _ocr_pil(img: Image.Image, label: str = "") -> str:
    """Run Windows OCR on a PIL image. Returns uppercase text. Safe from any thread."""
    if not _WINOCR_AVAILABLE:
        return ""
    try:
        result = _winocr_sync(img, "en")
        text = (result.get("text") or "").upper().strip()
        if text and label:
            print(f"[ocr] {label}: {text[:120]!r}")
        return text
    except Exception as e:
        print(f"[ocr] Error ({label}): {e}")
        return ""


# -- Scan regions (percentage of screen dimensions) ---------------------------

# OCR.DEPLOY — center screen, deployment loading screen (map name + coordinates)
DEPLOY_REGION = (0.35, 0.38, 0.65, 0.65)

# OCR.ENDGAME — upper center, //RUN_COMPLETE banner
ENDGAME_REGION = (0.28, 0.135, 0.72, 0.275)

# OCR.LOBBY — bottom center, PREPARE/READY_UP buttons
LOBBY_REGION = (0.33, 0.72, 0.67, 0.89)

# Known map names for deployment detection
MAP_NAMES = ["PERIMETER", "OUTPOST", "DIRE MARSH", "CRYO ARCHIVE"]


def _crop_region(img: Image.Image, region: tuple) -> Image.Image:
    """Crop a percentage-based region from an image."""
    w, h = img.size
    x1, y1, x2, y2 = region
    return img.crop((int(w * x1), int(h * y1), int(w * x2), int(h * y2)))


def detect_game_state(jpeg_bytes: bytes, scan_mode: str = "lobby") -> dict | None:
    """Scan ONE OCR region based on current state machine mode.

    scan_mode: 'lobby' | 'deploy' | 'endgame' | 'postgame'

    Returns a detection dict or None.
    """
    try:
        img = Image.open(io.BytesIO(jpeg_bytes))

        if scan_mode == "deploy":
            text = _ocr_pil(_crop_region(img, DEPLOY_REGION), "DEPLOY")
            if text:
                for map_name in MAP_NAMES:
                    if map_name in text:
                        is_ranked = "RANKED" in text or "RANK" in text
                        return {"type": "deploy", "map_name": map_name,
                                "is_ranked": is_ranked, "text": text}
            return None

        if scan_mode == "postgame":
            text = _ocr_pil(_crop_region(img, DEPLOY_REGION), "POSTGAME")
            if text:
                if "EXFILTRAT" in text:
                    return {"type": "exfiltrated", "map_name": None, "text": text}
                if "ELIMINATED" in text or "ELIMINAT" in text:
                    return {"type": "eliminated", "map_name": None, "text": text}
            return None

        if scan_mode == "endgame":
            text = _ocr_pil(_crop_region(img, ENDGAME_REGION), "ENDGAME")
            if text and "RUN" in text and "COMPLETE" in text:
                return {"type": "endgame", "map_name": None, "text": text}
            return None

        # 'lobby' — scan LOBBY region
        text = _ocr_pil(_crop_region(img, LOBBY_REGION), "LOBBY")
        if text:
            if "EXFILTRAT" in text:
                return {"type": "exfiltrated", "map_name": None, "text": text}
            if "ELIMINATED" in text or "ELIMINAT" in text:
                return {"type": "eliminated", "map_name": None, "text": text}
            if "DEPLOYING" in text:
                return {"type": "deploying", "map_name": None, "text": text}
            if "RUN" in text and "COMPLETE" not in text and "RUN TIME" not in text and "RUNNER" not in text:
                return {"type": "run", "map_name": None, "text": text}
            if "READY UP" in text or "READYUP" in text or "READY_UP" in text:
                return {"type": "ready_up", "map_name": None, "text": text}
            if "SELECT ZONE" in text or "SELECT_ZONE" in text or "SELECTZONE" in text:
                return {"type": "select_zone", "map_name": None, "text": text}
            if ("PREPARE" in text or "PREPAAE" in text or "PREPAQE" in text or "PREPAPE" in text) \
                    and "PREPARED" not in text:
                return {"type": "prepare", "map_name": None, "text": text}
            if "SEARCHING" in text:
                return {"type": "searching", "map_name": None, "text": text}

        return None

    except Exception as e:
        print(f"[ocr] Error: {e}")
        return None

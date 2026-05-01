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

# Minimum crop width before OCR — ensures text is large enough to read reliably.
# At 1080p the lobby crop is ~650px wide; winocr struggles below ~800px.
_MIN_OCR_WIDTH = 800


def _ocr_pil(img: Image.Image, label: str = "") -> str:
    """Run Windows OCR on a PIL image. Returns uppercase text. Safe from any thread."""
    if not _WINOCR_AVAILABLE:
        return ""
    try:
        # Upscale small crops so text is large enough for Windows OCR
        w, h = img.size
        if w < _MIN_OCR_WIDTH:
            scale = _MIN_OCR_WIDTH / w
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
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


def scan_regions_for_mode(scan_mode: str) -> list[tuple[str, tuple]]:
    """Return the exact OCR regions used by a scan mode, in priority order."""
    if scan_mode == "deploy":
        return [("DEPLOY", DEPLOY_REGION)]
    if scan_mode == "postgame":
        return [("POSTGAME", DEPLOY_REGION)]
    if scan_mode == "endgame":
        return [("ENDGAME", ENDGAME_REGION), ("ENDGAME_CENTER", DEPLOY_REGION)]
    return [("LOBBY", LOBBY_REGION)]


def _classify_text(text: str, scan_mode: str, label: str) -> dict | None:
    if not text:
        return None

    if scan_mode == "deploy":
        for map_name in MAP_NAMES:
            if map_name in text:
                is_ranked = "RANKED" in text or "RANK" in text
                return {"type": "deploy", "map_name": map_name,
                        "is_ranked": is_ranked, "text": text}
        return None

    if scan_mode == "postgame":
        if "EXFILTRAT" in text:
            return {"type": "exfiltrated", "map_name": None, "text": text}
        if "ELIMINATED" in text or "ELIMINAT" in text:
            return {"type": "eliminated", "map_name": None, "text": text}
        return None

    if scan_mode == "endgame":
        if label == "ENDGAME":
            if "RUN" in text and "COMPLETE" in text:
                return {"type": "endgame", "map_name": None, "text": text}
            return None

        # RUN_COMPLETE banner is brief (~2s) and can be missed by the 2s mss interval.
        # Fall back to checking the center region for ELIMINATED/EXFILTRATED directly.
        if "EXFILTRAT" in text:
            return {"type": "exfiltrated", "map_name": None, "text": text}
        if "ELIMINATED" in text or "ELIMINAT" in text:
            return {"type": "eliminated", "map_name": None, "text": text}
        return None

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


def detect_game_state_from_crop(crop: Image.Image, scan_mode: str, label: str) -> dict | None:
    """Classify one already-cropped OCR region."""
    try:
        text = _ocr_pil(crop, label)
        return _classify_text(text, scan_mode, label)
    except Exception as e:
        print(f"[ocr] Error ({label}): {e}")
        return None


def detect_game_state(frame: "Image.Image | bytes", scan_mode: str = "lobby") -> dict | None:
    """Scan ONE OCR region based on current state machine mode.

    Accepts either a PIL.Image (preferred — skips decode) or raw JPEG bytes.

    scan_mode: 'lobby' | 'deploy' | 'endgame' | 'postgame'

    Returns a detection dict or None.
    """
    try:
        img = frame if isinstance(frame, Image.Image) else Image.open(io.BytesIO(frame))

        for label, region in scan_regions_for_mode(scan_mode):
            result = detect_game_state_from_crop(_crop_region(img, region), scan_mode, label)
            if result:
                return result

        return None

    except Exception as e:
        print(f"[ocr] Error: {e}")
        return None

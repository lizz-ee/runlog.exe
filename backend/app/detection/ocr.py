"""
OCR detection for Marathon game state.

Three scan regions:
  - OCR.DEPLOY (center)  — map name on deployment loading screen → START recording
  - OCR.ENDGAME (upper)  — //RUN_COMPLETE banner → log timestamp for stats extraction
  - OCR.LOBBY (bottom)   — PREPARE/READY_UP buttons → STOP recording / capture loadout

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
        _reader = easyocr.Reader(['en'], gpu=False)  # CPU mode — GPU is busy rendering the game
        print(f"[ocr] Loaded in {time.time()-t0:.1f}s (CPU mode)")
    return _reader


# -- Scan regions (percentage of screen dimensions) --------------------

# OCR.DEPLOY — center screen, deployment loading screen (map name + coordinates)
DEPLOY_REGION = (0.35, 0.38, 0.65, 0.65)

# OCR.ENDGAME — upper center, //RUN_COMPLETE banner
ENDGAME_REGION = (0.28, 0.135, 0.72, 0.275)

# OCR.LOBBY — bottom center, PREPARE/READY_UP buttons
LOBBY_REGION = (0.33, 0.72, 0.67, 0.89)

# Known map names for deployment detection
MAP_NAMES = ['PERIMETER', 'OUTPOST', 'DIRE MARSH', 'CRYO ARCHIVE']


_debug_count = 0

def _ocr_region(img, region, reader, contrast=2.0, label=""):
    """OCR a region of the image. Returns uppercase joined text."""
    global _debug_count
    w, h = img.size
    x1, y1, x2, y2 = region
    crop = img.crop((int(w * x1), int(h * y1), int(w * x2), int(h * y2)))
    if contrast != 1.0:
        crop = ImageEnhance.Contrast(crop).enhance(contrast)
    arr = np.array(crop)
    results = reader.readtext(arr)
    # Debug: log all raw results for first 5 frames
    if _debug_count < 15:
        all_texts = [(r[1], round(r[2], 3)) for r in results]
        if all_texts:
            print(f"[ocr-debug] {label} img={w}x{h} crop={crop.size[0]}x{crop.size[1]} raw={all_texts}")
        else:
            print(f"[ocr-debug] {label} img={w}x{h} crop={crop.size[0]}x{crop.size[1]} -> NO TEXT FOUND")
    texts = [r[1] for r in results if r[2] > 0.4]
    return ' '.join(texts).upper().strip()


def detect_game_state(jpeg_bytes: bytes, scan_mode: str = 'lobby') -> dict | None:
    """Scan ONE OCR region based on current state machine mode.

    scan_mode: 'lobby' | 'deploy' | 'endgame' | 'postgame'
    """
    try:
        img = Image.open(io.BytesIO(jpeg_bytes))
        reader = get_reader()

        if scan_mode == 'deploy':
            deploy_text = _ocr_region(img, DEPLOY_REGION, reader, label="DEPLOY")
            if deploy_text:
                for map_name in MAP_NAMES:
                    if map_name in deploy_text:
                        print(f"[ocr] DEPLOY: \"{deploy_text}\" -> {map_name}")
                        return {'type': 'deploy', 'map_name': map_name, 'text': deploy_text}
            return None

        if scan_mode == 'endgame':
            endgame_text = _ocr_region(img, ENDGAME_REGION, reader, label="ENDGAME")
            if endgame_text and ('RUN' in endgame_text and 'COMPLETE' in endgame_text):
                print(f"[ocr] ENDGAME: \"{endgame_text}\"")
                return {'type': 'endgame', 'map_name': None, 'text': endgame_text}
            return None

        # 'lobby' or 'postgame' — scan LOBBY region
        lobby_text = _ocr_region(img, LOBBY_REGION, reader, label="LOBBY")
        if lobby_text:
            # Post-game states
            if 'EXFILTRAT' in lobby_text:
                print(f"[ocr] LOBBY: \"{lobby_text}\" -> EXFILTRATED")
                return {'type': 'exfiltrated', 'map_name': None, 'text': lobby_text}
            if 'ELIMINATED' in lobby_text or 'ELIMINAT' in lobby_text:
                print(f"[ocr] LOBBY: \"{lobby_text}\" -> ELIMINATED")
                return {'type': 'eliminated', 'map_name': None, 'text': lobby_text}
            # Pre-deploy states
            if 'DEPLOYING' in lobby_text:
                print(f"[ocr] LOBBY: \"{lobby_text}\" -> DEPLOYING")
                return {'type': 'deploying', 'map_name': None, 'text': lobby_text}
            if 'RUN' in lobby_text and 'COMPLETE' not in lobby_text and 'RUN TIME' not in lobby_text and 'RUNNER' not in lobby_text:
                print(f"[ocr] LOBBY: \"{lobby_text}\" -> RUN")
                return {'type': 'run', 'map_name': None, 'text': lobby_text}
            if 'READY UP' in lobby_text or 'READYUP' in lobby_text or 'READY_UP' in lobby_text:
                print(f"[ocr] LOBBY: \"{lobby_text}\" -> READY_UP")
                return {'type': 'ready_up', 'map_name': None, 'text': lobby_text}
            # Menu states
            if 'SELECT ZONE' in lobby_text or 'SELECT_ZONE' in lobby_text or 'SELECTZONE' in lobby_text:
                print(f"[ocr] LOBBY: \"{lobby_text}\" -> SELECT_ZONE")
                return {'type': 'select_zone', 'map_name': None, 'text': lobby_text}
            if ('PREPARE' in lobby_text or 'PREPAAE' in lobby_text or 'PREPAQE' in lobby_text or 'PREPAPE' in lobby_text) and 'PREPARED' not in lobby_text:
                print(f"[ocr] LOBBY: \"{lobby_text}\" -> PREPARE")
                return {'type': 'prepare', 'map_name': None, 'text': lobby_text}
            if 'SEARCHING' in lobby_text:
                print(f"[ocr] LOBBY: \"{lobby_text}\" -> SEARCHING")
                return {'type': 'searching', 'map_name': None, 'text': lobby_text}

        return None
    except Exception as e:
        print(f"[ocr] Error: {e}")
        return None

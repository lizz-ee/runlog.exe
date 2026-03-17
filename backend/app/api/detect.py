"""
Game state detection endpoint.

Two-tier approach:
1. Fast local check: color analysis for EXFILTRATED/ELIMINATED banners + screen change detection
2. Claude Vision: full screen read for everything else (ready_up, lobby, results, etc.)
"""

from fastapi import APIRouter, UploadFile, File, Form
from typing import Optional
import numpy as np

from ..detection.templates import bytes_to_cv2, analyze_color
from ..detection.ocr import detect_game_state as ocr_detect

router = APIRouter()

# Store last frame hash to detect screen changes
_last_frame_hash = None


def _compute_frame_hash(image: np.ndarray) -> str:
    """Coarse perceptual hash — detect major screen transitions, not gameplay movement.
    Samples very few pixels and quantizes colors so minor changes don't trigger."""
    h, w = image.shape[:2]
    # Sample a 4x4 grid of the image
    small = image[::h//4, ::w//4]
    # Quantize to reduce sensitivity (divide by 32 so small color shifts are ignored)
    quantized = (small // 32).tobytes()
    return hash(quantized)


def _check_banner_colors(image: np.ndarray) -> dict:
    """Detect EXFILTRATED/ELIMINATED banners via color analysis.

    The banners appear at y=55-66% of screen. To avoid false positives
    from red/green game objects, we also check that the area ABOVE the
    banner (y=45-55%) is dark (the character model on dark background).
    """
    h, w = image.shape[:2]

    # Banner region (y=55-66%, center)
    center = image[int(h*0.55):int(h*0.66), int(w*0.28):int(w*0.72)]
    center_strip = center[int(center.shape[0]*0.2):int(center.shape[0]*0.8),
                          int(center.shape[1]*0.2):int(center.shape[1]*0.8)]
    colors = analyze_color(center_strip)

    # Area above banner should be dark (character on dark bg, not gameplay)
    above = image[int(h*0.45):int(h*0.55), int(w*0.35):int(w*0.65)]
    above_colors = analyze_color(above)
    is_dark_above = above_colors["avg_r"] < 100 and above_colors["avg_g"] < 100 and above_colors["avg_b"] < 100

    # EXFILTRATED: bright green/yellow banner + dark above
    if colors["avg_g"] > 100 and colors["avg_g"] > colors["avg_b"] * 2 and is_dark_above:
        return {"detected": "exfiltrated", "confidence": min(1.0, colors["avg_g"] / 200), "method": "color"}

    # ELIMINATED: red banner + dark above
    if colors["avg_r"] > 80 and colors["avg_r"] > colors["avg_g"] * 1.5 and is_dark_above:
        return {"detected": "eliminated", "confidence": min(1.0, colors["avg_r"] / 200), "method": "color"}

    return {"detected": "none", "confidence": 0}


def _check_loading_screen(image: np.ndarray) -> dict:
    """Detect the Marathon loading screen: solid dark blue bg with green text center."""
    h, w = image.shape[:2]

    corners = [
        image[10:50, 10:50],
        image[10:50, w-50:w-10],
        image[h-50:h-10, 10:50],
    ]

    for corner in corners:
        colors = analyze_color(corner)
        if not (colors["avg_b"] > 80 and colors["avg_r"] < 60 and colors["avg_g"] < 40):
            return {"detected": "none", "confidence": 0}

    center = image[h//2-50:h//2+50, w//2-100:w//2+100]
    center_colors = analyze_color(center)
    if center_colors["avg_g"] > 80:
        return {"detected": "loading_screen", "confidence": min(1.0, center_colors["avg_g"] / 200), "method": "color"}

    return {"detected": "none", "confidence": 0}


@router.post("/check")
async def check_screen(
    file: UploadFile = File(...),
    region: Optional[str] = Form(None),
):
    """
    Fast local detection check. Only detects high-confidence states locally:
    - EXFILTRATED / ELIMINATED banners (color analysis)
    - Loading screen (color analysis)
    - Screen changed (frame hash comparison)

    Everything else should use /check-full with Claude Vision.
    """
    global _last_frame_hash

    contents = await file.read()
    image = bytes_to_cv2(contents)
    if image is None:
        return {"detected": "error", "confidence": 0}

    # ALWAYS check banners first — they're the most important detection (<5ms)
    result = _check_banner_colors(image)
    if result["detected"] != "none" and result.get("confidence", 0) >= 0.6:
        return result

    # Check loading screen
    result = _check_loading_screen(image)
    if result["detected"] != "none":
        return result

    # Check if screen has changed for OCR trigger
    frame_hash = _compute_frame_hash(image)
    screen_changed = frame_hash != _last_frame_hash
    _last_frame_hash = frame_hash

    if not screen_changed:
        return {"detected": "no_change", "confidence": 1.0}

    # Screen changed but not a banner/loading — trigger OCR
    return {"detected": "unknown_change", "confidence": 0, "screen_changed": True}


@router.post("/check-full")
async def check_screen_full(
    file: UploadFile = File(...),
):
    """
    Full screen analysis via local OCR. Reads specific screen regions
    to identify game state and extract all visible data.
    Fast (~1-2 seconds), no API calls, works offline.
    """
    contents = await file.read()
    result = ocr_detect(contents)
    return result

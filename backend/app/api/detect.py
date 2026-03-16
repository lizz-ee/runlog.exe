"""
Fast game state detection endpoint.

Receives small screen region captures from Electron and returns
what game state is detected. Designed to respond in <10ms.
"""

from fastapi import APIRouter, UploadFile, File, Form
from typing import Optional

from ..detection.templates import get_store, bytes_to_cv2, analyze_color, detect_loading_screen, detect_banner

router = APIRouter()


@router.post("/check")
async def check_screen(
    file: UploadFile = File(...),
    region: Optional[str] = Form(None),
):
    """
    Check a screen region for game state indicators.

    Regions:
      - center_banner: check for EXFILTRATED/ELIMINATED
      - bottom_center: check for READY UP button
      - full: check for loading screen + all indicators
      - top_right: check for STATS/LOADOUT tab indicators

    Returns detected state and confidence.
    """
    contents = await file.read()
    image = bytes_to_cv2(contents)

    if image is None:
        return {"detected": "error", "confidence": 0, "detail": "Invalid image"}

    store = get_store()
    region = region or "full"

    # Route detection based on region hint
    if region == "center_banner":
        return _check_banner(image, store)

    elif region == "bottom_center":
        return _check_ready_up(image, store)

    elif region == "top_right":
        return _check_tabs(image, store)

    elif region == "full":
        # Check everything in priority order

        # 1. Loading screen (very distinctive)
        is_loading, conf = detect_loading_screen(image)
        if is_loading:
            return {"detected": "loading_screen", "confidence": conf}

        # 2. Banner detection (center region — exfiltrated/eliminated)
        h, w = image.shape[:2]
        center = image[int(h*0.55):int(h*0.66), int(w*0.28):int(w*0.72)]
        result = _check_banner(center, store)
        if result["detected"] != "none":
            return result

        # 3. Ready up button (bottom center)
        bottom = image[int(h*0.78):int(h*0.90), int(w*0.30):int(w*0.70)]
        result = _check_ready_up(bottom, store)
        if result["detected"] != "none":
            return result

        # 4. Tab indicators (results screen)
        top_right = image[0:int(h*0.05), int(w*0.70):w]
        result = _check_tabs(top_right, store)
        if result["detected"] != "none":
            return result

        return {"detected": "none", "confidence": 0}

    return {"detected": "none", "confidence": 0}


def _check_banner(image, store):
    """Check for EXFILTRATED or ELIMINATED banner."""
    # Fast color check first
    banner_type, color_conf = detect_banner(image)

    if banner_type != "none":
        # Confirm with template match
        template_name = f"{banner_type}_banner"
        matched, tpl_conf = store.match(image, template_name, threshold=0.5)
        if matched:
            return {"detected": banner_type, "confidence": tpl_conf, "method": "template+color"}
        # Color alone was strong enough
        if color_conf > 0.6:
            return {"detected": banner_type, "confidence": color_conf, "method": "color"}

    return {"detected": "none", "confidence": 0}


def _check_ready_up(image, store):
    """Check for READY UP button."""
    matched, conf = store.match(image, "ready_up_button", threshold=0.6)
    if matched:
        return {"detected": "ready_up", "confidence": conf}

    # Fallback: color check for bright green/yellow bar
    colors = analyze_color(image)
    if colors["avg_g"] > 180 and colors["avg_r"] > 140 and colors["avg_b"] < 50:
        return {"detected": "ready_up", "confidence": 0.7, "method": "color"}

    return {"detected": "none", "confidence": 0}


def _check_tabs(image, store):
    """Check for active STATS or LOADOUT tab."""
    for tab_name in ["tab_stats_active", "tab_loadout_active"]:
        matched, conf = store.match(image, tab_name, threshold=0.6)
        if matched:
            detected = "stats_tab" if "stats" in tab_name else "loadout_tab"
            return {"detected": detected, "confidence": conf}

    return {"detected": "none", "confidence": 0}

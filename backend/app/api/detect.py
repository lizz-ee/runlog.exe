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

router = APIRouter()

# Store last frame hash to detect screen changes
_last_frame_hash = None


def _compute_frame_hash(image: np.ndarray) -> str:
    """Quick perceptual hash — resize to tiny image and hash the pixels."""
    small = image[::32, ::32]  # Sample every 32nd pixel
    return hash(small.tobytes())


def _check_banner_colors(image: np.ndarray) -> dict:
    """Fast color-based detection for EXFILTRATED/ELIMINATED banners.
    These are the most reliable local detections since nothing else
    in the game looks like a big green/red banner center-screen."""
    h, w = image.shape[:2]

    # Check center-screen region where banners appear (y=55-66%)
    center = image[int(h*0.55):int(h*0.66), int(w*0.28):int(w*0.72)]
    center_strip = center[int(center.shape[0]*0.2):int(center.shape[0]*0.8),
                          int(center.shape[1]*0.2):int(center.shape[1]*0.8)]
    colors = analyze_color(center_strip)

    # EXFILTRATED: bright green/yellow banner
    if colors["avg_g"] > 100 and colors["avg_g"] > colors["avg_b"] * 2:
        return {"detected": "exfiltrated", "confidence": min(1.0, colors["avg_g"] / 200), "method": "color"}

    # ELIMINATED: red banner
    if colors["avg_r"] > 80 and colors["avg_r"] > colors["avg_g"] * 1.5:
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

    # Check if screen has changed
    frame_hash = _compute_frame_hash(image)
    screen_changed = frame_hash != _last_frame_hash
    _last_frame_hash = frame_hash

    if not screen_changed:
        return {"detected": "no_change", "confidence": 1.0}

    # 1. Loading screen (very distinctive)
    result = _check_loading_screen(image)
    if result["detected"] != "none":
        return result

    # 2. Banner detection (exfiltrated / eliminated)
    result = _check_banner_colors(image)
    if result["detected"] != "none":
        return result

    # Screen changed but nothing detected locally — caller should use Claude Vision
    return {"detected": "unknown_change", "confidence": 0, "screen_changed": True}


@router.post("/check-full")
async def check_screen_full(
    file: UploadFile = File(...),
):
    """
    Full screen analysis via Claude Vision. Used when the fast check detects
    a screen change but can't identify the state locally.

    Returns the game state and all visible data.
    """
    contents = await file.read()

    from .screenshot import _call_claude, _extract_json
    import json

    prompt = """Analyze this Marathon (Bungie 2026) game screenshot and identify the current game state.

Return ONLY valid JSON with these fields:
{
  "game_state": "lobby" | "prepare" | "select_zone" | "ready_up" | "deploying" | "loading" | "gameplay" | "run_complete" | "exfiltrated" | "eliminated" | "stats_screen" | "progress_screen" | "loadout_screen" | "shell_select" | "other",
  "map_name": "string or null",
  "shell_name": "string or null (if character/shell is visible)",
  "crew": "solo" | "squad" | null,
  "crew_members": ["list of visible player names"] or null,
  "zone_name": "string or null (HUD zone name if visible)",
  "compass_bearing": "string or null (e.g. 'S 195')",
  "primary_weapon": "string or null",
  "secondary_weapon": "string or null",
  "survived": true | false | null,
  "combatant_eliminations": number or null,
  "runner_eliminations": number or null,
  "crew_revives": number or null,
  "inventory_value": number or null,
  "run_time": "string or null (e.g. '12:56')",
  "killed_by": "string or null (player name if death screen)",
  "killed_by_damage": number or null,
  "raw_text": "any other important text visible on screen"
}

Return ONLY the JSON object."""

    try:
        # Save temp file for Claude
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            f.write(contents)
            temp_path = f.name

        response_text = await _call_claude([temp_path], prompt)
        os.unlink(temp_path)

        parsed = _extract_json(response_text)
        return parsed
    except Exception as e:
        return {"game_state": "error", "error": str(e)}

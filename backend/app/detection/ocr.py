"""
Region-based OCR for Marathon game state detection.

Reads specific screen regions to identify game state and extract data.
Uses easyocr with GPU acceleration. Model loads once, stays in memory.

All regions are defined as percentages (0-1) of screen resolution,
so this works at any resolution.
"""

import time
import easyocr
import numpy as np
from PIL import Image
import io
import re

# Singleton OCR reader
_reader = None


def get_reader():
    global _reader
    if _reader is None:
        print("[ocr] Loading easyocr (GPU)...")
        t0 = time.time()
        _reader = easyocr.Reader(['en'], gpu=True)
        print(f"[ocr] Loaded in {time.time()-t0:.1f}s")
    return _reader


# ── Screen regions (percentage-based) ─────────────────────────────────

REGIONS = {
    # Bottom center — button text: READY UP, PREPARE, SELECT ZONE, DEPLOYING
    'button': (0.30, 0.82, 0.70, 0.92),

    # Banner area — EXFILTRATED / ELIMINATED text
    'banner': (0.28, 0.55, 0.72, 0.66),

    # Stats area — full results data
    'stats': (0.30, 0.58, 0.65, 0.92),

    # HUD zone name — top center during gameplay
    'zone': (0.35, 0.02, 0.65, 0.06),

    # HUD compass — bearing text
    'compass': (0.42, 0.02, 0.58, 0.05),

    # Map name — on ready-up screen
    'map_name': (0.25, 0.72, 0.50, 0.78),

    # Crew info — on ready-up screen
    'crew': (0.50, 0.72, 0.75, 0.78),

    # Death screen — killer info
    'death_killer': (0.70, 0.13, 1.0, 0.22),

    # Death screen — RUN_COMPLETE text
    'death_banner': (0.25, 0.15, 0.75, 0.30),

    # Timer — top left
    'timer': (0.01, 0.01, 0.08, 0.04),

    # Tab indicators — top right
    'tabs': (0.70, 0.005, 0.98, 0.03),
}


def crop_region(image: Image.Image, region_name: str) -> Image.Image:
    """Crop a named region from the image using percentage coordinates."""
    x1, y1, x2, y2 = REGIONS[region_name]
    w, h = image.size
    return image.crop((int(w*x1), int(h*y1), int(w*x2), int(h*y2)))


def read_region(image: Image.Image, region_name: str, min_confidence: float = 0.3) -> list[str]:
    """OCR a specific region and return text lines."""
    crop = crop_region(image, region_name)
    # Convert to numpy for easyocr
    img_array = np.array(crop)
    reader = get_reader()
    results = reader.readtext(img_array)
    return [r[1] for r in results if r[2] >= min_confidence]


def read_region_with_confidence(image: Image.Image, region_name: str) -> list[tuple[str, float]]:
    """OCR a region and return (text, confidence) tuples."""
    crop = crop_region(image, region_name)
    img_array = np.array(crop)
    reader = get_reader()
    results = reader.readtext(img_array)
    return [(r[1], r[2]) for r in results]


# ── Game state detection ──────────────────────────────────────────────

# Keywords that identify each game state
STATE_KEYWORDS = {
    'exfiltrated': ['EXFILTRATED'],
    'eliminated': ['ELIMINATED'],
    'run_complete': ['RUN_COMPLETE', 'RUN COMPLETE', 'NEURAL LINK SEVERED'],
    'ready_up': ['READY UP'],
    'deploying': ['DEPLOYING'],
    'prepare': ['PREPARE'],
    'select_zone': ['SELECT ZONE'],
    'stats_screen': ['Combatant Eliminations', 'Runner Eliminations', 'Inventory Value', 'Run Time'],
    'loadout_screen': ['LOADOUT REPORT', 'LOADOUT', 'Report Summary'],
    'progress_screen': ['PROGRESS REPORT', 'SEASON LEVEL', 'FACTION RANKS'],
}


def detect_game_state(image_bytes: bytes) -> dict:
    """
    Detect the current game state from a screenshot using OCR.
    Returns game state and any extracted data.

    Fast path: check banner and button regions first (~0.2s)
    Slow path: if unknown, check more regions (~1-2s)
    """
    img = Image.open(io.BytesIO(image_bytes))
    result = {'game_state': 'unknown', 'confidence': 0, 'data': {}}

    # Phase 1: Quick checks (~0.2s each)

    # Check banner for EXFILTRATED/ELIMINATED
    banner_text = read_region(img, 'banner', min_confidence=0.5)
    banner_joined = ' '.join(banner_text).upper()

    if 'EXFILTRATED' in banner_joined:
        result['game_state'] = 'exfiltrated'
        result['confidence'] = 1.0
        result['data']['survived'] = True
        # Also read stats since we're on the results screen
        _parse_stats(img, result)
        return result

    if 'ELIMINATED' in banner_joined:
        result['game_state'] = 'eliminated'
        result['confidence'] = 1.0
        result['data']['survived'] = False
        _parse_stats(img, result)
        return result

    # Check button text
    button_text = read_region(img, 'button', min_confidence=0.5)
    button_joined = ' '.join(button_text).upper()

    if 'READY UP' in button_joined:
        result['game_state'] = 'ready_up'
        result['confidence'] = 1.0
        _parse_ready_up(img, result)
        return result

    if 'DEPLOYING' in button_joined:
        result['game_state'] = 'deploying'
        result['confidence'] = 1.0
        _parse_ready_up(img, result)
        return result

    if 'PREPARE' in button_joined:
        result['game_state'] = 'prepare'
        result['confidence'] = 1.0
        return result

    if 'SELECT ZONE' in button_joined:
        result['game_state'] = 'select_zone'
        result['confidence'] = 1.0
        return result

    # Check death screen
    death_text = read_region(img, 'death_banner', min_confidence=0.3)
    death_joined = ' '.join(death_text).upper()

    if 'RUN_COMPLETE' in death_joined or 'RUN COMPLETE' in death_joined:
        result['game_state'] = 'run_complete'
        result['confidence'] = 1.0
        result['data']['survived'] = False
        _parse_death_screen(img, result)
        return result

    # Phase 2: Check for gameplay HUD
    timer_text = read_region(img, 'timer', min_confidence=0.5)
    if timer_text:
        # Check if it looks like a timer (XX:XX format)
        for t in timer_text:
            if re.match(r'\d{1,2}:\d{2}', t):
                result['game_state'] = 'gameplay'
                result['confidence'] = 0.8
                _parse_gameplay_hud(img, result)
                return result

    # Check for stats keywords in the stats region
    if 'COMBATANT' in banner_joined or 'RUNNER' in banner_joined:
        result['game_state'] = 'stats_screen'
        result['confidence'] = 0.9
        _parse_stats(img, result)
        return result

    # Check tabs for results screens
    tabs_text = read_region(img, 'tabs', min_confidence=0.3)
    tabs_joined = ' '.join(tabs_text).upper()
    if 'STATS' in tabs_joined or 'LOADOUT' in tabs_joined or 'PROGRESS' in tabs_joined:
        if 'LOADOUT' in tabs_joined:
            result['game_state'] = 'loadout_screen'
        elif 'PROGRESS' in tabs_joined:
            result['game_state'] = 'progress_screen'
        else:
            result['game_state'] = 'stats_screen'
        result['confidence'] = 0.7
        _parse_stats(img, result)
        return result

    return result


def _parse_stats(img: Image.Image, result: dict):
    """Parse the stats screen for run data."""
    text_lines = read_region(img, 'stats', min_confidence=0.3)
    text = ' '.join(text_lines)

    data = result['data']

    # Combatant Eliminations
    match = re.search(r'Combatant\s*Eliminations?\s*(\d+)', text, re.IGNORECASE)
    if match:
        data['combatant_eliminations'] = int(match.group(1))

    # Runner Eliminations
    match = re.search(r'Runner\s*Eliminations?\s*(\d+)', text, re.IGNORECASE)
    if match:
        data['runner_eliminations'] = int(match.group(1))

    # Crew Revives
    match = re.search(r'Crew\s*Revives?\s*(\d+)', text, re.IGNORECASE)
    if match:
        data['crew_revives'] = int(match.group(1))

    # Inventory Value
    match = re.search(r'Inventory\s*Value\s*(-?[\d,]+)', text, re.IGNORECASE)
    if match:
        data['inventory_value'] = int(match.group(1).replace(',', ''))

    # Run Time
    match = re.search(r'Run\s*Time\s*(\d+:\d+)', text, re.IGNORECASE)
    if match:
        time_str = match.group(1)
        parts = time_str.split(':')
        data['run_time'] = time_str
        data['duration_seconds'] = int(parts[0]) * 60 + int(parts[1])


def _parse_ready_up(img: Image.Image, result: dict):
    """Parse the ready-up screen for map and crew info."""
    data = result['data']

    map_text = read_region(img, 'map_name', min_confidence=0.5)
    if map_text:
        map_name = map_text[0].strip().upper()
        # Normalize map names
        for known in ['PERIMETER', 'DIRE MARSH', 'OUTPOST', 'CRYO ARCHIVE']:
            if known in map_name or map_name in known:
                data['map_name'] = known.title()
                break

    crew_text = read_region(img, 'crew', min_confidence=0.5)
    crew_joined = ' '.join(crew_text).upper()
    if 'SOLO' in crew_joined:
        data['crew'] = 'solo'
    elif 'CREW' in crew_joined:
        data['crew'] = 'squad'


def _parse_gameplay_hud(img: Image.Image, result: dict):
    """Parse the gameplay HUD for zone name and compass bearing."""
    data = result['data']

    zone_text = read_region(img, 'zone', min_confidence=0.3)
    if zone_text:
        # Zone name is usually the most prominent text
        data['zone_name'] = zone_text[0].strip()

    compass_text = read_region(img, 'compass', min_confidence=0.3)
    for t in compass_text:
        # Look for compass pattern like "S 195", "NE 039"
        match = re.match(r'([NESW]{1,2})\s*(\d{3})', t)
        if match:
            data['compass_bearing'] = f"{match.group(1)} {match.group(2)}"
            break


def _parse_death_screen(img: Image.Image, result: dict):
    """Parse the death screen for killer info."""
    data = result['data']

    killer_text = read_region(img, 'death_killer', min_confidence=0.3)
    if killer_text:
        # First line is usually the killer's name
        data['killed_by'] = killer_text[0].strip()

    # Look for damage numbers
    for t in killer_text:
        match = re.search(r'(\d+)\s*$', t)
        if match:
            data['killed_by_damage'] = int(match.group(1))
            break

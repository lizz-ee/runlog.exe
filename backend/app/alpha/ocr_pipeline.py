"""
Alpha OCR Pipeline — Extract game stats from screenshots using Windows OCR.

Replaces Claude API calls for text extraction. Uses winocr (Windows.Media.Ocr)
at known crop positions to read stat values, gamertags, coordinates, and more.

Usage:
    from backend.app.alpha.ocr_pipeline import AlphaOCR
    ocr = AlphaOCR()
    coords = ocr.read_spawn_coordinates(deploy_image)
    stats = ocr.read_stats_tab(stats_image)
"""

import asyncio
import logging
import os
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Try to import winocr, fall back gracefully
try:
    from winocr import recognize_pil
    WINOCR_AVAILABLE = True
except ImportError:
    WINOCR_AVAILABLE = False
    logger.warning("winocr not available — OCR will not function")

# EasyOCR as fallback for single-digit values
try:
    import easyocr
    _easyocr_reader = None

    def _get_easyocr():
        global _easyocr_reader
        if _easyocr_reader is None:
            _easyocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        return _easyocr_reader

    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    logger.warning("easyocr not available — single-digit detection will be limited")

# Tesseract for single-digit and full-row stat reading
TESSERACT_AVAILABLE = False
try:
    import pytesseract
    # Find tesseract binary
    for tess_path in [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Tesseract-OCR", "tesseract.exe"),
    ]:
        if Path(tess_path).exists():
            pytesseract.pytesseract.tesseract_cmd = tess_path
            TESSERACT_AVAILABLE = True
            logger.info(f"Tesseract found at {tess_path}")
            break
    if not TESSERACT_AVAILABLE:
        # Try PATH
        import shutil
        if shutil.which("tesseract"):
            TESSERACT_AVAILABLE = True
            logger.info("Tesseract found in PATH")
except ImportError:
    pass

if not TESSERACT_AVAILABLE:
    logger.warning("Tesseract not available — install for best stat detection")


# --- Crop Regions (percentage of full frame) ---
# These match the positions observed in actual Marathon screenshots.

REGIONS = {
    # Deploy loading screen
    "deploy_map_name":   (0.30, 0.42, 0.70, 0.55),   # Map name text
    "deploy_coords":     (0.38, 0.56, 0.62, 0.66),   # Coordinate numbers (green text below map)
    "deploy_full_text":  (0.30, 0.35, 0.70, 0.70),   # Everything on deploy screen

    # Readyup screen
    "readyup_gamertag":  (0.38, 0.02, 0.62, 0.06),   # Gamertag above shell head
    "readyup_loadout":   (0.42, 0.37, 0.55, 0.42),   # Loadout value (e.g. "$1.3K")
    "readyup_map_crew":  (0.30, 0.82, 0.70, 0.88),   # Map name + Crew size bar

    # Stats tab — CALIBRATED from actual screenshots (2026-03-28)
    # Best approach: OCR the full center column block, then parse structured text.
    # The block contains: banner + 4 stat rows + run time, all in one clean region.
    "stats_center_block": (0.33, 0.53, 0.67, 0.87),  # Full center column: banner + all stats + run time
    "stats_run_time":     (0.38, 0.83, 0.62, 0.88),  # Run Time row (also inside center_block)

    # Individual columns for trio — OCR full block per column
    "stats_left_block":   (0.03, 0.53, 0.32, 0.87),  # Left squad member stats
    "stats_right_block":  (0.68, 0.53, 0.97, 0.87),  # Right squad member stats

    # Gamertags (slightly below top bar)
    "gamertag_center":    (0.38, 0.05, 0.62, 0.10),   # Center player gamertag
    "gamertag_left":      (0.03, 0.05, 0.30, 0.10),   # Left squad gamertag
    "gamertag_right":     (0.70, 0.05, 0.97, 0.10),   # Right squad gamertag

    # Top bar (level pill + vault info)
    "top_bar":            (0.01, 0.005, 0.30, 0.035),  # Level + vault pills
    "top_level":          (0.01, 0.005, 0.08, 0.035),  # Level number in green circle
    "top_vault":          (0.12, 0.005, 0.30, 0.035),  # Vault/currency display

    # LOADOUT tab regions
    "loadout_weapon_1":   (0.50, 0.06, 0.80, 0.12),   # Primary weapon name
    "loadout_weapon_2":   (0.50, 0.25, 0.80, 0.31),   # Secondary weapon name
    "loadout_wallet":     (0.05, 0.92, 0.35, 0.97),   # Wallet balance at bottom

    # Death screen damage widget (right side)
    "damage_widget":      (0.74, 0.17, 0.97, 0.75),   # Full damage widget
}


def _crop_pil(img: Image.Image, region: tuple) -> Image.Image:
    """Crop a PIL image using percentage-based coordinates."""
    w, h = img.size
    return img.crop((
        int(w * region[0]),
        int(h * region[1]),
        int(w * region[2]),
        int(h * region[3]),
    ))


def _preprocess_for_ocr(img: Image.Image, invert_if_dark: bool = True,
                         min_width: int = 800) -> Image.Image:
    """Preprocess image for optimal OCR accuracy."""
    arr = np.array(img)

    # Convert to grayscale
    if len(arr.shape) == 3:
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    else:
        gray = arr

    # Invert if predominantly dark (light text on dark bg)
    if invert_if_dark and gray.mean() < 128:
        gray = cv2.bitwise_not(gray)

    # Upscale small images
    h, w = gray.shape
    if w < min_width:
        scale = min_width / w
        gray = cv2.resize(gray, (int(w * scale), int(h * scale)),
                          interpolation=cv2.INTER_LANCZOS4)

    # Add white border for edge text
    gray = cv2.copyMakeBorder(gray, 15, 15, 15, 15,
                               cv2.BORDER_CONSTANT, value=255)

    return Image.fromarray(gray)


async def _ocr_async(img: Image.Image, lang: str = "en") -> str:
    """Run winocr on a PIL image, return recognized text."""
    if not WINOCR_AVAILABLE:
        return ""
    result = await recognize_pil(img, lang=lang)
    return result.text.strip() if result and result.text else ""


def _ocr_sync(img: Image.Image, lang: str = "en") -> str:
    """Synchronous wrapper for winocr."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If already in async context, create new loop in thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(lambda: asyncio.run(_ocr_async(img, lang))).result()
        else:
            return loop.run_until_complete(_ocr_async(img, lang))
    except RuntimeError:
        return asyncio.run(_ocr_async(img, lang))


class AlphaOCR:
    """OCR engine for Marathon game screenshots."""

    def __init__(self):
        if not WINOCR_AVAILABLE:
            logger.error("winocr is not installed. Run: pip install winocr")

    # =========================================================================
    # Parsers (text -> structured data)
    # =========================================================================

    @staticmethod
    def _fix_slashed_zero(text: str) -> str:
        """Fix Marathon's slashed-zero font: Tesseract reads 0 as Q, O, or A."""
        # Only fix these characters when they appear where a digit is expected
        # (at the end of a stat line, after a label)
        # Replace Q/O/A with 0 when surrounded by digits or at end of number position
        result = text
        # "Q" at end of line (common: "Runner ELimtnattons Q" -> ...0)
        result = re.sub(r'\bQ\b', '0', result)
        # "A" at end of line when it looks like a number position
        result = re.sub(r'\bA$', '0', result)
        # "I" that should be "1" (only in number context, not in words)
        # Don't replace I in "Inventory" etc - only isolated I
        result = re.sub(r'(?<=\s)I(?=\s*$)', '1', result)
        return result

    @staticmethod
    def _parse_number(text: str) -> int | None:
        """Parse a number from OCR text. Handles commas, K suffix, negatives."""
        text = text.strip().replace(" ", "").replace("\n", "")

        # Handle "1.5K" -> 1500
        k_match = re.search(r'(-?[\d.]+)\s*[kK]', text)
        if k_match:
            return int(float(k_match.group(1)) * 1000)

        # Handle comma-separated numbers: "1,248" -> 1248
        text = text.replace(",", "")

        # Handle dollar sign
        text = text.replace("$", "").replace("¢", "")

        # Extract first number (int or float)
        num_match = re.search(r'-?[\d]+\.?\d*', text)
        if num_match:
            val = float(num_match.group())
            return int(val)

        return None

    @staticmethod
    def _parse_duration(text: str) -> int | None:
        """Parse MM:SS or M:SS format to total seconds."""
        text = text.strip().replace(" ", "")
        # Match MM:SS or M:SS (possibly with trailing icon/text)
        match = re.search(r'(\d{1,2}):(\d{2})', text)
        if match:
            minutes = int(match.group(1))
            seconds = int(match.group(2))
            return minutes * 60 + seconds
        return None

    @staticmethod
    def _parse_coordinates(text: str) -> list | None:
        """Parse spawn coordinates from deploy screen text."""
        # winocr often inserts spaces around dots: "251 . 992844" -> "251.992844"
        # Also handles "251 .992844" and "251. 992844"
        cleaned = re.sub(r'(\d)\s*\.\s*(\d)', r'\1.\2', text)

        # Coordinates appear as two decimal numbers
        # e.g., "251.992844 -357.184479" or on separate lines
        numbers = re.findall(r'-?\d+\.\d+', cleaned)
        if len(numbers) >= 2:
            return [float(numbers[0]), float(numbers[1])]

        # Fallback: try to find numbers even with partial parsing
        # Sometimes the negative sign is separated: "- 357.184479"
        cleaned2 = re.sub(r'-\s+(\d)', r'-\1', cleaned)
        numbers2 = re.findall(r'-?\d+\.\d+', cleaned2)
        if len(numbers2) >= 2:
            return [float(numbers2[0]), float(numbers2[1])]

        return None

    @staticmethod
    def _parse_map_name(text: str) -> str | None:
        """Parse map name from OCR text."""
        text_upper = text.upper().replace("\n", " ")
        for name in ["PERIMETER", "OUTPOST", "DIRE MARSH", "CRYO ARCHIVE"]:
            if name in text_upper:
                # Return proper case
                return name.title()
        # Fuzzy: check partial matches
        for name, display in [("PERIM", "Perimeter"), ("OUTPO", "Outpost"),
                               ("DIRE", "Dire Marsh"), ("MARSH", "Dire Marsh"),
                               ("CRYO", "Cryo Archive")]:
            if name in text_upper:
                return display
        return None

    @staticmethod
    def _parse_gamertag(text: str) -> str | None:
        """Parse a gamertag (may include #number suffix)."""
        text = text.strip()
        # Gamertags can have format "name#1234" or just "name"
        # Remove leading icons/symbols
        text = re.sub(r'^[^\w]+', '', text)
        # Remove trailing whitespace/symbols but keep #number
        text = re.sub(r'\s+$', '', text)
        if len(text) >= 2:
            return text
        return None

    # =========================================================================
    # High-Level OCR Functions
    # =========================================================================

    def read_spawn_coordinates(self, img: Image.Image) -> dict:
        """Read spawn coordinates from a deploy loading screen (blue or black).

        Returns dict with "spawn_coordinates" and "_confidence".
        """
        result = {"spawn_coordinates": None, "_confidence": {}}

        # Try the wider deploy text region first (has map name + subtitle + coords)
        crop_wide = _crop_pil(img, REGIONS["deploy_full_text"])
        wide_4x = crop_wide.resize(
            (crop_wide.size[0] * 4, crop_wide.size[1] * 4), Image.LANCZOS)
        text_wide = _ocr_sync(wide_4x)
        logger.debug(f"Deploy text (4x): '{text_wide}'")

        coords = self._parse_coordinates(text_wide)
        if coords:
            result["spawn_coordinates"] = coords
            result["_confidence"]["spawn_coordinates"] = 0.85
            return result

        # Fallback: tighter coordinate-only region
        crop_tight = _crop_pil(img, REGIONS["deploy_coords"])
        tight_4x = crop_tight.resize(
            (crop_tight.size[0] * 4, crop_tight.size[1] * 4), Image.LANCZOS)
        text_tight = _ocr_sync(tight_4x)
        logger.debug(f"Deploy coords tight (4x): '{text_tight}'")

        coords = self._parse_coordinates(text_tight)
        if coords:
            result["spawn_coordinates"] = coords
            result["_confidence"]["spawn_coordinates"] = 0.75
            return result

        # Final fallback: preprocessed (inverted for dark backgrounds)
        processed = _preprocess_for_ocr(crop_wide)
        text_processed = _ocr_sync(processed)
        coords = self._parse_coordinates(text_processed)
        if coords:
            result["spawn_coordinates"] = coords
            result["_confidence"]["spawn_coordinates"] = 0.5
        return result

    def read_map_name(self, img: Image.Image) -> dict:
        """Read map name from a deploy loading screen.

        Returns dict with "map_name" and "_confidence".
        """
        crop = _crop_pil(img, REGIONS["deploy_map_name"])
        processed = _preprocess_for_ocr(crop)
        text = _ocr_sync(processed)
        logger.debug(f"Map OCR raw: '{text}'")
        name = self._parse_map_name(text)
        conf = 0.85 if name else 0.0
        return {"map_name": name, "_confidence": {"map_name": conf}}

    @staticmethod
    def _read_value_by_pixels(img: Image.Image, region: tuple,
                               threshold: int = 100) -> int | None:
        """
        Read a stat value using pixel analysis when OCR fails on single digits.

        For single-digit values (0-9), winocr can't detect them reliably.
        This method:
        1. Binarizes the value region
        2. Counts white pixels (text pixels)
        3. If very few white pixels -> value is 0
        4. If some white pixels but OCR failed -> returns None (unknown)
        """
        crop = _crop_pil(img, region)
        arr = np.array(crop.convert("L"))
        _, binary = cv2.threshold(arr, threshold, 255, cv2.THRESH_BINARY)

        total_pixels = binary.size
        white_pixels = int((binary > 128).sum())
        white_ratio = white_pixels / total_pixels if total_pixels > 0 else 0

        # Very few white pixels = no text = value is 0
        # Typical: single "0" digit has ~1-3% white pixels
        # Empty (actual 0 value) has < 0.5% white pixels
        # Single digit like "7" has ~2-5% white pixels
        if white_ratio < 0.005:
            return 0
        return None  # Has pixels but we can't read the number

    def read_stats_tab(self, img: Image.Image, crew_size: str = None) -> dict:
        """
        Read all stats from a post-match STATS tab screenshot.

        Hybrid strategy:
        1. OCR the full center column block for text (labels, multi-digit values)
        2. Use per-row OCR for individual stat lines (label + value together)
        3. Fall back to pixel analysis for single-digit values winocr can't detect

        Returns dict with: survived, combatant_eliminations, runner_eliminations,
        crew_revives, loot_value_total (inventory value), duration_seconds,
        player_gamertag, squad_members, kills.

        Also includes "_confidence" dict mapping field names to 0.0-1.0 scores.
        Confidence tiers: tesseract=0.9, easyocr=0.7, pixel=0.4, color_fallback=0.6
        """
        result = {
            "survived": None,
            "combatant_eliminations": None,
            "runner_eliminations": None,
            "crew_revives": None,
            "loot_value_total": None,
            "duration_seconds": None,
            "player_gamertag": None,
            "squad_members": [],
            "kills": None,
        }
        confidence = {}

        w_img, h_img = img.size

        # --- Step 1: OCR the full center block for overall text ---
        block_crop = _crop_pil(img, REGIONS["stats_center_block"])
        block_4x = block_crop.resize(
            (block_crop.size[0] * 4, block_crop.size[1] * 4), Image.LANCZOS)
        block_text = _ocr_sync(block_4x)
        logger.debug(f"Stats block raw: '{block_text}'")

        # --- Step 2: Parse survived ---
        block_upper = block_text.upper()
        if "EXFILTRAT" in block_upper:
            result["survived"] = True
            confidence["survived"] = 0.95
        elif "ELIMINAT" in block_upper:
            result["survived"] = False
            confidence["survived"] = 0.95
        else:
            # Color fallback on banner area
            banner_arr = np.array(block_crop)
            top_slice = banner_arr[:banner_arr.shape[0] // 5, :, :]
            avg_r = top_slice[:, :, 0].mean()
            avg_g = top_slice[:, :, 1].mean()
            if avg_r > 100 and avg_r > avg_g * 1.5:
                result["survived"] = False
                confidence["survived"] = 0.6
            elif avg_g > 80:
                result["survived"] = True
                confidence["survived"] = 0.6

        # --- Step 3: Per-stat extraction using 3-tier OCR ---
        # Tier 1: Tesseract on full row (label + value, best for single digits)
        # Tier 2: EasyOCR on value-only crop (3x upscale)
        # Tier 3: Pixel analysis fallback

        # Full row regions (label + value together)
        row_regions = {
            "combatant_eliminations": (0.33, 0.615, 0.67, 0.660),
            "runner_eliminations":    (0.33, 0.665, 0.67, 0.710),
            "crew_revives":           (0.33, 0.715, 0.67, 0.760),
            "loot_value_total":       (0.33, 0.765, 0.67, 0.810),
        }
        # Value-only regions (right portion)
        val_regions = {
            "combatant_eliminations": (0.59, 0.630, 0.665, 0.655),
            "runner_eliminations":    (0.59, 0.680, 0.665, 0.705),
            "crew_revives":           (0.59, 0.730, 0.665, 0.755),
            "loot_value_total":       (0.56, 0.780, 0.665, 0.808),
        }

        for field in row_regions:
            # --- Tier 1: Tesseract full-row OCR ---
            if TESSERACT_AVAILABLE and result.get(field) is None:
                row_crop = _crop_pil(img, row_regions[field])
                row_4x = row_crop.resize(
                    (row_crop.size[0] * 4, row_crop.size[1] * 4), Image.LANCZOS)
                try:
                    tess_text = pytesseract.image_to_string(
                        row_4x, config="--psm 7").strip()
                    # Fix slashed-zero font: Q/A/O -> 0, I -> 1
                    tess_fixed = self._fix_slashed_zero(tess_text)
                    logger.debug(f"Tesseract {field}: '{tess_text}' -> '{tess_fixed}'")

                    # Extract number from end of line
                    num_match = re.search(r'(-?\d[\d,]*)\s*\S?\s*$', tess_fixed)
                    if num_match:
                        val = self._parse_number(num_match.group(1))
                        if val is not None:
                            result[field] = val
                            confidence[field] = 0.9
                            continue
                except Exception as e:
                    logger.debug(f"Tesseract failed for {field}: {e}")

            # --- Tier 2: EasyOCR on value-only crop ---
            if EASYOCR_AVAILABLE and result.get(field) is None and field in val_regions:
                val_crop = _crop_pil(img, val_regions[field])
                val_3x = val_crop.resize(
                    (val_crop.size[0] * 3, val_crop.size[1] * 3), Image.LANCZOS)
                try:
                    reader = _get_easyocr()
                    ocr_results = reader.readtext(np.array(val_3x), detail=1)
                    # Use EasyOCR's own confidence scores
                    easyocr_conf = min([c for _, _, c in ocr_results], default=0.5) if ocr_results else 0.5
                    val_text = " ".join([t for _, t, c in ocr_results]).strip()
                    if val_text:
                        num_match = re.search(r'-?\d[\d,]*', val_text)
                        if num_match:
                            val = self._parse_number(num_match.group(1))
                            if val is not None:
                                result[field] = val
                                confidence[field] = round(0.7 * easyocr_conf, 2)
                                continue
                    else:
                        result[field] = 0
                        confidence[field] = 0.5
                        continue
                except Exception as e:
                    logger.debug(f"EasyOCR failed for {field}: {e}")

            # --- Tier 3: Pixel analysis ---
            if result.get(field) is None and field in val_regions:
                pixel_val = self._read_value_by_pixels(img, val_regions[field])
                if pixel_val is not None:
                    result[field] = pixel_val
                    confidence[field] = 0.4

        # --- Step 4: Run time (OCR dedicated region) ---
        rt_crop = _crop_pil(img, REGIONS["stats_run_time"])
        rt_4x = rt_crop.resize(
            (rt_crop.size[0] * 4, rt_crop.size[1] * 4), Image.LANCZOS)
        rt_text = _ocr_sync(rt_4x)
        result["duration_seconds"] = self._parse_duration(rt_text)

        # Also try from block text
        if result["duration_seconds"] is None:
            result["duration_seconds"] = self._parse_duration(block_text)

        if result["duration_seconds"] is not None:
            confidence["duration_seconds"] = 0.85

        # --- Step 5: Calculate kills total ---
        ce = result.get("combatant_eliminations") or 0
        re_ = result.get("runner_eliminations") or 0
        result["kills"] = ce + re_
        # Kills confidence = min of its components
        if ce or re_:
            confidence["kills"] = min(
                confidence.get("combatant_eliminations", 0.0),
                confidence.get("runner_eliminations", 0.0),
            )

        # --- Step 6: Gamertag ---
        gt_crop = _crop_pil(img, REGIONS["gamertag_center"])
        gt_4x = gt_crop.resize(
            (gt_crop.size[0] * 4, gt_crop.size[1] * 4), Image.LANCZOS)
        gt_text = _ocr_sync(gt_4x)
        result["player_gamertag"] = self._parse_gamertag(gt_text)
        if result["player_gamertag"]:
            confidence["player_gamertag"] = 0.8

        result["_confidence"] = confidence
        return result

    def read_loadout_tab(self, img: Image.Image) -> dict:
        """Read weapon names and wallet from LOADOUT tab.

        Returns dict with fields and "_confidence" sub-dict.
        """
        result = {
            "primary_weapon": None,
            "secondary_weapon": None,
            "vault_value": None,
        }
        confidence = {}

        # Primary weapon
        w1_crop = _crop_pil(img, REGIONS["loadout_weapon_1"])
        w1_processed = _preprocess_for_ocr(w1_crop)
        w1_text = _ocr_sync(w1_processed)
        if w1_text:
            # Weapon names are typically ALL CAPS, strip prefixes like "(1)"
            w1_clean = re.sub(r'^\(\d+\)\s*', '', w1_text.split("\n")[0].strip())
            if len(w1_clean) >= 3:
                result["primary_weapon"] = w1_clean
                confidence["primary_weapon"] = 0.75

        # Secondary weapon
        w2_crop = _crop_pil(img, REGIONS["loadout_weapon_2"])
        w2_processed = _preprocess_for_ocr(w2_crop)
        w2_text = _ocr_sync(w2_processed)
        if w2_text:
            w2_clean = re.sub(r'^\(\d+\)\s*', '', w2_text.split("\n")[0].strip())
            if len(w2_clean) >= 3:
                result["secondary_weapon"] = w2_clean
                confidence["secondary_weapon"] = 0.75

        # Wallet balance
        wallet_crop = _crop_pil(img, REGIONS["loadout_wallet"])
        wallet_processed = _preprocess_for_ocr(wallet_crop)
        wallet_text = _ocr_sync(wallet_processed)
        result["vault_value"] = self._parse_number(wallet_text)
        if result["vault_value"] is not None:
            confidence["vault_value"] = 0.7

        result["_confidence"] = confidence
        return result

    def read_readyup(self, img: Image.Image) -> dict:
        """Read gamertag, loadout value, map, and crew from readyup screen.

        Returns dict with fields and "_confidence" sub-dict.
        """
        result = {
            "player_gamertag": None,
            "loadout_value": None,
            "map_name": None,
            "crew_size": None,
        }
        confidence = {}

        # Gamertag
        gt_crop = _crop_pil(img, REGIONS["readyup_gamertag"])
        gt_processed = _preprocess_for_ocr(gt_crop)
        gt_text = _ocr_sync(gt_processed)
        result["player_gamertag"] = self._parse_gamertag(gt_text)
        if result["player_gamertag"]:
            confidence["player_gamertag"] = 0.8

        # Loadout value
        lv_crop = _crop_pil(img, REGIONS["readyup_loadout"])
        lv_processed = _preprocess_for_ocr(lv_crop)
        lv_text = _ocr_sync(lv_processed)
        result["loadout_value"] = self._parse_number(lv_text)
        if result["loadout_value"] is not None:
            confidence["loadout_value"] = 0.75

        # Map + crew from bottom bar
        mc_crop = _crop_pil(img, REGIONS["readyup_map_crew"])
        mc_processed = _preprocess_for_ocr(mc_crop)
        mc_text = _ocr_sync(mc_processed)
        logger.debug(f"Map/crew raw: '{mc_text}'")

        result["map_name"] = self._parse_map_name(mc_text)
        if result["map_name"]:
            confidence["map_name"] = 0.8

        # Crew size
        mc_upper = mc_text.upper()
        if "TRIO" in mc_upper:
            result["crew_size"] = "Trio"
            confidence["crew_size"] = 0.9
        elif "DUO" in mc_upper:
            result["crew_size"] = "Duo"
            confidence["crew_size"] = 0.9
        elif "SOLO" in mc_upper:
            result["crew_size"] = "Solo"
            confidence["crew_size"] = 0.9

        result["_confidence"] = confidence
        return result

    def read_top_bar(self, img: Image.Image) -> dict:
        """Read player level and vault value from top bar.

        Returns dict with fields and "_confidence" sub-dict.
        """
        result = {"player_level": None, "vault_value": None}
        confidence = {}

        level_crop = _crop_pil(img, REGIONS["top_level"])
        level_processed = _preprocess_for_ocr(level_crop)
        level_text = _ocr_sync(level_processed)
        result["player_level"] = self._parse_number(level_text)
        if result["player_level"] is not None:
            confidence["player_level"] = 0.7

        vault_crop = _crop_pil(img, REGIONS["top_vault"])
        vault_processed = _preprocess_for_ocr(vault_crop)
        vault_text = _ocr_sync(vault_processed)
        result["vault_value"] = self._parse_number(vault_text)
        if result["vault_value"] is not None:
            confidence["vault_value"] = 0.7

        result["_confidence"] = confidence
        return result


# =============================================================================
# CLI Testing
# =============================================================================

def test_on_data():
    """Test OCR on available training data screenshots."""
    import json
    import os

    ocr = AlphaOCR()
    training_dir = Path(__file__).parent / "training_data"

    # --- Test coordinate OCR ---
    print("\n=== Testing Coordinate OCR ===")
    coords_dir = training_dir / "deploy"
    if coords_dir.exists():
        correct = 0
        total = 0
        for truth_file in sorted(coords_dir.glob("*_truth.json")):
            with open(truth_file) as f:
                truth = json.load(f)

            # Find corresponding text crop
            prefix = truth_file.stem.replace("_truth", "")
            text_file = coords_dir / f"{prefix}_text.jpg"
            if not text_file.exists():
                continue

            img = Image.open(text_file)
            # The text crop is already cropped to deploy_text region,
            # so we need to OCR the full image, not re-crop
            processed = _preprocess_for_ocr(img)
            text = _ocr_sync(processed)
            coords = AlphaOCR._parse_coordinates(text)
            map_name = AlphaOCR._parse_map_name(text)

            expected_map = truth.get("map_name")
            total += 1

            if map_name and expected_map and map_name.lower() == expected_map.lower():
                correct += 1
                status = "OK"
            else:
                status = "MISS"

            print(f"  [{status}] {prefix}: map={map_name} (expected={expected_map}) coords={coords}")

        if total > 0:
            print(f"\n  Map name accuracy: {correct}/{total} ({correct/total*100:.0f}%)")

    # --- Test stats OCR ---
    print("\n=== Testing Stats Tab OCR ===")
    stats_dir = training_dir / "stats"
    if stats_dir.exists():
        stats_results = []
        for run_dir in sorted(stats_dir.iterdir()):
            if not run_dir.is_dir():
                continue

            gt_file = run_dir / "ground_truth.json"
            if not gt_file.exists():
                continue

            with open(gt_file) as f:
                gt = json.load(f)

            # Find a stats screenshot (prefer stats_2 as it's usually settled)
            for stats_name in ["stats_2.jpg", "stats_1.jpg", "stats_3.jpg"]:
                stats_path = run_dir / stats_name
                if stats_path.exists():
                    break
            else:
                continue

            img = Image.open(stats_path)
            result = ocr.read_stats_tab(img)

            # Compare to ground truth
            fields = ["survived", "combatant_eliminations", "runner_eliminations",
                      "crew_revives", "loot_value_total", "duration_seconds"]
            matches = 0
            total_fields = 0

            print(f"\n  {run_dir.name}:")
            for field in fields:
                expected = gt.get(field)
                actual = result.get(field)
                if expected is not None:
                    total_fields += 1
                    match = (actual == expected)
                    if match:
                        matches += 1
                    status = "OK" if match else "MISS"
                    print(f"    [{status}] {field}: got={actual} expected={expected}")

            if total_fields > 0:
                stats_results.append(matches / total_fields)

        if stats_results:
            avg = sum(stats_results) / len(stats_results)
            print(f"\n  Average field accuracy: {avg*100:.0f}% across {len(stats_results)} runs")


if __name__ == "__main__":
    test_on_data()

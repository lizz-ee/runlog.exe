"""
Alpha Template Matching Engine — Game state detection via OpenCV + pixel gates.

Provides fast, zero-AI game state detection:
- Pixel color gates (sub-millisecond) for initial state filtering
- Template matching (~10-50ms) for confirming UI elements
- HSV analysis for death screen detection

Usage:
    from backend.app.alpha.templates import TemplateEngine
    engine = TemplateEngine()

    # Check game state
    state = engine.detect_game_state(frame)
    # Returns: "deploy", "lobby", "endgame", "stats", "gameplay", or "unknown"

    # Specific detections
    survived = engine.detect_survived(frame)  # True/False/None
    map_name = engine.detect_map_name(frame)  # "Perimeter"/etc or None
    tab = engine.detect_active_tab(frame)     # "STATS"/"PROGRESS"/"LOADOUT"/None
"""

import json
import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
CALIBRATION_PATH = TEMPLATES_DIR / "pixel_calibration.json"

# Known map names
MAP_NAMES = ["Perimeter", "Outpost", "Dire Marsh", "Cryo Archive"]

# --- Pixel Color Definitions ---
# Calibrated from actual Marathon screenshots (see pixel_calibration.json)

# Deploy loading screen: solid blue background
DEPLOY_BLUE = {
    "color_bgr": (179, 63, 25),    # BGR (OpenCV format) from calibration
    "tolerance": 50,
    "check_positions": [(0.5, 0.5), (0.3, 0.3), (0.7, 0.7)],  # Multiple points for confidence
}

# Deploy loading screen: black variant with green text
DEPLOY_BLACK = {
    "color_bgr": (0, 0, 0),
    "tolerance": 20,
    "check_positions": [(0.5, 0.3), (0.2, 0.2)],
    # Distinguish from other black screens by checking for green text center
    "green_text_region": (0.35, 0.42, 0.65, 0.55),  # Map name area should have green pixels
}

# ELIMINATED: red tint across screen, red banner at ~48% height
ELIMINATED_RED = {
    "banner_region": (0.25, 0.42, 0.75, 0.55),
    "min_red_ratio": 0.3,  # At least 30% of banner pixels are red-dominant
}

# EXFILTRATED: yellow-green banner at ~48% height
EXFILTRATED_GREEN = {
    "banner_region": (0.25, 0.42, 0.75, 0.55),
    "min_green_ratio": 0.3,
}

# RUN_COMPLETE: bright yellow-green banner at ~15-22% height
RUN_COMPLETE = {
    "banner_region": (0.28, 0.12, 0.72, 0.22),
    "min_brightness": 150,
    "min_green": 180,
}

# Lobby: bright green READY UP button at bottom center
LOBBY_BUTTON = {
    "region": (0.35, 0.85, 0.65, 0.93),
    "min_green": 160,
    "min_brightness": 120,
}

# Stats tab: cyan highlight on active tab (top-right corner)
STATS_TAB = {
    "region": (0.80, 0.01, 0.88, 0.04),
    "cyan_color_bgr": (200, 200, 50),  # Approximate cyan in BGR
    "tolerance": 60,
}


class TemplateEngine:
    """Fast game state detection using pixel checks and template matching."""

    def __init__(self):
        self._templates = {}
        self._calibration = {}
        self._load_calibration()
        self._load_templates()

    def _load_calibration(self):
        """Load pixel calibration data from JSON."""
        if CALIBRATION_PATH.exists():
            with open(CALIBRATION_PATH) as f:
                self._calibration = json.load(f)
            logger.info(f"Loaded {len(self._calibration)} pixel calibration points")

    def _load_templates(self):
        """Load template images for matching."""
        for subdir in ["maps", "banners", "tabs"]:
            template_dir = TEMPLATES_DIR / subdir
            if not template_dir.exists():
                continue
            for img_path in template_dir.glob("*.jpg"):
                key = f"{subdir}/{img_path.stem}"
                img = cv2.imread(str(img_path))
                if img is not None:
                    self._templates[key] = img
                    # Also store grayscale version for faster matching
                    self._templates[f"{key}_gray"] = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        logger.info(f"Loaded {len(self._templates) // 2} template images")

    # =========================================================================
    # Pixel Color Gates (sub-millisecond)
    # =========================================================================

    @staticmethod
    def _check_pixel(frame: np.ndarray, pos_pct: tuple, expected_bgr: tuple,
                     tolerance: int = 40) -> bool:
        """Check if pixel at percentage position matches expected color."""
        h, w = frame.shape[:2]
        x = int(w * pos_pct[0])
        y = int(h * pos_pct[1])
        # Clamp to valid range
        x = min(max(x, 0), w - 1)
        y = min(max(y, 0), h - 1)
        pixel = frame[y, x]
        diff = sum(abs(int(pixel[i]) - expected_bgr[i]) for i in range(3))
        return diff < tolerance

    @staticmethod
    def _region_color_stats(frame: np.ndarray, region: tuple) -> dict:
        """Get color statistics for a percentage-based region."""
        h, w = frame.shape[:2]
        x1, y1 = int(w * region[0]), int(h * region[1])
        x2, y2 = int(w * region[2]), int(h * region[3])
        crop = frame[y1:y2, x1:x2]

        if crop.size == 0:
            return {"avg_b": 0, "avg_g": 0, "avg_r": 0, "brightness": 0}

        return {
            "avg_b": float(crop[:, :, 0].mean()),
            "avg_g": float(crop[:, :, 1].mean()),
            "avg_r": float(crop[:, :, 2].mean()),
            "brightness": float(crop.mean()),
        }

    def is_deploy_screen(self, frame: np.ndarray) -> bool:
        """Check if frame is a deployment loading screen (blue or black variant)."""
        h, w = frame.shape[:2]

        # Check for blue deploy screen (solid blue background)
        center_stats = self._region_color_stats(frame, (0.35, 0.35, 0.65, 0.65))
        if center_stats["avg_b"] > 130 and center_stats["avg_r"] < 80 and center_stats["avg_g"] < 100:
            return True

        # Check for black deploy screen with green/yellow-green text
        # The screen is very dark overall with sparse green text (map name + coords)
        if center_stats["brightness"] < 30:
            # Use HSV to detect green/yellow-green pixels in the center area
            center_crop = frame[int(h*0.30):int(h*0.70), int(w*0.30):int(w*0.70)]
            hsv = cv2.cvtColor(center_crop, cv2.COLOR_BGR2HSV)
            # Green/yellow-green text: hue 20-90, decent saturation and value
            green_mask = cv2.inRange(hsv, (20, 30, 30), (90, 255, 255))
            green_ratio = green_mask.sum() / (green_mask.size * 255)

            # Even sparse text gives > 0.1% green pixels
            # Also check that green channel dominates (rules out other dark screens)
            if green_ratio > 0.001 and center_stats["avg_g"] > center_stats["avg_r"]:
                return True

            # Additional check: look for the map logo/name text specifically
            # The map name area (42-55%h) should have noticeably more green
            name_area = frame[int(h*0.40):int(h*0.58), int(w*0.35):int(w*0.65)]
            name_hsv = cv2.cvtColor(name_area, cv2.COLOR_BGR2HSV)
            name_green = cv2.inRange(name_hsv, (20, 30, 40), (90, 255, 255))
            name_green_ratio = name_green.sum() / (name_green.size * 255)
            if name_green_ratio > 0.005:
                return True

        return False

    def is_death_screen(self, frame: np.ndarray) -> bool:
        """Check if frame has red death tint (ELIMINATED)."""
        stats = self._region_color_stats(frame, ELIMINATED_RED["banner_region"])
        # Red-dominant banner
        return (stats["avg_r"] > 120 and
                stats["avg_r"] > stats["avg_g"] * 2 and
                stats["avg_r"] > stats["avg_b"] * 2)

    def is_exfiltrated_screen(self, frame: np.ndarray) -> bool:
        """Check if frame shows EXFILTRATED (yellow-green banner)."""
        stats = self._region_color_stats(frame, EXFILTRATED_GREEN["banner_region"])
        # Green/yellow-green dominant banner
        return (stats["avg_g"] > 120 and
                stats["avg_g"] > stats["avg_r"] * 1.3 and
                stats["avg_g"] > stats["avg_b"] * 1.5)

    def is_run_complete(self, frame: np.ndarray) -> bool:
        """Check if frame shows //RUN_COMPLETE banner."""
        stats = self._region_color_stats(frame, RUN_COMPLETE["banner_region"])
        return (stats["brightness"] > RUN_COMPLETE["min_brightness"] and
                stats["avg_g"] > RUN_COMPLETE["min_green"])

    def is_lobby(self, frame: np.ndarray) -> bool:
        """Check if frame shows lobby (READY UP / PREPARE button)."""
        stats = self._region_color_stats(frame, LOBBY_BUTTON["region"])
        return (stats["avg_g"] > LOBBY_BUTTON["min_green"] and
                stats["brightness"] > LOBBY_BUTTON["min_brightness"] and
                stats["avg_g"] > stats["avg_r"] * 1.5)

    def is_stats_screen(self, frame: np.ndarray) -> bool:
        """Check if frame is showing post-match stats (EXFILTRATED/ELIMINATED + stat columns)."""
        h, w = frame.shape[:2]

        # Stats screens are dark overall (character on dark background)
        overall = self._region_color_stats(frame, (0.0, 0.0, 1.0, 1.0))
        if overall["brightness"] > 80:
            return False  # Too bright — gameplay, not stats

        # Must have a colored banner in the ~42-55% height band
        # Check three sub-regions across the banner (left column, center, right)
        # to handle Solo (1 banner) vs Trio (3 banners)
        banner_detected = False
        for region in [(0.05, 0.43, 0.30, 0.53),   # Left column banner
                       (0.35, 0.43, 0.65, 0.53),   # Center column banner
                       (0.70, 0.43, 0.95, 0.53)]:  # Right column banner
            stats = self._region_color_stats(frame, region)
            # Red banner (ELIMINATED): strong red
            if stats["avg_r"] > 100 and stats["avg_r"] > stats["avg_g"] * 2:
                banner_detected = True
                break
            # Green/yellow banner (EXFILTRATED): green dominant
            if stats["avg_g"] > 100 and stats["avg_g"] > stats["avg_r"] * 1.2:
                banner_detected = True
                break

        if not banner_detected:
            # Fallback: try template matching for ELIMINATED banner
            for key in self._templates:
                if "ELIMINATED" in key and not key.endswith("_gray"):
                    matched, conf, _ = self._match_template(
                        frame, key,
                        region=(0.10, 0.35, 0.90, 0.60),
                        threshold=0.60
                    )
                    if matched:
                        banner_detected = True
                        break

        if not banner_detected:
            return False

        # Final check: stat labels below banner should have high-contrast text
        label_area = frame[int(h*0.60):int(h*0.85), int(w*0.05):int(w*0.50)]
        label_std = float(label_area.std())
        return label_std > 25  # High std = text on dark background

    # =========================================================================
    # Template Matching (~10-50ms)
    # =========================================================================

    def _match_template(self, frame: np.ndarray, template_key: str,
                        region: tuple = None, threshold: float = 0.75) -> tuple:
        """
        Match a template against a frame (or region of frame).

        Returns: (matched: bool, confidence: float, location: tuple or None)
        """
        gray_key = f"{template_key}_gray"
        if gray_key not in self._templates:
            return False, 0.0, None

        template = self._templates[gray_key]

        # Crop frame to region of interest if specified
        if region:
            h, w = frame.shape[:2]
            x1, y1 = int(w * region[0]), int(h * region[1])
            x2, y2 = int(w * region[2]), int(h * region[3])
            search_area = frame[y1:y2, x1:x2]
        else:
            search_area = frame
            x1, y1 = 0, 0

        # Convert to grayscale if needed
        if len(search_area.shape) == 3:
            search_gray = cv2.cvtColor(search_area, cv2.COLOR_BGR2GRAY)
        else:
            search_gray = search_area

        # Scale template to match search area if needed
        th, tw = template.shape[:2]
        sh, sw = search_gray.shape[:2]

        if tw > sw or th > sh:
            # Template is larger than search area — scale down
            scale = min(sw / tw, sh / th) * 0.9
            template = cv2.resize(template, (int(tw * scale), int(th * scale)))

        if template.shape[0] > search_gray.shape[0] or template.shape[1] > search_gray.shape[1]:
            return False, 0.0, None

        result = cv2.matchTemplate(search_gray, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= threshold:
            # Convert location back to full frame coordinates
            loc = (max_loc[0] + x1, max_loc[1] + y1)
            return True, float(max_val), loc

        return False, float(max_val), None

    def _match_template_multiscale(self, frame: np.ndarray, template_key: str,
                                    region: tuple = None, threshold: float = 0.75,
                                    scales: list = None) -> tuple:
        """Match template at multiple scales for resolution independence."""
        if scales is None:
            scales = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.4]

        gray_key = f"{template_key}_gray"
        if gray_key not in self._templates:
            return False, 0.0, None

        template_orig = self._templates[gray_key]

        # Crop frame to region
        if region:
            h, w = frame.shape[:2]
            x1, y1 = int(w * region[0]), int(h * region[1])
            x2, y2 = int(w * region[2]), int(h * region[3])
            search_area = frame[y1:y2, x1:x2]
        else:
            search_area = frame

        if len(search_area.shape) == 3:
            search_gray = cv2.cvtColor(search_area, cv2.COLOR_BGR2GRAY)
        else:
            search_gray = search_area

        best_val = 0.0
        best_loc = None

        for scale in scales:
            th = int(template_orig.shape[0] * scale)
            tw = int(template_orig.shape[1] * scale)

            if th < 10 or tw < 10:
                continue
            if th > search_gray.shape[0] or tw > search_gray.shape[1]:
                continue

            template_scaled = cv2.resize(template_orig, (tw, th))
            result = cv2.matchTemplate(search_gray, template_scaled, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val > best_val:
                best_val = max_val
                best_loc = max_loc

        matched = best_val >= threshold
        return matched, float(best_val), best_loc

    # =========================================================================
    # High-Level Detection Functions
    # =========================================================================

    def detect_game_state(self, frame: np.ndarray) -> str:
        """
        Detect the current game state from a frame.

        Returns one of:
            "deploy"    - Deployment loading screen (map name + coordinates visible)
            "lobby"     - Ready up / prepare screen
            "endgame"   - //RUN_COMPLETE banner
            "stats"     - Post-match stats/progress/loadout tabs
            "death"     - In-game death (red tint, before stats)
            "gameplay"  - Active gameplay
            "unknown"   - Cannot determine
        """
        # Fast pixel checks first (sub-millisecond)

        # Deploy screen (blue or black with green text)
        if self.is_deploy_screen(frame):
            return "deploy"

        # RUN_COMPLETE banner
        if self.is_run_complete(frame):
            return "endgame"

        # Stats screen (has tab headers + banner)
        if self.is_stats_screen(frame):
            return "stats"

        # Lobby (READY UP button)
        if self.is_lobby(frame):
            return "lobby"

        # Death screen (red tint) — check after stats since stats also has red for ELIMINATED
        # but death screen has red everywhere, not just the banner
        overall = self._region_color_stats(frame, (0.0, 0.0, 1.0, 1.0))
        if overall["avg_r"] > 80 and overall["avg_r"] > overall["avg_g"] * 1.5:
            return "death"

        # If frame has normal brightness and varied colors, it's gameplay
        if overall["brightness"] > 40:
            return "gameplay"

        return "unknown"

    def detect_survived(self, frame: np.ndarray) -> bool | None:
        """
        Detect if the run was EXFILTRATED (True) or ELIMINATED (False).
        Returns None if cannot determine.
        """
        # Check banner colors
        banner_stats = self._region_color_stats(frame, (0.25, 0.42, 0.75, 0.55))

        # EXFILTRATED: yellow-green banner
        if banner_stats["avg_g"] > 120 and banner_stats["avg_g"] > banner_stats["avg_r"] * 1.3:
            return True

        # ELIMINATED: red banner
        if banner_stats["avg_r"] > 120 and banner_stats["avg_r"] > banner_stats["avg_g"] * 2:
            return False

        # Try template matching as fallback
        for key in self._templates:
            if "ELIMINATED" in key and not key.endswith("_gray"):
                matched, conf, _ = self._match_template(
                    frame, key.replace("banners/", "").replace("_gray", ""),
                    region=(0.20, 0.35, 0.80, 0.60),
                    threshold=0.65
                )
                if matched:
                    return False

            if "EXFILTRATED" in key and not key.endswith("_gray"):
                matched, conf, _ = self._match_template(
                    frame, key.replace("banners/", "").replace("_gray", ""),
                    region=(0.20, 0.35, 0.80, 0.60),
                    threshold=0.65
                )
                if matched:
                    return True

        return None

    def detect_map_name(self, frame: np.ndarray) -> str | None:
        """
        Detect the map name from a deploy loading screen.
        Uses template matching against known map name images.
        Returns map name string or None.
        """
        # Only works on deploy screens
        if not self.is_deploy_screen(frame):
            return None

        best_map = None
        best_conf = 0.0

        for key in self._templates:
            if not key.startswith("maps/") or key.endswith("_gray"):
                continue

            # Skip non-map-name templates (full deploy text, etc.)
            name = key.split("/")[1]
            if name.startswith("DEPLOY_") or name.startswith("MAP_"):
                continue

            # Extract the map name from template filename (e.g., "PERIMETER_3840x2160")
            map_key = name.split("_")[0]

            matched, conf, _ = self._match_template_multiscale(
                frame, key,
                region=(0.25, 0.35, 0.75, 0.65),
                threshold=0.5,
            )

            if conf > best_conf:
                best_conf = conf
                # Convert back to proper case
                for mn in MAP_NAMES:
                    if mn.upper().replace(" ", "_").startswith(map_key):
                        best_map = mn
                        break

        if best_conf > 0.5 and best_map:
            logger.debug(f"Map detected: {best_map} (confidence: {best_conf:.3f})")
            return best_map

        return None

    def detect_active_tab(self, frame: np.ndarray) -> str | None:
        """
        Detect which post-match tab is active (STATS, PROGRESS, or LOADOUT).
        The active tab has a cyan/highlighted background in the top-right.

        Returns: "STATS", "PROGRESS", "LOADOUT", or None
        """
        h, w = frame.shape[:2]

        # Tab positions (percentage-based, top-right corner)
        # From the screenshot: STATS | PROGRESS | LOADOUT in top-right
        tab_regions = {
            "STATS":    (0.78, 0.01, 0.84, 0.04),
            "PROGRESS": (0.85, 0.01, 0.93, 0.04),
            "LOADOUT":  (0.93, 0.01, 1.00, 0.04),
        }

        best_tab = None
        best_brightness = 0

        for tab_name, region in tab_regions.items():
            stats = self._region_color_stats(frame, region)
            # Active tab has cyan/bright highlight
            # Check for high blue+green (cyan) or just highest brightness
            cyan_score = stats["avg_b"] + stats["avg_g"] - stats["avg_r"]
            if cyan_score > best_brightness:
                best_brightness = cyan_score
                best_tab = tab_name

        # Only return if clearly highlighted (not just slightly brighter)
        if best_brightness > 200:
            return best_tab

        return None

    def detect_crew_size(self, frame: np.ndarray) -> str | None:
        """
        Detect crew size from stats screen by counting columns.
        Solo = 1 column (center), Duo = 2, Trio = 3.
        """
        if not self.is_stats_screen(frame):
            return None

        h, w = frame.shape[:2]

        # Check for characters/banners in left and right column positions
        left_stats = self._region_color_stats(frame, (0.05, 0.42, 0.30, 0.55))
        center_stats = self._region_color_stats(frame, (0.35, 0.42, 0.65, 0.55))
        right_stats = self._region_color_stats(frame, (0.70, 0.42, 0.95, 0.55))

        # Columns with banners have significant color (red or green)
        def has_banner(stats):
            return (stats["avg_r"] > 80 or stats["avg_g"] > 80) and stats["brightness"] > 50

        left_active = has_banner(left_stats)
        center_active = has_banner(center_stats)
        right_active = has_banner(right_stats)

        active_count = sum([left_active, center_active, right_active])

        if active_count >= 3:
            return "Trio"
        elif active_count == 2:
            return "Duo"
        elif active_count == 1:
            return "Solo"

        return None

    # =========================================================================
    # Convenience: Crop Helper
    # =========================================================================

    @staticmethod
    def crop_region(frame: np.ndarray, region: tuple) -> np.ndarray:
        """Crop a frame using percentage-based region (x1%, y1%, x2%, y2%)."""
        h, w = frame.shape[:2]
        x1 = int(w * region[0])
        y1 = int(h * region[1])
        x2 = int(w * region[2])
        y2 = int(h * region[3])
        return frame[y1:y2, x1:x2]


# =============================================================================
# CLI Testing
# =============================================================================

def test_on_screenshots():
    """Test template engine on all available screenshots."""
    import os

    engine = TemplateEngine()

    clips_dir = Path(os.environ.get("APPDATA", "")) / "runlog" / "marathon" / "data" / "clips"
    steam_dir = Path(__file__).parents[3] / "screenshots"

    results = {"deploy": 0, "lobby": 0, "endgame": 0, "stats": 0,
               "death": 0, "gameplay": 0, "unknown": 0}
    survived_results = {"correct": 0, "wrong": 0, "unknown": 0}

    # Test on RunLog screenshots
    print("\n=== Testing on RunLog screenshots ===")

    # Load DB for ground truth
    import sqlite3
    db = sqlite3.connect(str(Path(os.environ.get("APPDATA", "")) / "runlog" / "marathon" / "data" / "runlog.db"))
    db.row_factory = sqlite3.Row
    db_runs = {
        row["date"].replace("T", " ").split("+")[0].split(".")[0]: dict(row)
        for row in db.execute("SELECT * FROM runs WHERE survived IS NOT NULL").fetchall()
        if row["date"]
    }
    db.close()

    for folder in sorted(clips_dir.iterdir()):
        if not folder.name.startswith("run_"):
            continue
        ss_dir = folder / "screenshots"
        if not ss_dir.exists():
            continue

        for ss_file in sorted(ss_dir.iterdir()):
            if not ss_file.name.endswith(".jpg"):
                continue
            if "crop" in ss_file.name:
                continue

            frame = cv2.imread(str(ss_file))
            if frame is None:
                continue

            state = engine.detect_game_state(frame)
            results[state] += 1

            # Test survived detection on stats screenshots
            if "stats_" in ss_file.name and state == "stats":
                survived = engine.detect_survived(frame)
                # Match to DB
                folder_ts = folder.name.replace("run_", "")
                try:
                    from backend.app.alpha.data_prep import folder_timestamp_to_db_date
                    db_date = folder_timestamp_to_db_date(folder_ts)
                    db_run = db_runs.get(db_date)
                    if db_run and survived is not None:
                        expected = bool(db_run["survived"])
                        if survived == expected:
                            survived_results["correct"] += 1
                        else:
                            survived_results["wrong"] += 1
                            print(f"  WRONG survived: {folder.name}/{ss_file.name} "
                                  f"detected={survived} expected={expected}")
                    elif survived is None:
                        survived_results["unknown"] += 1
                except Exception:
                    pass

            # Test map detection on deploy screenshots
            if "deploy" in ss_file.name and state == "deploy":
                map_name = engine.detect_map_name(frame)
                print(f"  [deploy] {folder.name}/{ss_file.name}: map={map_name}")

    print(f"\n  State detection results:")
    for state, count in sorted(results.items()):
        print(f"    {state}: {count}")

    print(f"\n  Survived detection accuracy:")
    total = sum(survived_results.values())
    if total > 0:
        print(f"    Correct: {survived_results['correct']}/{total} "
              f"({survived_results['correct']/total*100:.0f}%)")
        print(f"    Wrong: {survived_results['wrong']}")
        print(f"    Unknown: {survived_results['unknown']}")

    # Test on Steam screenshots
    print("\n=== Testing on Steam screenshots ===")
    steam_results = {"deploy": 0, "lobby": 0, "endgame": 0, "stats": 0,
                     "death": 0, "gameplay": 0, "unknown": 0}

    if steam_dir.exists():
        for ss_file in sorted(steam_dir.glob("*.jpg")):
            if not ss_file.name[0].isdigit():
                continue
            frame = cv2.imread(str(ss_file))
            if frame is None:
                continue
            state = engine.detect_game_state(frame)
            steam_results[state] += 1

        print(f"  State detection results:")
        for state, count in sorted(steam_results.items()):
            print(f"    {state}: {count}")


if __name__ == "__main__":
    test_on_screenshots()

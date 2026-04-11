"""
Alpha Processor — Orchestrator replacing Claude API calls for stat extraction.

This is the main entry point for the alpha pipeline. It provides the same
interface as video_processor.py's Claude calls but uses local detection:
  - Template matching for game state detection
  - winocr for text extraction
  - Pixel analysis for single-digit values
  - Rule-based grading
  - Template-based summaries

Usage:
    from backend.app.alpha.processor import AlphaProcessor
    proc = AlphaProcessor()

    # Phase 1: Extract stats from screenshots
    stats = proc.process_phase1(screenshots_dir)

    # Phase 2: Grade + summary (no video analysis)
    phase2 = proc.process_phase2(stats)
"""

import json
import logging
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from backend.app.alpha.grading import calculate_grade, generate_summary
from backend.app.alpha.ocr_pipeline import AlphaOCR
from backend.app.alpha.shell_classifier import ShellClassifier
from backend.app.alpha.templates import TemplateEngine

logger = logging.getLogger(__name__)

# Default confidence threshold for hybrid fallback
DEFAULT_CONFIDENCE_THRESHOLD = 0.8


class AlphaProcessor:
    """
    Local stat extraction processor — replaces all Claude API calls.

    Drop-in replacement for the Claude-based video_processor pipeline.
    Uses template matching + OCR + rule-based grading.
    """

    def __init__(self):
        self.engine = TemplateEngine()
        self.ocr = AlphaOCR()
        self.shell_classifier = ShellClassifier()
        logger.info("AlphaProcessor initialized (Claude-free mode)")

    # =========================================================================
    # Phase 1: Stat Extraction (replaces Claude Calls 1A, 2A, 3A, 2)
    # =========================================================================

    def process_phase1(self, screenshots_dir: str | Path) -> dict:
        """
        Process all screenshots from a run and extract stats.

        Replaces:
          - Call 1A (loadout & identity): map, gamertag, squad, crew size, loadout value
          - Call 2A (shell ID): shell_name (requires trained classifier, returns None for now)
          - Call 3A (spawn coords): spawn_coordinates
          - Call 2 (end stats): survived, kills, loot, weapons, killed_by, etc.

        Parameters
        ----------
        screenshots_dir : path to folder containing run screenshots
            Expected files: readyup.jpg, deploy*.jpg, stats_*.jpg, endgame.jpg, etc.

        Returns
        -------
        dict with all extracted fields (same schema as video_processor output).
        Includes "_confidence" dict mapping field names to 0.0-1.0 scores,
        and "_low_confidence_fields" list of fields below threshold.
        """
        ss_dir = Path(screenshots_dir)
        result = {
            # Call 1A fields
            "map_name": None,
            "is_ranked": None,
            "player_gamertag": None,
            "squad_members": None,
            "crew_size": None,
            "loadout_value": None,
            # Call 2A fields
            "shell_name": None,
            # Call 3A fields
            "spawn_coordinates": None,
            # Call 2 fields
            "survived": None,
            "kills": None,
            "combatant_eliminations": None,
            "runner_eliminations": None,
            "deaths": None,
            "crew_revives": None,
            "duration_seconds": None,
            "loot_value_total": None,
            "primary_weapon": None,
            "secondary_weapon": None,
            "killed_by": None,
            "killed_by_weapon": None,
            "killed_by_damage": None,
            "damage_contributors": None,
            "player_level": None,
            "vault_value": None,
            "stats_tab_found": False,
            "loadout_tab_found": False,
        }
        confidence = {}

        # --- Call 1A: Loadout & Identity (deploy + readyup screenshots) ---
        loadout_data = self._extract_loadout(ss_dir)
        conf = loadout_data.pop("_confidence", {})
        result.update(loadout_data)
        confidence.update(conf)

        # --- Call 2A: Shell ID (character crop from readyup screenshots) ---
        shell_data = self._extract_shell(ss_dir)
        conf = shell_data.pop("_confidence", {})
        result.update(shell_data)
        confidence.update(conf)

        # --- Call 3A: Spawn Coordinates (deploy screenshots) ---
        coords_data = self._extract_coordinates(ss_dir)
        conf = coords_data.pop("_confidence", {})
        result.update(coords_data)
        confidence.update(conf)

        # --- Call 2: End Stats (stats + endgame screenshots) ---
        stats_data = self._extract_stats(ss_dir)
        conf = stats_data.pop("_confidence", {})
        result.update(stats_data)
        confidence.update(conf)

        # --- Derive fields ---
        if result["survived"] is not None:
            result["deaths"] = 0 if result["survived"] else 1

        # --- Build confidence report ---
        # Fields that matter for hybrid gate (skip metadata fields)
        gated_fields = [
            "map_name", "survived", "kills", "combatant_eliminations",
            "runner_eliminations", "crew_revives", "loot_value_total",
            "duration_seconds", "shell_name", "spawn_coordinates",
            "primary_weapon", "secondary_weapon",
        ]
        low_conf = []
        for field in gated_fields:
            if result.get(field) is not None:
                score = confidence.get(field, 0.0)
                if score < DEFAULT_CONFIDENCE_THRESHOLD:
                    low_conf.append(field)
            elif field in ("survived", "kills", "duration_seconds"):
                # Critical fields that are None = definitely low confidence
                low_conf.append(field)

        result["_confidence"] = confidence
        result["_low_confidence_fields"] = low_conf
        logger.info(
            f"Phase 1 complete: {len(confidence)} fields scored, "
            f"{len(low_conf)} below threshold ({DEFAULT_CONFIDENCE_THRESHOLD})"
        )
        if low_conf:
            logger.info(f"Low confidence fields: {low_conf}")

        return result

    def _extract_loadout(self, ss_dir: Path) -> dict:
        """Extract loadout info from readyup and deploy screenshots (Call 1A)."""
        extracted = {}
        confidence = {}

        # --- Map name from deploy screenshots ---
        for name in ["deploy.jpg", "deploy_1.jpg", "deploy_2.jpg", "deploy_3.jpg"]:
            path = ss_dir / name
            if not path.exists():
                continue

            frame = cv2.imread(str(path))
            if frame is None:
                continue

            # Template match first (fastest, high confidence)
            map_name = self.engine.detect_map_name(frame)
            if map_name:
                extracted["map_name"] = map_name
                confidence["map_name"] = 0.95
                break

            # OCR fallback
            img = Image.open(path)
            map_data = self.ocr.read_map_name(img)
            if map_data.get("map_name"):
                extracted["map_name"] = map_data["map_name"]
                confidence.update(map_data.get("_confidence", {}))
                break

        # --- Readyup screen info ---
        for name in ["readyup.jpg", "readyup_1.jpg", "readyup_2.jpg"]:
            path = ss_dir / name
            if not path.exists():
                continue

            img = Image.open(path)
            readyup_data = self.ocr.read_readyup(img)
            readyup_conf = readyup_data.pop("_confidence", {})

            if readyup_data.get("player_gamertag"):
                extracted["player_gamertag"] = readyup_data["player_gamertag"]
                if "player_gamertag" in readyup_conf:
                    confidence["player_gamertag"] = readyup_conf["player_gamertag"]
            if readyup_data.get("loadout_value") is not None:
                extracted["loadout_value"] = readyup_data["loadout_value"]
                if "loadout_value" in readyup_conf:
                    confidence["loadout_value"] = readyup_conf["loadout_value"]
            if readyup_data.get("map_name") and not extracted.get("map_name"):
                extracted["map_name"] = readyup_data["map_name"]
                if "map_name" in readyup_conf:
                    confidence["map_name"] = readyup_conf["map_name"]
            if readyup_data.get("crew_size"):
                extracted["crew_size"] = readyup_data["crew_size"]
                if "crew_size" in readyup_conf:
                    confidence["crew_size"] = readyup_conf["crew_size"]
            break

        extracted["_confidence"] = confidence
        return extracted

    def _extract_shell(self, ss_dir: Path) -> dict:
        """Classify the player's shell from character crop images (Call 2A)."""
        conf_map = {}

        # Look for character crop files (named *_char.jpg)
        char_crops = sorted([
            f for f in ss_dir.iterdir()
            if f.name.endswith("_char.jpg") and f.suffix == ".jpg"
        ])

        if not char_crops:
            # Also check for character_crop.jpg naming
            crop = ss_dir / "character_crop.jpg"
            if crop.exists():
                char_crops = [crop]

        for crop_path in char_crops:
            try:
                shell_name, shell_conf = self.shell_classifier.predict(crop_path)
                if shell_conf >= 0.5:
                    logger.info(
                        "Shell classified: %s (%.1f%%) from %s",
                        shell_name, shell_conf * 100, crop_path.name,
                    )
                    conf_map["shell_name"] = round(shell_conf, 2)
                    return {"shell_name": shell_name, "_confidence": conf_map}
                else:
                    logger.info(
                        "Shell prediction below threshold: %s (%.1f%%) from %s",
                        shell_name, shell_conf * 100, crop_path.name,
                    )
            except Exception:
                logger.warning("Shell classification failed for %s", crop_path.name, exc_info=True)

        return {"_confidence": conf_map}

    def _extract_coordinates(self, ss_dir: Path) -> dict:
        """Extract spawn coordinates from deploy screenshots (Call 3A)."""
        for name in ["deploy_1.jpg", "deploy_2.jpg", "deploy_3.jpg", "deploy.jpg"]:
            path = ss_dir / name
            if not path.exists():
                continue

            img = Image.open(path)

            # Check if it's a deploy screen
            frame = cv2.imread(str(path))
            if frame is None or not self.engine.is_deploy_screen(frame):
                continue

            coords_data = self.ocr.read_spawn_coordinates(img)
            if coords_data.get("spawn_coordinates"):
                return coords_data

        return {"_confidence": {}}

    def _extract_stats(self, ss_dir: Path) -> dict:
        """Extract end-of-run stats from stats/endgame screenshots (Call 2)."""
        extracted = {}
        confidence = {}

        # --- Stats tab screenshots (primary source) ---
        stats_files = sorted([
            f for f in ss_dir.iterdir()
            if f.name.startswith("stats_") and "crop" not in f.name and f.suffix == ".jpg"
        ])

        if stats_files:
            extracted["stats_tab_found"] = True

            # Use stats_3 if available (stats_1/2 may capture the EXFILTRATED splash
            # before stat values load). stats_3 is most likely to have full data.
            best = stats_files[-1] if len(stats_files) > 0 else stats_files[0]
            img = Image.open(best)

            stats_data = self.ocr.read_stats_tab(img)
            stats_conf = stats_data.pop("_confidence", {})
            extracted.update({k: v for k, v in stats_data.items() if v is not None})
            confidence.update(stats_conf)

            # Try other stats screenshots for missing fields
            for sf in stats_files:
                if sf == best:
                    continue
                img2 = Image.open(sf)
                stats2 = self.ocr.read_stats_tab(img2)
                stats2_conf = stats2.pop("_confidence", {})
                for key, val in stats2.items():
                    if val is not None and extracted.get(key) is None:
                        extracted[key] = val
                        if key in stats2_conf:
                            confidence[key] = stats2_conf[key]

        # --- Endgame screenshot (survived detection fallback) ---
        endgame = ss_dir / "endgame.jpg"
        if endgame.exists() and extracted.get("survived") is None:
            frame = cv2.imread(str(endgame))
            if frame is not None:
                survived = self.engine.detect_survived(frame)
                if survived is not None:
                    extracted["survived"] = survived
                    confidence["survived"] = 0.85  # Template match = reliable

        extracted["_confidence"] = confidence
        return extracted

    # =========================================================================
    # Phase 2: Grade + Summary (replaces Claude video analysis)
    # =========================================================================

    def process_phase2(self, stats: dict, video_path: str | None = None) -> dict:
        """
        Generate grade, summary, and highlights from extracted stats + video.

        Replaces Claude Phase 2. Uses:
        - Rule-based grading
        - Template-based summaries
        - HUD detection + audio analysis for highlights (if video provided)

        Parameters
        ----------
        stats : dict from process_phase1()
        video_path : optional path to the run's video file for highlight detection

        Returns
        -------
        dict with: grade, summary, highlights, audio_segments
        """
        # Detect highlights from video (HUD + audio)
        highlights = []
        audio_segments = []
        combat_intensity = 0.0

        if video_path:
            try:
                from backend.app.alpha.highlight_detector import HighlightDetector

                detector = HighlightDetector()
                highlights = detector.detect(video_path, stats=stats)
                logger.info(f"Detected {len(highlights)} highlights from video")

                # Reuse audio segments from highlight detector (avoids double extraction)
                audio_segments = getattr(detector, "last_audio_segments", [])
                if audio_segments:
                    combat_segs = [s for s in audio_segments if s.is_combat]
                    combat_intensity = (
                        sum(s.intensity for s in combat_segs) / len(combat_segs)
                        if combat_segs else 0.0
                    )
                    logger.info(
                        f"Audio: {len(audio_segments)} segments, "
                        f"{len(combat_segs)} combat, intensity={combat_intensity:.2f}"
                    )
            except Exception as e:
                logger.error(f"Highlight/audio detection failed (non-fatal): {e}")

        grade = calculate_grade(
            survived=bool(stats.get("survived", False)),
            runner_kills=stats.get("runner_eliminations") or 0,
            combatant_kills=stats.get("combatant_eliminations") or 0,
            loot_value=stats.get("loot_value_total") or 0,
            crew_revives=stats.get("crew_revives") or 0,
            duration_seconds=stats.get("duration_seconds") or 0,
            combat_intensity=combat_intensity,
        )

        summary_input = {**stats, "grade": grade}
        summary = generate_summary(summary_input)

        return {
            "grade": grade,
            "summary": summary,
            "highlights": highlights,
            "audio_segments": len(audio_segments),
            "combat_intensity": round(combat_intensity, 2),
        }

    # =========================================================================
    # Full Pipeline (both phases)
    # =========================================================================

    def process_run(self, screenshots_dir: str | Path,
                    video_path: str | None = None) -> dict:
        """
        Process a complete run: extract stats, grade, summary, and highlights.

        Parameters
        ----------
        screenshots_dir : path to folder containing run screenshots
        video_path : optional path to run video for highlight detection

        Returns
        -------
        dict with all fields (stats + grade + summary + highlights)
        """
        # Phase 1
        stats = self.process_phase1(screenshots_dir)

        # Auto-detect video if not provided
        if video_path is None:
            ss_dir = Path(screenshots_dir)
            parent = ss_dir.parent if ss_dir.name == "screenshots" else ss_dir
            for mp4 in parent.glob("*.mp4"):
                video_path = str(mp4)
                break

        # Phase 2
        phase2 = self.process_phase2(stats, video_path=video_path)
        stats.update(phase2)

        return stats


# =============================================================================
# CLI: Process a specific run or all runs
# =============================================================================

def process_single_run(run_dir: str):
    """Process a single run directory and print results."""
    proc = AlphaProcessor()
    ss_dir = Path(run_dir) / "screenshots" if (Path(run_dir) / "screenshots").exists() else Path(run_dir)

    print(f"Processing: {ss_dir}")
    result = proc.process_run(ss_dir)

    print(f"\n--- Results ---")
    for key, val in sorted(result.items()):
        if val is not None and val != [] and val != "":
            print(f"  {key}: {val}")


def process_all_runs():
    """Process all available runs and compare to DB ground truth."""
    import os
    from backend.app.alpha.data_prep import CLIPS_DIR, get_db_runs, match_folder_to_run

    proc = AlphaProcessor()
    runs = get_db_runs()

    print("Processing all runs with AlphaProcessor...\n")

    for folder in sorted(CLIPS_DIR.iterdir()):
        if not folder.name.startswith("run_"):
            continue
        ss_dir = folder / "screenshots"
        if not ss_dir.exists():
            continue

        run = match_folder_to_run(folder.name, runs)
        if not run:
            continue

        result = proc.process_run(ss_dir)

        # Compare key fields
        print(f"\n{folder.name} (run #{run['id']}):")
        fields = ["map_name", "survived", "kills", "loot_value_total",
                   "duration_seconds", "grade"]
        for f in fields:
            expected = run.get(f)
            actual = result.get(f)
            match = ""
            if expected is not None and actual is not None:
                if f == "survived":
                    match = "OK" if bool(actual) == bool(expected) else "MISS"
                elif f in ("loot_value_total", "duration_seconds"):
                    match = "OK" if actual is not None and abs(float(actual) - float(expected)) < 50 else "MISS"
                else:
                    match = "OK" if str(actual).lower() == str(expected).lower() else "MISS"
            print(f"  {f}: got={actual} expected={expected} {match}")

        # Show generated summary
        if result.get("summary"):
            print(f"  summary: {result['summary'][:120]}...")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        process_single_run(sys.argv[1])
    else:
        process_all_runs()

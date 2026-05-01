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
from backend.app.alpha.health import alpha_health
from backend.app.alpha.ocr_pipeline import AlphaOCR
from backend.app.alpha.shell_classifier import ShellClassifier
from backend.app.alpha.templates import TemplateEngine

logger = logging.getLogger(__name__)

# Default confidence threshold for hybrid fallback
DEFAULT_CONFIDENCE_THRESHOLD = 0.8

GATED_FIELDS = [
    "map_name", "survived", "kills", "combatant_eliminations",
    "runner_eliminations", "crew_revives", "loot_value_total",
    "duration_seconds", "shell_name", "spawn_coordinates",
    "primary_weapon", "secondary_weapon", "player_level", "vault_value",
]

DEATH_GATED_FIELDS = [
    "killed_by", "killed_by_weapon", "killed_by_damage", "damage_contributors",
]

SHELL_ACCEPT_CONFIDENCE = 0.75
SHELL_REPORT_CONFIDENCE = 0.55


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

    @staticmethod
    def _set_if_better(
        extracted: dict,
        confidence: dict,
        sources: dict,
        field: str,
        value,
        score: float | None,
        source: str,
    ) -> None:
        """Keep the highest-confidence value for a field."""
        if value is None:
            return
        current_score = confidence.get(field, -1.0)
        if extracted.get(field) is None or (score is not None and score >= current_score):
            extracted[field] = value
            if score is not None:
                confidence[field] = score
            sources[field] = source

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
        sources = {}
        metadata = {}

        # --- Call 1A: Loadout & Identity (deploy + readyup screenshots) ---
        loadout_data = self._extract_loadout(ss_dir)
        conf = loadout_data.pop("_confidence", {})
        sources.update(loadout_data.pop("_sources", {}))
        result.update(loadout_data)
        confidence.update(conf)

        # --- Call 2A: Shell ID (character crop from readyup screenshots) ---
        shell_data = self._extract_shell(ss_dir)
        conf = shell_data.pop("_confidence", {})
        sources.update(shell_data.pop("_sources", {}))
        if "_shell_candidates" in shell_data:
            metadata["_shell_candidates"] = shell_data.pop("_shell_candidates")
        result.update(shell_data)
        confidence.update(conf)

        # --- Call 3A: Spawn Coordinates (deploy screenshots) ---
        coords_data = self._extract_coordinates(ss_dir)
        conf = coords_data.pop("_confidence", {})
        sources.update(coords_data.pop("_sources", {}))
        result.update(coords_data)
        confidence.update(conf)

        # --- Call 2: End Stats (stats + endgame screenshots) ---
        stats_data = self._extract_stats(ss_dir)
        conf = stats_data.pop("_confidence", {})
        sources.update(stats_data.pop("_sources", {}))
        if "_tab_classification" in stats_data:
            metadata["_tab_classification"] = stats_data.pop("_tab_classification")
        result.update(stats_data)
        confidence.update(conf)

        # --- Derive fields ---
        if result["survived"] is not None:
            result["deaths"] = 0 if result["survived"] else 1

        # --- Build confidence report ---
        low_conf = []
        gated_fields = list(GATED_FIELDS)
        if result.get("survived") is not True:
            gated_fields.extend(DEATH_GATED_FIELDS)
        for field in gated_fields:
            if result.get(field) is not None:
                score = confidence.get(field, 0.0)
                if score < DEFAULT_CONFIDENCE_THRESHOLD:
                    low_conf.append(field)
            else:
                low_conf.append(field)

        result["_confidence"] = confidence
        result["_low_confidence_fields"] = low_conf
        result["_sources"] = sources
        result.update(metadata)
        capability = alpha_health()
        result["_alpha_health"] = {
            "confidence_threshold": DEFAULT_CONFIDENCE_THRESHOLD,
            "fields_scored": len(confidence),
            "low_confidence_fields": low_conf,
            "routing": "alpha",
            "capability_status": capability.get("status"),
            "capability_ready": capability.get("ready"),
            "capability_blockers": capability.get("blockers", []),
            "capability_warnings": capability.get("warnings", []),
        }
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
        sources = {}

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
                sources["map_name"] = path.name
                break

            # OCR fallback
            img = Image.open(path)
            map_data = self.ocr.read_map_name(img)
            if map_data.get("map_name"):
                extracted["map_name"] = map_data["map_name"]
                confidence.update(map_data.get("_confidence", {}))
                sources["map_name"] = path.name
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
                sources["player_gamertag"] = path.name
            if readyup_data.get("loadout_value") is not None:
                extracted["loadout_value"] = readyup_data["loadout_value"]
                if "loadout_value" in readyup_conf:
                    confidence["loadout_value"] = readyup_conf["loadout_value"]
                sources["loadout_value"] = path.name
            if readyup_data.get("map_name") and not extracted.get("map_name"):
                extracted["map_name"] = readyup_data["map_name"]
                if "map_name" in readyup_conf:
                    confidence["map_name"] = readyup_conf["map_name"]
                sources["map_name"] = path.name
            if readyup_data.get("crew_size"):
                extracted["crew_size"] = readyup_data["crew_size"]
                if "crew_size" in readyup_conf:
                    confidence["crew_size"] = readyup_conf["crew_size"]
                sources["crew_size"] = path.name
            break

        extracted["_confidence"] = confidence
        extracted["_sources"] = sources
        return extracted

    def _extract_shell(self, ss_dir: Path) -> dict:
        """Classify the player's shell from character crop images (Call 2A)."""
        conf_map = {}
        sources = {}
        candidates_by_crop = {}

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
        face_crop = ss_dir / "face_crop.jpg"
        if face_crop.exists():
            char_crops.append(face_crop)

        for crop_path in char_crops:
            try:
                topk = self.shell_classifier.predict_topk(crop_path, k=3)
                candidates_by_crop[crop_path.name] = [
                    {"shell": name, "confidence": round(conf, 3)}
                    for name, conf in topk
                ]
                shell_name, shell_conf = topk[0]
                if shell_conf >= SHELL_ACCEPT_CONFIDENCE:
                    logger.info(
                        "Shell classified: %s (%.1f%%) from %s",
                        shell_name, shell_conf * 100, crop_path.name,
                    )
                    conf_map["shell_name"] = round(shell_conf, 2)
                    sources["shell_name"] = crop_path.name
                    return {
                        "shell_name": shell_name,
                        "_confidence": conf_map,
                        "_sources": sources,
                        "_shell_candidates": candidates_by_crop,
                    }
                elif shell_conf >= SHELL_REPORT_CONFIDENCE:
                    conf_map["shell_name"] = round(shell_conf, 2)
                    sources["shell_name"] = crop_path.name
                    return {
                        "shell_name": shell_name,
                        "_confidence": conf_map,
                        "_sources": sources,
                        "_shell_candidates": candidates_by_crop,
                    }
                else:
                    logger.info(
                        "Shell prediction below threshold: %s (%.1f%%) from %s",
                        shell_name, shell_conf * 100, crop_path.name,
                    )
            except Exception:
                logger.warning("Shell classification failed for %s", crop_path.name, exc_info=True)

        return {"_confidence": conf_map, "_sources": sources, "_shell_candidates": candidates_by_crop}

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
                coords_data["_sources"] = {"spawn_coordinates": path.name}
                return coords_data

        return {"_confidence": {}, "_sources": {}}

    def _extract_stats(self, ss_dir: Path) -> dict:
        """Extract end-of-run stats from stats/endgame screenshots (Call 2)."""
        extracted = {}
        confidence = {}
        sources = {}
        tab_classification = []

        # --- Stats tab screenshots (primary source) ---
        stats_files = sorted([
            f for f in ss_dir.iterdir()
            if f.name.startswith("stats_") and "crop" not in f.name and f.suffix == ".jpg"
        ])

        if stats_files:
            # Later stats captures tend to be more settled, but classify every
            # image so LOADOUT/PROGRESS frames feed the readers built for them.
            for sf in reversed(stats_files):
                frame = cv2.imread(str(sf))
                img = Image.open(sf)
                state = self.engine.detect_game_state(frame) if frame is not None else "unknown"
                tab = self.engine.detect_active_tab(frame) if frame is not None else None
                crew_size = self.engine.detect_crew_size(frame) if frame is not None else None

                if state == "stats" and tab is None:
                    tab = "STATS"

                tab_classification.append({
                    "file": sf.name,
                    "state": state,
                    "tab": tab,
                    "crew_size": crew_size,
                })

                if state not in ("stats", "endgame", "unknown"):
                    continue

                # The top bar exists on every post-match report and carries the
                # safest player level/vault value, so read it regardless of tab.
                top_data = self.ocr.read_top_bar(img)
                top_conf = top_data.pop("_confidence", {})
                for key, val in top_data.items():
                    self._set_if_better(
                        extracted, confidence, sources,
                        key, val, top_conf.get(key), sf.name,
                    )

                if tab == "LOADOUT":
                    extracted["loadout_tab_found"] = True
                    loadout_data = self.ocr.read_loadout_tab(img)
                    loadout_conf = loadout_data.pop("_confidence", {})
                    for key, val in loadout_data.items():
                        self._set_if_better(
                            extracted, confidence, sources,
                            key, val, loadout_conf.get(key), sf.name,
                        )
                    continue

                if tab == "STATS" or (state == "stats" and tab is None):
                    stats_data = self.ocr.read_stats_tab(img, crew_size=crew_size)
                    stats_conf = stats_data.pop("_confidence", {})
                    if stats_data.get("survived") is not None or stats_data.get("duration_seconds") is not None:
                        extracted["stats_tab_found"] = True
                    for key, val in stats_data.items():
                        self._set_if_better(
                            extracted, confidence, sources,
                            key, val, stats_conf.get(key), sf.name,
                        )

            # If tab highlighting was unreliable, try loadout OCR on the last
            # screenshot as a low-cost fallback for weapon/vault fields.
            if not extracted.get("loadout_tab_found") and stats_files:
                fallback = stats_files[-1]
                img = Image.open(fallback)
                loadout_data = self.ocr.read_loadout_tab(img)
                loadout_conf = loadout_data.pop("_confidence", {})
                found_loadout_field = False
                for key, val in loadout_data.items():
                    if val is not None:
                        found_loadout_field = True
                    self._set_if_better(
                        extracted, confidence, sources,
                        key, val, min(loadout_conf.get(key, 0.0), 0.6), fallback.name,
                    )
                if found_loadout_field:
                    extracted["loadout_tab_found"] = True

        # --- Endgame screenshot (survived detection fallback) ---
        endgame = ss_dir / "endgame.jpg"
        if endgame.exists() and extracted.get("survived") is None:
            frame = cv2.imread(str(endgame))
            if frame is not None:
                survived = self.engine.detect_survived(frame)
                if survived is not None:
                    extracted["survived"] = survived
                    confidence["survived"] = 0.85  # Template match = reliable
                    sources["survived"] = endgame.name

        # --- Death widget (right side of RUN_COMPLETE/death screen) ---
        for name in ["endgame_damage.jpg", "endgame.jpg"]:
            dmg_path = ss_dir / name
            if not dmg_path.exists():
                continue
            dmg_data = self.ocr.read_damage_widget(Image.open(dmg_path))
            dmg_conf = dmg_data.pop("_confidence", {})
            for key, val in dmg_data.items():
                self._set_if_better(
                    extracted, confidence, sources,
                    key, val, dmg_conf.get(key), dmg_path.name,
                )

        extracted["_confidence"] = confidence
        extracted["_sources"] = sources
        extracted["_tab_classification"] = tab_classification
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

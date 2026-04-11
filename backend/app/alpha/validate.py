"""
Alpha Validation Suite — Test OCR + template accuracy against DB ground truth.

Loads all runs with screenshots, runs the alpha detection pipeline,
and compares results to database values. Reports per-field accuracy.

Usage:
    python -m backend.app.alpha.validate
"""

import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from backend.app.alpha.data_prep import (
    CLIPS_DIR, DB_PATH, folder_timestamp_to_db_date, get_db_runs, match_folder_to_run,
)
from backend.app.alpha.grading import calculate_grade, generate_summary
from backend.app.alpha.ocr_pipeline import AlphaOCR
from backend.app.alpha.templates import TemplateEngine


def validate_all():
    """Run full validation against all available data."""
    print("=" * 70)
    print("ALPHA VALIDATION SUITE")
    print("=" * 70)

    runs = get_db_runs()
    engine = TemplateEngine()
    ocr = AlphaOCR()

    # Track results per field
    fields = [
        "game_state", "survived", "map_name",
        "combatant_eliminations", "runner_eliminations", "crew_revives",
        "loot_value_total", "duration_seconds", "grade",
    ]
    field_results = {f: {"correct": 0, "wrong": 0, "missing": 0, "total": 0}
                     for f in fields}

    run_count = 0

    for folder in sorted(CLIPS_DIR.iterdir()):
        if not folder.name.startswith("run_"):
            continue
        ss_dir = folder / "screenshots"
        if not ss_dir.exists():
            continue

        run = match_folder_to_run(folder.name, runs)
        if not run:
            continue

        # --- Find screenshots ---
        stats_files = sorted([f for f in ss_dir.iterdir()
                              if f.name.startswith("stats_") and "crop" not in f.name])
        deploy_files = sorted([f for f in ss_dir.iterdir()
                               if f.name.startswith("deploy") and "crop" not in f.name])
        endgame_file = ss_dir / "endgame.jpg"
        readyup_file = ss_dir / "readyup.jpg"

        if not stats_files and not deploy_files:
            continue

        run_count += 1
        print(f"\n--- {folder.name} (run #{run['id']}) ---")

        # === Test Game State Detection ===
        for ss_file in list(stats_files[:1]) + list(deploy_files[:1]):
            frame = cv2.imread(str(ss_file))
            if frame is None:
                continue
            detected_state = engine.detect_game_state(frame)

            expected_state = "stats" if "stats" in ss_file.name else "deploy"
            field_results["game_state"]["total"] += 1
            if detected_state == expected_state:
                field_results["game_state"]["correct"] += 1
            else:
                field_results["game_state"]["wrong"] += 1
                print(f"  [state MISS] {ss_file.name}: got={detected_state} expected={expected_state}")

        # === Test Map Name (deploy screenshots) ===
        if deploy_files:
            for deploy_file in deploy_files[:1]:
                frame = cv2.imread(str(deploy_file))
                if frame is None:
                    continue

                # Template-based map detection
                tmpl_map = engine.detect_map_name(frame)

                # OCR-based map detection
                deploy_img = Image.open(deploy_file)
                ocr_map_data = ocr.read_map_name(deploy_img)
                ocr_map = ocr_map_data.get("map_name") if isinstance(ocr_map_data, dict) else ocr_map_data

                # Use best result
                detected_map = tmpl_map or ocr_map
                expected_map = run.get("map_name")

                if expected_map:
                    field_results["map_name"]["total"] += 1
                    if detected_map and detected_map.lower() == expected_map.lower():
                        field_results["map_name"]["correct"] += 1
                    elif detected_map is None:
                        field_results["map_name"]["missing"] += 1
                        print(f"  [map MISS] no detection (expected={expected_map})")
                    else:
                        field_results["map_name"]["wrong"] += 1
                        print(f"  [map WRONG] got={detected_map} expected={expected_map}")

        # === Test Stats Tab OCR ===
        if stats_files:
            # Use stats_2 (usually best — UI settled) or stats_1
            best_stats = stats_files[1] if len(stats_files) > 1 else stats_files[0]
            stats_img = Image.open(best_stats)

            # Run OCR
            ocr_result = ocr.read_stats_tab(stats_img)

            # Compare each field
            stat_fields = {
                "survived": ("survived", lambda x: bool(x)),
                "combatant_eliminations": ("combatant_eliminations", lambda x: int(x) if x is not None else None),
                "runner_eliminations": ("runner_eliminations", lambda x: int(x) if x is not None else None),
                "crew_revives": ("crew_revives", lambda x: int(x) if x is not None else None),
                "loot_value_total": ("loot_value_total", lambda x: int(float(x)) if x is not None else None),
                "duration_seconds": ("duration_seconds", lambda x: int(x) if x is not None else None),
            }

            for field, (db_field, normalize) in stat_fields.items():
                expected = run.get(db_field)
                if expected is None:
                    continue

                expected_norm = normalize(expected)
                actual = ocr_result.get(field)

                field_results[field]["total"] += 1

                if actual is None:
                    field_results[field]["missing"] += 1
                elif field == "survived":
                    if actual == expected_norm:
                        field_results[field]["correct"] += 1
                    else:
                        field_results[field]["wrong"] += 1
                        print(f"  [{field} WRONG] got={actual} expected={expected_norm}")
                elif field == "duration_seconds":
                    # Allow 10% tolerance for duration
                    if expected_norm and abs(actual - expected_norm) < max(30, expected_norm * 0.1):
                        field_results[field]["correct"] += 1
                    else:
                        field_results[field]["wrong"] += 1
                        print(f"  [{field} WRONG] got={actual} expected={expected_norm}")
                elif field == "loot_value_total":
                    # Allow small tolerance for loot
                    if abs(actual - expected_norm) < 50:
                        field_results[field]["correct"] += 1
                    else:
                        field_results[field]["wrong"] += 1
                        print(f"  [{field} WRONG] got={actual} expected={expected_norm}")
                else:
                    if actual == expected_norm:
                        field_results[field]["correct"] += 1
                    else:
                        field_results[field]["wrong"] += 1
                        print(f"  [{field} WRONG] got={actual} expected={expected_norm}")

        # === Test Grade Calculation ===
        if run.get("grade"):
            alpha_grade = calculate_grade(
                survived=bool(run["survived"]),
                runner_kills=run.get("runner_eliminations") or 0,
                combatant_kills=run.get("combatant_eliminations") or 0,
                loot_value=run.get("loot_value_total") or 0,
                crew_revives=run.get("crew_revives") or 0,
                duration_seconds=run.get("duration_seconds") or 0,
            )
            grade_order = {"S": 6, "A": 5, "B": 4, "C": 3, "D": 2, "F": 1}
            expected_grade = run["grade"].strip().upper()

            field_results["grade"]["total"] += 1
            if alpha_grade == expected_grade:
                field_results["grade"]["correct"] += 1
            elif abs(grade_order.get(alpha_grade, 0) - grade_order.get(expected_grade, 0)) <= 1:
                field_results["grade"]["correct"] += 1  # Count within-1 as correct
            else:
                field_results["grade"]["wrong"] += 1
                print(f"  [grade WRONG] got={alpha_grade} expected={expected_grade}")

    # === Print Summary ===
    print("\n" + "=" * 70)
    print("VALIDATION RESULTS")
    print("=" * 70)
    print(f"\nRuns tested: {run_count}")
    print(f"\n{'Field':<28} {'Correct':>8} {'Wrong':>8} {'Missing':>8} {'Total':>8} {'Accuracy':>10}")
    print("-" * 70)

    total_correct = 0
    total_total = 0

    for field in fields:
        r = field_results[field]
        if r["total"] == 0:
            continue
        acc = r["correct"] / r["total"] * 100 if r["total"] > 0 else 0
        total_correct += r["correct"]
        total_total += r["total"]
        print(f"  {field:<26} {r['correct']:>8} {r['wrong']:>8} {r['missing']:>8} {r['total']:>8} {acc:>9.0f}%")

    if total_total > 0:
        overall = total_correct / total_total * 100
        print("-" * 70)
        print(f"  {'OVERALL':<26} {total_correct:>8} {'':>8} {'':>8} {total_total:>8} {overall:>9.0f}%")

    # === Known Limitations ===
    print("\n--- Known Limitations ---")
    print("  - Single-digit stat values (0-9) undetectable by winocr")
    print("  - Tesseract not installed (would fix single-digit detection)")
    print("  - Coordinate OCR works only when coords are large enough text")
    print("  - Stats crop regions calibrated for trio layout at 3840x2160")


if __name__ == "__main__":
    validate_all()

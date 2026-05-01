"""
Alpha Validation Suite.

Runs the real alpha or hybrid processor end to end against previously captured
runs and compares output to the database/Claude-proven run records. This is the
scorecard for moving alpha from demo to production.

Usage:
    python -m backend.app.alpha.validate
    python -m backend.app.alpha.validate --mode hybrid --limit 20
    python -m backend.app.alpha.validate --json alpha_report.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.app.alpha.data_prep import (
    CLIPS_DIR,
    DB_PATH,
    get_db_runs,
    match_folder_to_run,
)
from backend.app.alpha.health import alpha_health
from backend.app.alpha.hybrid_router import HybridRouter
from backend.app.alpha.processor import AlphaProcessor


TRAINING_STATS_DIR = Path(__file__).resolve().parent / "training_data" / "stats"


@dataclass
class FieldResult:
    correct: int = 0
    wrong: int = 0
    missing: int = 0
    skipped: int = 0

    @property
    def total(self) -> int:
        return self.correct + self.wrong + self.missing

    @property
    def accuracy(self) -> float:
        return (self.correct / self.total * 100.0) if self.total else 0.0


FIELD_ORDER = [
    "map_name",
    "shell_name",
    "survived",
    "kills",
    "combatant_eliminations",
    "runner_eliminations",
    "crew_revives",
    "loot_value_total",
    "duration_seconds",
    "primary_weapon",
    "secondary_weapon",
    "player_gamertag",
    "player_level",
    "vault_value",
    "spawn_coordinates",
    "killed_by",
    "killed_by_weapon",
    "killed_by_damage",
    "damage_contributors",
    "grade",
]

INT_FIELDS = {
    "kills", "combatant_eliminations", "runner_eliminations", "crew_revives",
    "duration_seconds", "player_level", "killed_by_damage",
}
FLOAT_FIELDS = {"loot_value_total", "vault_value"}
STRING_FIELDS = {
    "map_name", "shell_name", "primary_weapon", "secondary_weapon",
    "player_gamertag", "killed_by", "killed_by_weapon", "grade",
}
TRAINING_SCREEN_UNAVAILABLE_FIELDS = {"map_name", "shell_name", "spawn_coordinates"}


def _expected_spawn_coords() -> dict[int, list[float]]:
    if not DB_PATH.exists():
        return {}
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(
            """
            SELECT r.id, sp.game_coord_x, sp.game_coord_y
            FROM runs r
            LEFT JOIN spawn_points sp ON r.spawn_point_id = sp.id
            WHERE sp.game_coord_x IS NOT NULL AND sp.game_coord_y IS NOT NULL
            """
        ).fetchall()
        return {row["id"]: [row["game_coord_x"], row["game_coord_y"]] for row in rows}
    finally:
        db.close()


def _expected_value(run: dict, field: str, spawn_coords: dict[int, list[float]]) -> Any:
    if field == "spawn_coordinates":
        return spawn_coords.get(run["id"])
    return run.get(field)


def _normalize_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return " ".join(text.split()) or None


def _normalize_contributors(value: Any) -> list[dict]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return value if isinstance(value, list) else []


def _compare(field: str, expected: Any, actual: Any) -> tuple[str, str]:
    """Return (status, detail): ok, wrong, missing, or skipped."""
    if expected is None or expected == "":
        return "skipped", "no ground truth"
    if actual is None or actual == "":
        return "missing", f"expected={expected}"

    if field == "survived":
        return ("ok", "") if bool(actual) == bool(expected) else ("wrong", f"got={actual} expected={bool(expected)}")

    if field in INT_FIELDS:
        try:
            got_i = int(actual)
            exp_i = int(expected)
        except (TypeError, ValueError):
            return "wrong", f"got={actual} expected={expected}"
        if field == "duration_seconds":
            tolerance = max(30, int(exp_i * 0.10))
            return ("ok", "") if abs(got_i - exp_i) <= tolerance else ("wrong", f"got={got_i} expected={exp_i}")
        return ("ok", "") if got_i == exp_i else ("wrong", f"got={got_i} expected={exp_i}")

    if field in FLOAT_FIELDS:
        try:
            got_f = float(actual)
            exp_f = float(expected)
        except (TypeError, ValueError):
            return "wrong", f"got={actual} expected={expected}"
        tolerance = 50.0 if field == "loot_value_total" else max(50.0, abs(exp_f) * 0.02)
        return ("ok", "") if abs(got_f - exp_f) <= tolerance else ("wrong", f"got={got_f} expected={exp_f}")

    if field == "spawn_coordinates":
        if not isinstance(actual, list) or len(actual) != 2:
            return "wrong", f"got={actual} expected={expected}"
        try:
            dist = ((float(actual[0]) - float(expected[0])) ** 2 + (float(actual[1]) - float(expected[1])) ** 2) ** 0.5
        except (TypeError, ValueError):
            return "wrong", f"got={actual} expected={expected}"
        return ("ok", "") if dist <= 10.0 else ("wrong", f"got={actual} expected={expected} dist={dist:.1f}")

    if field == "damage_contributors":
        expected_list = _normalize_contributors(expected)
        actual_list = _normalize_contributors(actual)
        if not expected_list:
            return "skipped", "no ground truth"
        if not actual_list:
            return "missing", f"expected={expected}"
        return ("ok", "") if len(actual_list) == len(expected_list) else (
            "wrong", f"got={len(actual_list)} contributors expected={len(expected_list)}"
        )

    if field in STRING_FIELDS:
        got = _normalize_string(actual)
        exp = _normalize_string(expected)
        return ("ok", "") if got == exp else ("wrong", f"got={actual} expected={expected}")

    return ("ok", "") if actual == expected else ("wrong", f"got={actual} expected={expected}")


def _iter_run_folders(limit: int | None = None):
    count = 0
    if not CLIPS_DIR.exists():
        return
    for folder in sorted(CLIPS_DIR.iterdir()):
        if not folder.name.startswith("run_"):
            continue
        ss_dir = folder / "screenshots"
        if not ss_dir.exists():
            continue
        yield folder, ss_dir
        count += 1
        if limit is not None and count >= limit:
            break


def _iter_training_folders():
    if not TRAINING_STATS_DIR.exists():
        return
    for folder in sorted(TRAINING_STATS_DIR.iterdir()):
        if not folder.is_dir():
            continue
        if (folder / "ground_truth.json").exists() or (folder / "damage_ground_truth.json").exists():
            yield folder


def _load_training_truth(folder: Path) -> dict:
    truth = {}
    for name in ("ground_truth.json", "damage_ground_truth.json"):
        path = folder / name
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                truth.update(data)
        except (OSError, json.JSONDecodeError):
            pass
    return truth


def run_validation(mode: str = "alpha", limit: int | None = None, source: str = "all") -> dict:
    runs = get_db_runs()
    spawn_coords = _expected_spawn_coords()
    processor = AlphaProcessor() if mode == "alpha" else HybridRouter(mode=mode)
    field_results = {field: FieldResult() for field in FIELD_ORDER}
    run_reports = []

    def record_result(folder: Path, ss_dir: Path, expected_record: dict, report_source: str) -> None:
        result = processor.process_run(ss_dir, video_path=None)

        misses: list[dict] = []
        for field in FIELD_ORDER:
            if report_source == "training" and field in TRAINING_SCREEN_UNAVAILABLE_FIELDS:
                field_results[field].skipped += 1
                continue
            expected = (
                _expected_value(expected_record, field, spawn_coords)
                if report_source == "appdata"
                else expected_record.get(field)
            )
            actual = result.get(field)
            status, detail = _compare(field, expected, actual)
            bucket = field_results[field]
            if status == "ok":
                bucket.correct += 1
            elif status == "wrong":
                bucket.wrong += 1
                misses.append({"field": field, "detail": detail})
            elif status == "missing":
                bucket.missing += 1
                misses.append({"field": field, "detail": detail})
            else:
                bucket.skipped += 1

        run_reports.append({
            "source": report_source,
            "folder": folder.name,
            "run_id": expected_record.get("id") or expected_record.get("run_id"),
            "routing": result.get("_routing", "alpha"),
            "low_confidence_fields": [
                field for field in result.get("_low_confidence_fields", [])
                if field in expected_record and not (
                    report_source == "training" and field in TRAINING_SCREEN_UNAVAILABLE_FIELDS
                )
            ],
            "claude_fields": result.get("_claude_fields", []),
            "misses": misses,
        })

    if source in ("all", "appdata"):
        for folder, ss_dir in _iter_run_folders(limit):
            if limit is not None and len(run_reports) >= limit:
                break
            run = match_folder_to_run(folder.name, runs)
            if not run:
                continue
            record_result(folder, ss_dir, run, "appdata")

    if source in ("all", "training"):
        for folder in _iter_training_folders():
            if limit is not None and len(run_reports) >= limit:
                break
            truth = _load_training_truth(folder)
            if not truth:
                continue
            record_result(folder, folder, truth, "training")

    summary = {
        field: {
            "correct": r.correct,
            "wrong": r.wrong,
            "missing": r.missing,
            "skipped": r.skipped,
            "total": r.total,
            "accuracy": round(r.accuracy, 1),
        }
        for field, r in field_results.items()
    }
    return {
        "mode": mode,
        "source": source,
        "runs_tested": len(run_reports),
        "alpha_health": alpha_health(),
        "fields": summary,
        "runs": run_reports,
    }


def _print_report(report: dict) -> None:
    print("=" * 82)
    print(
        f"ALPHA VALIDATION SUITE | mode={report['mode']} | "
        f"source={report.get('source', 'all')} | runs={report['runs_tested']}"
    )
    print("=" * 82)
    health = report.get("alpha_health", {})
    blockers = health.get("blockers") or []
    warnings = health.get("warnings") or []
    print(
        f"Capability: {str(health.get('status', 'unknown')).upper()} "
        f"| blockers={len(blockers)} | warnings={len(warnings)}"
    )
    if blockers:
        for item in blockers[:3]:
            print(f"  BLOCKER: {item}")
    if warnings:
        for item in warnings[:3]:
            print(f"  WARN: {item}")
    print("-" * 82)
    print(f"{'Field':<28} {'Correct':>8} {'Wrong':>8} {'Missing':>8} {'Total':>8} {'Accuracy':>10}")
    print("-" * 82)
    total_correct = 0
    total_total = 0
    for field in FIELD_ORDER:
        row = report["fields"][field]
        if row["total"] == 0 and row["skipped"] == 0:
            continue
        total_correct += row["correct"]
        total_total += row["total"]
        print(
            f"{field:<28} {row['correct']:>8} {row['wrong']:>8} "
            f"{row['missing']:>8} {row['total']:>8} {row['accuracy']:>9.1f}%"
        )
    overall = (total_correct / total_total * 100.0) if total_total else 0.0
    print("-" * 82)
    print(f"{'OVERALL':<28} {total_correct:>8} {'':>8} {'':>8} {total_total:>8} {overall:>9.1f}%")

    noisy_runs = [r for r in report["runs"] if r["misses"] or r["low_confidence_fields"]]
    if noisy_runs:
        print("\nRuns needing attention:")
        for run in noisy_runs[:20]:
            miss_fields = ", ".join(m["field"] for m in run["misses"]) or "none"
            low = ", ".join(run["low_confidence_fields"]) or "none"
            print(
                f"  [{run.get('source', '?')}] {run['folder']} #{run['run_id']} "
                f"routing={run['routing']} misses={miss_fields} low={low}"
            )


def validate_all():
    """Backwards-compatible entry point used by older scripts."""
    report = run_validation(mode="alpha")
    _print_report(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["alpha", "hybrid"], default="alpha")
    parser.add_argument("--source", choices=["all", "appdata", "training"], default="all")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", dest="json_path", default=None)
    args = parser.parse_args()

    report = run_validation(mode=args.mode, limit=args.limit, source=args.source)
    _print_report(report)
    if args.json_path:
        out = Path(args.json_path)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nWrote JSON report: {out}")


if __name__ == "__main__":
    main()

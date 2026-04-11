"""
Rule-based grade calculation and template-based summary generation.

Replaces Claude Phase 2 grading and narrative generation with deterministic
formulas and templates. Produces grades S through F based on weighted scoring
of survival, kills, loot, revives, and duration.
"""

import random
import sqlite3
from pathlib import Path

DB_PATH = Path("C:/Users/User/AppData/Roaming/runlog/marathon/data/runlog.db")

# ---------------------------------------------------------------------------
# Weight constants
# ---------------------------------------------------------------------------
WEIGHT_SURVIVAL = 0.35
WEIGHT_RUNNER_KILLS = 0.25
WEIGHT_LOOT = 0.15
WEIGHT_REVIVES = 0.10
WEIGHT_PVE = 0.05
WEIGHT_BASE = 0.10

# ---------------------------------------------------------------------------
# Grade thresholds (cumulative score 0-100)
# ---------------------------------------------------------------------------
GRADE_S = 85
GRADE_A = 70
GRADE_B = 50
GRADE_C = 35
GRADE_D = 20
# Below D -> F


def _score_survival(survived: bool, duration_seconds: float) -> float:
    """0-100 score for survival component."""
    minutes = duration_seconds / 60.0
    if survived:
        # Extracting is great; longer runs score higher
        if minutes >= 15:
            return 100
        if minutes >= 10:
            return 90
        if minutes >= 5:
            return 75
        return 60  # fast extract still counts
    else:
        # Dying: score based on how long you lasted
        if minutes >= 15:
            return 55
        if minutes >= 10:
            return 45
        if minutes >= 5:
            return 30
        if minutes >= 3:
            return 15
        if minutes >= 1:
            return 5
        return 0


def _score_runner_kills(runner_kills: int) -> float:
    """0-100 score for runner eliminations."""
    if runner_kills >= 6:
        return 100
    if runner_kills >= 4:
        return 85
    if runner_kills >= 3:
        return 70
    if runner_kills >= 2:
        return 55
    if runner_kills >= 1:
        return 35
    return 0


def _score_loot(loot_value: float) -> float:
    """0-100 score for loot extracted/collected."""
    if loot_value >= 5000:
        return 100
    if loot_value >= 3000:
        return 85
    if loot_value >= 1500:
        return 65
    if loot_value >= 1000:
        return 50
    if loot_value >= 500:
        return 35
    if loot_value >= 100:
        return 15
    return 0


def _score_revives(crew_revives: int) -> float:
    """0-100 score for teammate revives."""
    if crew_revives >= 4:
        return 100
    if crew_revives >= 3:
        return 80
    if crew_revives >= 2:
        return 60
    if crew_revives >= 1:
        return 40
    return 0


def _score_pve(combatant_kills: int) -> float:
    """0-100 score for PvE combatant eliminations."""
    if combatant_kills >= 30:
        return 100
    if combatant_kills >= 20:
        return 80
    if combatant_kills >= 10:
        return 55
    if combatant_kills >= 5:
        return 35
    if combatant_kills >= 1:
        return 15
    return 0


def calculate_grade(
    survived: bool,
    runner_kills: int,
    combatant_kills: int,
    loot_value: float,
    crew_revives: int,
    duration_seconds: float,
    combat_intensity: float = 0.0,
) -> str:
    """
    Calculate a letter grade (S/A/B/C/D/F) from run stats.

    Uses weighted scoring across survival, runner kills, loot, revives,
    PvE kills, and a base component. Also applies override rules for
    exceptional or terrible runs.

    combat_intensity (0.0-1.0) from audio analysis can bump borderline grades.
    """
    runner_kills = runner_kills or 0
    combatant_kills = combatant_kills or 0
    loot_value = loot_value or 0.0
    crew_revives = crew_revives or 0
    duration_seconds = duration_seconds or 0.0

    minutes = duration_seconds / 60.0

    # --- Override rules (from the Claude prompt thresholds) ---

    # S overrides: exceptional extraction
    if survived and loot_value >= 5000:
        return "S"
    if survived and loot_value >= 3000 and runner_kills >= 1 and minutes >= 10:
        return "S"

    # F override: died almost immediately with nothing
    if not survived and minutes < 1 and runner_kills == 0 and loot_value < 100:
        return "F"

    # D override: died quickly with very little
    if not survived and minutes < 3 and runner_kills <= 1 and loot_value < 500:
        return "D"

    # --- Weighted score calculation ---
    score = (
        _score_survival(survived, duration_seconds) * WEIGHT_SURVIVAL
        + _score_runner_kills(runner_kills) * WEIGHT_RUNNER_KILLS
        + _score_loot(loot_value) * WEIGHT_LOOT
        + _score_revives(crew_revives) * WEIGHT_REVIVES
        + _score_pve(combatant_kills) * WEIGHT_PVE
        + 100 * WEIGHT_BASE  # base is always given
    )

    # Audio combat intensity bonus: up to +5 points for high-action runs
    if combat_intensity > 0.3:
        score += min(combat_intensity * 8, 5.0)

    if score >= GRADE_S:
        return "S"
    if score >= GRADE_A:
        return "A"
    if score >= GRADE_B:
        return "B"
    if score >= GRADE_C:
        return "C"
    if score >= GRADE_D:
        return "D"
    return "F"


# ---------------------------------------------------------------------------
# Summary templates
# ---------------------------------------------------------------------------
# Each key is (grade, survived). Values are lists of template strings.
# Placeholders: {minutes}, {kills}, {runner_kills}, {combatant_kills},
#   {loot}, {revives}, {map}, {shell}, {weapon}, {squad_size}

_TEMPLATES: dict[tuple[str, bool], list[str]] = {
    # S-tier
    ("S", True): [
        "You extracted from {map} with ${loot} in loot and {runner_kills} runner kills across {minutes} min. Dominant performance.",
        "Textbook extraction on {map}. ${loot} secured, {runner_kills} runners eliminated in {minutes} min.",
        "${loot} extracted on {map} with {runner_kills} runner kills. {minutes} min of controlled aggression.",
    ],
    ("S", False): [
        "Eliminated on {map} after {minutes} min, but not before racking up {runner_kills} runner kills and ${loot} in loot. You went down swinging.",
        "{runner_kills} runner kills and ${loot} loot in {minutes} min on {map} before going down. High-impact run despite the elimination.",
    ],
    # A-tier
    ("A", True): [
        "Solid extraction on {map}. ${loot} secured with {runner_kills} runner kills over {minutes} min.",
        "You got out of {map} with ${loot} and {runner_kills} runner kills in {minutes} min. Clean run.",
        "Extracted from {map} after {minutes} min with ${loot} and {kills} total kills. Well played.",
    ],
    ("A", False): [
        "Eliminated on {map} after {minutes} min with {runner_kills} runner kills and ${loot} loot. Strong effort, unlucky finish.",
        "Went down on {map} at {minutes} min. {runner_kills} runner kills and ${loot} loot — the run had legs.",
    ],
    # B-tier
    ("B", True): [
        "You extracted from {map} with ${loot} in {minutes} min. {kills} kills total. Decent haul.",
        "Got out of {map} after {minutes} min. ${loot} extracted, {runner_kills} runner encounters.",
        "Extraction on {map}. ${loot} loot, {minutes} min. Nothing flashy, but you made it out.",
    ],
    ("B", False): [
        "Eliminated on {map} after {minutes} min. {runner_kills} runner kills and ${loot} loot before going down.",
        "Died on {map} at {minutes} min with {runner_kills} runner kills. You put up a fight.",
        "{minutes} min on {map} before elimination. {kills} kills, ${loot} loot. Mid-run wipe.",
    ],
    # C-tier
    ("C", True): [
        "Quick extraction from {map} in {minutes} min. ${loot} loot, {kills} kills. In and out.",
        "You extracted from {map} with ${loot} in {minutes} min. Minimal engagement.",
        "Got out of {map} fast. ${loot}, {runner_kills} runner kills. Low-risk extraction.",
    ],
    ("C", False): [
        "Eliminated on {map} after {minutes} min. ${loot} loot, {kills} kills. Average engagement.",
        "Died on {map} at the {minutes} min mark. {runner_kills} runner kills, ${loot} loot. Unremarkable finish.",
    ],
    # D-tier
    ("D", True): [
        "You extracted from {map} in {minutes} min with ${loot}. Barely anything to show for it.",
        "Quick in-and-out on {map}. ${loot} loot, {kills} kills in {minutes} min. Minimal.",
    ],
    ("D", False): [
        "Eliminated on {map} after just {minutes} min. {kills} kills, ${loot} loot. Short run.",
        "Died early on {map}. {minutes} min, {runner_kills} runner kills, ${loot} loot. Rough start.",
    ],
    # F-tier
    ("F", True): [
        "You extracted from {map} in under a minute with almost nothing. Technically a win.",
    ],
    ("F", False): [
        "Eliminated on {map} in under a minute with nothing to show for it.",
        "Instant wipe on {map}. {minutes} min, no kills, no loot.",
        "Dead on arrival on {map}. {kills} kills, ${loot} loot in {minutes} min.",
    ],
}

# Additional context lines appended based on stats
_KILL_ADDONS = [
    "{runner_kills} of your kills were runners — you were hunting.",
    "Heavy PvP run with {runner_kills} runner eliminations.",
]
_REVIVE_ADDONS = [
    "You also revived teammates {revives} time(s).",
    "{revives} crew revive(s) along the way.",
]
_PVE_ADDONS = [
    "{combatant_kills} combatant kills cleared the path.",
    "Cleared {combatant_kills} combatants during the run.",
]
_SQUAD_ADDONS = [
    "Running with a {squad_size}-person squad.",
]


def generate_summary(stats: dict) -> str:
    """
    Generate a short 1-3 sentence run summary from stats.

    Parameters
    ----------
    stats : dict
        Keys: map_name, survived, kills, runner_eliminations,
        combatant_eliminations, crew_revives, loot_value_total,
        duration_seconds, shell_name, primary_weapon, grade,
        squad_members
    """
    grade = stats.get("grade", "C")
    survived = bool(stats.get("survived", False))
    minutes = round((stats.get("duration_seconds", 0) or 0) / 60.0, 1)
    runner_kills = stats.get("runner_eliminations", 0) or 0
    combatant_kills = stats.get("combatant_eliminations", 0) or 0
    kills = stats.get("kills", 0) or 0
    loot = int(stats.get("loot_value_total", 0) or 0)
    revives = stats.get("crew_revives", 0) or 0
    map_name = stats.get("map_name", "unknown map") or "unknown map"
    shell = stats.get("shell_name", "unknown") or "unknown"
    weapon = stats.get("primary_weapon", "unknown") or "unknown"
    squad_members = stats.get("squad_members") or []
    squad_size = len(squad_members) + 1 if squad_members else 1

    fmt = dict(
        minutes=minutes,
        kills=kills,
        runner_kills=runner_kills,
        combatant_kills=combatant_kills,
        loot=f"{loot:,}",
        revives=revives,
        map=map_name,
        shell=shell,
        weapon=weapon,
        squad_size=squad_size,
    )

    # Pick base template
    key = (grade, survived)
    templates = _TEMPLATES.get(key, _TEMPLATES.get(("C", survived), ["Run on {map}. {kills} kills, ${loot} loot."]))
    base = random.choice(templates).format(**fmt)

    # Optionally add context (keep it to 1 extra sentence max)
    addon = ""
    if runner_kills >= 3 and not survived:
        addon = random.choice(_KILL_ADDONS).format(**fmt)
    elif revives >= 2:
        addon = random.choice(_REVIVE_ADDONS).format(**fmt)
    elif combatant_kills >= 15 and runner_kills == 0:
        addon = random.choice(_PVE_ADDONS).format(**fmt)
    elif squad_size >= 3:
        addon = random.choice(_SQUAD_ADDONS).format(**fmt)

    if addon:
        return f"{base} {addon}"
    return base


# ---------------------------------------------------------------------------
# Validation against existing DB grades
# ---------------------------------------------------------------------------

def validate_against_db() -> None:
    """
    Load graded runs from the DB, recalculate grades with the rule-based
    formula, and print a comparison against Claude's original grades.
    """
    if not DB_PATH.exists():
        print(f"Database not found at {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Discover available columns so we handle schema variations gracefully
    col_info = cursor.execute("PRAGMA table_info(runs)").fetchall()
    col_names = {row["name"] for row in col_info}

    # Build SELECT dynamically based on available columns
    select_cols = ["r.id", "r.grade"]
    select_cols.append("r.survived" if "survived" in col_names else "0 as survived")
    select_cols.append("r.runner_eliminations" if "runner_eliminations" in col_names else "0 as runner_eliminations")
    select_cols.append("r.combatant_eliminations" if "combatant_eliminations" in col_names else "0 as combatant_eliminations")
    select_cols.append("r.loot_value_total" if "loot_value_total" in col_names else "0 as loot_value_total")
    select_cols.append("r.crew_revives" if "crew_revives" in col_names else "0 as crew_revives")
    select_cols.append("r.duration_seconds" if "duration_seconds" in col_names else "0 as duration_seconds")
    select_cols.append("r.kills" if "kills" in col_names else "0 as kills")

    # Check if runners table exists for shell_name
    tables = {row[0] for row in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "runners" in tables:
        join_clause = "LEFT JOIN runners rn ON r.runner_id = rn.id"
        select_cols.append("rn.name as shell_name")
    else:
        join_clause = ""
        select_cols.append("NULL as shell_name")

    query = f"""
        SELECT {', '.join(select_cols)}
        FROM runs r
        {join_clause}
        WHERE r.grade IS NOT NULL AND r.grade != ''
        ORDER BY r.id DESC
        LIMIT 30
    """

    rows = cursor.execute(query).fetchall()
    conn.close()

    if not rows:
        print("No graded runs found in the database.")
        return

    # Grade ordering for distance calculation
    grade_order = {"S": 6, "A": 5, "B": 4, "C": 3, "D": 2, "F": 1}

    exact = 0
    within_one = 0
    total = len(rows)
    mismatches: list[str] = []

    print(f"\n{'ID':>5}  {'Claude':>6}  {'Rule':>6}  {'Match':>7}  Stats")
    print("-" * 80)

    for row in rows:
        claude_grade = row["grade"].strip().upper() if row["grade"] else "?"
        survived = bool(row["survived"])
        runner_kills = row["runner_eliminations"] or 0
        combatant_kills = row["combatant_eliminations"] or 0
        loot_value = row["loot_value_total"] or 0
        crew_revives = row["crew_revives"] or 0
        duration = row["duration_seconds"] or 0

        rule_grade = calculate_grade(
            survived=survived,
            runner_kills=runner_kills,
            combatant_kills=combatant_kills,
            loot_value=loot_value,
            crew_revives=crew_revives,
            duration_seconds=duration,
        )

        match = "EXACT" if claude_grade == rule_grade else ""
        if claude_grade == rule_grade:
            exact += 1

        c_ord = grade_order.get(claude_grade, 0)
        r_ord = grade_order.get(rule_grade, 0)
        if abs(c_ord - r_ord) <= 1:
            within_one += 1
            if not match:
                match = "~1"
        else:
            match = f"OFF {abs(c_ord - r_ord)}"
            mismatches.append(
                f"  Run {row['id']}: Claude={claude_grade} Rule={rule_grade} "
                f"(surv={survived} rkills={runner_kills} loot=${loot_value} "
                f"dur={round(duration/60, 1)}m)"
            )

        minutes = round(duration / 60.0, 1)
        stats_str = (
            f"surv={survived} rkills={runner_kills} ckills={combatant_kills} "
            f"loot=${loot_value} rev={crew_revives} dur={minutes}m"
        )
        print(f"{row['id']:>5}  {claude_grade:>6}  {rule_grade:>6}  {match:>7}  {stats_str}")

    print("-" * 80)
    print(f"Total: {total}  |  Exact match: {exact} ({exact/total*100:.0f}%)  |  Within 1 grade: {within_one} ({within_one/total*100:.0f}%)")

    if mismatches:
        print(f"\nLargest mismatches ({len(mismatches)}):")
        for m in mismatches:
            print(m)


if __name__ == "__main__":
    validate_against_db()

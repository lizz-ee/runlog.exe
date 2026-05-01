"""
Alpha vocabularies and fuzzy normalization.

Alpha OCR should prefer known game/app values when the OCR text is close enough.
Weapon names are loaded from the user's local database where possible, so this
keeps improving as Claude/hybrid-confirmed runs accumulate.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path


MAP_NAMES = ["Perimeter", "Outpost", "Dire Marsh", "Cryo Archive"]
SHELL_NAMES = ["assassin", "destroyer", "recon", "rook", "thief", "triage", "vandal"]

# Seed list only. DB values and previously parsed runs are appended at runtime.
WEAPON_NAME_SEEDS = [
    "Blackbird",
    "BR33 Volley Rifle",
    "Bounty",
    "Brute",
    "Bully SMG",
    "Cavalier",
    "Cyclone",
    "Ferrous",
    "Gambit",
    "Hardline",
    "Hardline PR",
    "Hound",
    "Kodiak",
    "Lancer",
    "M77 Assault Rifle",
    "Maverick",
    "Mercury",
    "Mongrel",
    "MSTR Combat Shotgun",
    "Overwatch",
    "Overrun AR",
    "Paragon",
    "Peregrine",
    "Repeater HPR",
    "Retaliator LMG",
    "Reprisal",
    "Ricochet",
    "Rook",
    "Ruin",
    "Scorpion",
    "Tempest",
    "Traxus",
    "Stryder M1T",
    "V22 Volt Thrower",
    "V86 Lookout",
    "Valkyrie",
]


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def best_match(value: str | None, choices: list[str], min_score: float = 0.78) -> tuple[str | None, float]:
    if not value:
        return None, 0.0
    value_key = _key(value)
    if not value_key:
        return None, 0.0

    best_value = None
    best_score = 0.0
    for choice in choices:
        choice_key = _key(choice)
        if not choice_key:
            continue
        if value_key == choice_key:
            return choice, 1.0
        score = SequenceMatcher(None, value_key, choice_key).ratio()
        if value_key in choice_key or choice_key in value_key:
            score = max(score, 0.86)
        if score > best_score:
            best_score = score
            best_value = choice

    if best_score >= min_score:
        return best_value, round(best_score, 3)
    return None, round(best_score, 3)


def normalize_map_name(value: str | None) -> tuple[str | None, float]:
    return best_match(value, MAP_NAMES, min_score=0.70)


def normalize_shell_name(value: str | None) -> tuple[str | None, float]:
    matched, score = best_match(value, SHELL_NAMES, min_score=0.72)
    return (matched.lower(), score) if matched else (None, score)


@lru_cache(maxsize=1)
def load_weapon_vocabulary() -> tuple[str, ...]:
    names: set[str] = set(WEAPON_NAME_SEEDS)
    try:
        training_stats = Path(__file__).resolve().parent / "training_data" / "stats"
        for path in training_stats.glob("*/ground_truth.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            for key in ("primary_weapon", "secondary_weapon", "killed_by_weapon"):
                value = data.get(key)
                if value:
                    names.add(str(value))
    except Exception:
        pass
    try:
        from backend.app.database import SessionLocal
        from backend.app.models import Run, Weapon

        db = SessionLocal()
        try:
            for (name,) in db.query(Weapon.name).filter(Weapon.name.isnot(None)).all():
                if name:
                    names.add(str(name))
            rows = db.query(Run.primary_weapon, Run.secondary_weapon, Run.killed_by_weapon).all()
            for row in rows:
                for name in row:
                    if name:
                        names.add(str(name))
        finally:
            db.close()
    except Exception:
        pass
    return tuple(sorted(names, key=lambda s: s.lower()))


def normalize_weapon_name(value: str | None, min_score: float = 0.80) -> tuple[str | None, float]:
    return best_match(value, list(load_weapon_vocabulary()), min_score=min_score)

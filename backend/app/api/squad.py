from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Run
from ..utils import calc_kd, calc_survival_rate

router = APIRouter()


@router.get("/stats")
def get_squad_stats(limit: int = Query(7, ge=1, le=7), db: Session = Depends(get_db)):
    """Top squad mates by runs together, with per-mate stats."""
    runs = db.query(Run).all()
    if not runs:
        return []

    # Get the MOST COMMON player gamertag as self (avoids misidentified squad mates)
    from sqlalchemy import func
    most_common = db.query(Run.player_gamertag, func.count(Run.player_gamertag).label('cnt')) \
        .filter(Run.player_gamertag.isnot(None)) \
        .group_by(Run.player_gamertag).order_by(func.count(Run.player_gamertag).desc()).first()
    if most_common:
        base_self = most_common[0].split('#')[0].lower()
        self_tags = {base_self, most_common[0].lower()}
    else:
        self_tags = set()

    # Aggregate stats per squad mate (normalize gamertags — strip #tag for grouping)
    mates: dict[str, dict] = {}
    for r in runs:
        if not r.squad_members or not isinstance(r.squad_members, list):
            continue
        for name in r.squad_members:
            if not name:
                continue
            base_name = name.split('#')[0].lower()
            if base_name in self_tags or name.lower() in self_tags:
                continue
            # Group by base name (before #) so "AmazighRais" and "AmazighRais#0781" merge
            key = base_name
            if key not in mates:
                mates[key] = {
                    "gamertag": name,  # keep the most detailed version
                    "runs": 0, "survived": 0,
                    "pve_kills": 0, "pvp_kills": 0, "deaths": 0, "revives": 0,
                    "loot": 0, "time": 0,
                }
            # Update gamertag to the version with # tag if available
            if '#' in name and '#' not in mates[key]["gamertag"]:
                mates[key]["gamertag"] = name
            m = mates[key]
            m["runs"] += 1
            m["survived"] += 1 if r.survived else 0
            m["pve_kills"] += r.combatant_eliminations or 0
            m["pvp_kills"] += r.runner_eliminations or 0
            m["deaths"] += r.deaths or 0
            m["revives"] += r.crew_revives or 0
            m["loot"] += r.loot_value_total or 0
            m["time"] += r.duration_seconds or 0

    # Calculate derived stats
    total_runs = len(runs)
    total_survived = sum(1 for r in runs if r.survived)
    overall_survival = calc_survival_rate(total_survived, total_runs)

    for m in mates.values():
        m["survival_rate"] = calc_survival_rate(m["survived"], m["runs"])
        m["survival_diff"] = round(m["survival_rate"] - overall_survival, 1)
        total_kills = m["pve_kills"] + m["pvp_kills"]
        m["kills"] = total_kills
        m["kd"] = calc_kd(m["pvp_kills"], m["deaths"])
        m["avg_loot"] = round(m["loot"] / m["runs"]) if m["runs"] else 0
        m["avg_kills"] = round(total_kills / m["runs"], 1) if m["runs"] else 0
        m["avg_time"] = round(m["time"] / m["runs"]) if m["runs"] else 0

    # Weighted score: runs * (20% frequency + 50% survival + 30% loot)
    # Survival dominates, loot is critical (extraction shooter), frequency rewards loyalty
    for m in mates.values():
        surv_factor = m["survival_rate"] / 100  # 0.0 to 1.0
        loot_factor = min(m["avg_loot"] / 5000, 1.0) if m["avg_loot"] > 0 else 0  # caps at $5k
        m["score"] = round(m["runs"] * (0.20 + 0.50 * surv_factor + 0.30 * loot_factor), 2)

    sorted_mates = sorted(mates.values(), key=lambda x: x["score"], reverse=True)
    return sorted_mates[:limit]

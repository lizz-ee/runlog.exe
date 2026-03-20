from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Run

router = APIRouter()


@router.get("/stats")
def get_squad_stats(limit: int = Query(7, ge=1, le=7), db: Session = Depends(get_db)):
    """Top squad mates by runs together, with per-mate stats."""
    runs = db.query(Run).all()
    if not runs:
        return []

    # Get all known player gamertags to exclude self
    self_tags = {
        tag.lower() for (tag,) in
        db.query(Run.player_gamertag).filter(Run.player_gamertag.isnot(None)).distinct().all()
    }

    # Aggregate stats per squad mate
    mates: dict[str, dict] = {}
    for r in runs:
        if not r.squad_members or not isinstance(r.squad_members, list):
            continue
        for name in r.squad_members:
            if not name or name.lower() in self_tags:
                continue
            if name not in mates:
                mates[name] = {
                    "gamertag": name,
                    "runs": 0, "survived": 0,
                    "pve_kills": 0, "pvp_kills": 0, "deaths": 0, "revives": 0,
                    "loot": 0, "time": 0,
                }
            m = mates[name]
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
    overall_survival = round(total_survived / total_runs * 100, 1) if total_runs else 0

    for m in mates.values():
        m["survival_rate"] = round(m["survived"] / m["runs"] * 100, 1) if m["runs"] else 0
        m["survival_diff"] = round(m["survival_rate"] - overall_survival, 1)
        total_kills = m["pve_kills"] + m["pvp_kills"]
        m["kills"] = total_kills
        m["kd"] = round(m["pvp_kills"] / m["deaths"], 2) if m["deaths"] else float(m["pvp_kills"])
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

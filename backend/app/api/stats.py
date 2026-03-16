from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import Run, Runner
from ..schemas import OverviewStats

router = APIRouter()


@router.get("/overview", response_model=OverviewStats)
def get_overview_stats(db: Session = Depends(get_db)):
    runs = db.query(Run).all()
    if not runs:
        return OverviewStats()

    total = len(runs)
    survived = sum(1 for r in runs if r.survived)
    pve_kills = sum(r.combatant_eliminations or 0 for r in runs)
    pvp_kills = sum(r.runner_eliminations or 0 for r in runs)
    kills = pve_kills + pvp_kills
    deaths = sum(r.deaths or 0 for r in runs)
    assists = sum(r.assists or 0 for r in runs)
    loot = sum(r.loot_value_total or 0 for r in runs)

    # K/D is Runner K/D (PvP only) — PvE kills don't count for K/D
    kd = round(pvp_kills / deaths, 2) if deaths else float(pvp_kills)

    # Favorite map
    map_counts: dict[str, int] = {}
    for r in runs:
        if r.map_name:
            map_counts[r.map_name] = map_counts.get(r.map_name, 0) + 1
    fav_map = max(map_counts, key=map_counts.get) if map_counts else None

    # Favorite runner
    runner_counts: dict[int, int] = {}
    for r in runs:
        if r.runner_id:
            runner_counts[r.runner_id] = runner_counts.get(r.runner_id, 0) + 1
    fav_runner_name = None
    if runner_counts:
        fav_id = max(runner_counts, key=runner_counts.get)
        fav_runner = db.query(Runner).filter(Runner.id == fav_id).first()
        fav_runner_name = fav_runner.name if fav_runner else None

    return OverviewStats(
        total_runs=total,
        total_survived=survived,
        survival_rate=round(survived / total * 100, 1) if total else 0,
        total_kills=kills,
        total_deaths=deaths,
        total_assists=assists,
        kd_ratio=kd,
        total_loot_value=round(loot, 2),
        avg_kills_per_run=round(kills / total, 1) if total else 0,
        avg_loot_per_run=round(loot / total, 1) if total else 0,
        favorite_map=fav_map,
        favorite_runner=fav_runner_name,
    )


@router.get("/by-map")
def stats_by_map(db: Session = Depends(get_db)):
    runs = db.query(Run).filter(Run.map_name.isnot(None)).all()
    maps: dict[str, dict] = {}
    for r in runs:
        if r.map_name not in maps:
            maps[r.map_name] = {"map": r.map_name, "runs": 0, "survived": 0, "kills": 0, "deaths": 0, "loot": 0}
        m = maps[r.map_name]
        m["runs"] += 1
        m["survived"] += 1 if r.survived else 0
        m["kills"] += r.kills or 0
        m["deaths"] += r.deaths or 0
        m["loot"] += r.loot_value_total or 0
    for m in maps.values():
        m["survival_rate"] = round(m["survived"] / m["runs"] * 100, 1) if m["runs"] else 0
        m["kd"] = round(m["kills"] / m["deaths"], 2) if m["deaths"] else float(m["kills"])
    return list(maps.values())


@router.get("/by-runner")
def stats_by_runner(db: Session = Depends(get_db)):
    runs = db.query(Run).filter(Run.runner_id.isnot(None)).all()
    runners: dict[int, dict] = {}
    for r in runs:
        if r.runner_id not in runners:
            runner = db.query(Runner).filter(Runner.id == r.runner_id).first()
            runners[r.runner_id] = {
                "runner_id": r.runner_id,
                "runner_name": runner.name if runner else "Unknown",
                "runs": 0, "survived": 0, "kills": 0, "deaths": 0, "loot": 0,
            }
        s = runners[r.runner_id]
        s["runs"] += 1
        s["survived"] += 1 if r.survived else 0
        s["kills"] += r.kills or 0
        s["deaths"] += r.deaths or 0
        s["loot"] += r.loot_value_total or 0
    for s in runners.values():
        s["survival_rate"] = round(s["survived"] / s["runs"] * 100, 1) if s["runs"] else 0
        s["kd"] = round(s["kills"] / s["deaths"], 2) if s["deaths"] else float(s["kills"])
    return list(runners.values())


@router.get("/trends")
def stats_trends(db: Session = Depends(get_db)):
    """Daily aggregated stats for trend charts."""
    runs = db.query(Run).order_by(Run.date).all()
    days: dict[str, dict] = {}
    for r in runs:
        day = r.date.strftime("%Y-%m-%d") if r.date else "unknown"
        if day not in days:
            days[day] = {"date": day, "runs": 0, "survived": 0, "kills": 0, "deaths": 0, "loot": 0}
        d = days[day]
        d["runs"] += 1
        d["survived"] += 1 if r.survived else 0
        d["kills"] += r.kills or 0
        d["deaths"] += r.deaths or 0
        d["loot"] += r.loot_value_total or 0
    return list(days.values())

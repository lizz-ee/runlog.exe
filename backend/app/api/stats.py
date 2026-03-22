from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db
from ..models import Run, Runner
from ..schemas import OverviewStats, MapTime
from ..utils import calc_kd, calc_survival_rate

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
    revives = sum(r.crew_revives or 0 for r in runs)
    loot = sum(r.loot_value_total or 0 for r in runs)

    # K/D is Runner K/D (PvP only) — PvE kills don't count for K/D
    kd = calc_kd(pvp_kills, deaths)

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

    # Favorite weapon
    weapon_counts: dict[str, int] = {}
    for r in runs:
        if r.primary_weapon:
            weapon_counts[r.primary_weapon] = weapon_counts.get(r.primary_weapon, 0) + 1
    fav_weapon = max(weapon_counts, key=weapon_counts.get) if weapon_counts else None

    # Favorite squad mate — count how often each name appears in squad_members
    # Exclude the local player's own gamertags (pulled live from DB, supports multiple profiles)
    self_tags = {
        tag.lower() for (tag,) in
        db.query(Run.player_gamertag).filter(Run.player_gamertag.isnot(None)).distinct().all()
    }
    mate_counts: dict[str, int] = {}
    for r in runs:
        if r.squad_members:
            members = r.squad_members if isinstance(r.squad_members, list) else []
            for name in members:
                if name and name.lower() not in self_tags:
                    mate_counts[name] = mate_counts.get(name, 0) + 1
    fav_mate = max(mate_counts, key=mate_counts.get) if mate_counts else None
    fav_mate_runs = mate_counts.get(fav_mate, 0) if fav_mate else 0

    # Time tracking
    total_time = sum(r.duration_seconds or 0 for r in runs)
    map_time: dict[str, int] = {}
    for r in runs:
        if r.map_name and r.duration_seconds:
            map_time[r.map_name] = map_time.get(r.map_name, 0) + r.duration_seconds
    time_by_map = [MapTime(map_name=k, total_seconds=v) for k, v in sorted(map_time.items(), key=lambda x: x[1], reverse=True)]

    return OverviewStats(
        total_runs=total,
        total_survived=survived,
        survival_rate=calc_survival_rate(survived, total),
        total_kills=kills,
        total_deaths=deaths,
        total_assists=assists,
        total_revives=revives,
        kd_ratio=kd,
        total_loot_value=round(loot, 2),
        avg_kills_per_run=round(kills / total, 1) if total else 0,
        avg_loot_per_run=round(loot / total, 1) if total else 0,
        favorite_map=fav_map,
        favorite_runner=fav_runner_name,
        favorite_shell=fav_runner_name,
        favorite_weapon=fav_weapon,
        favorite_squad_mate=fav_mate,
        favorite_squad_mate_runs=fav_mate_runs,
        total_time_seconds=total_time,
        time_by_map=time_by_map,
    )


@router.get("/by-map")
def stats_by_map(db: Session = Depends(get_db)):
    runs = db.query(Run).filter(Run.map_name.isnot(None)).all()
    maps: dict[str, dict] = {}
    for r in runs:
        if r.map_name not in maps:
            maps[r.map_name] = {
                "map": r.map_name, "runs": 0, "survived": 0,
                "pve_kills": 0, "pvp_kills": 0, "deaths": 0,
                "loot": 0, "time": 0,
            }
        m = maps[r.map_name]
        m["runs"] += 1
        m["survived"] += 1 if r.survived else 0
        m["pve_kills"] += r.combatant_eliminations or 0
        m["pvp_kills"] += r.runner_eliminations or 0
        m["deaths"] += r.deaths or 0
        m["loot"] += r.loot_value_total or 0
        m["time"] += r.duration_seconds or 0
    for m in maps.values():
        m["survival_rate"] = calc_survival_rate(m["survived"], m["runs"])
        total_kills = m["pve_kills"] + m["pvp_kills"]
        m["kills"] = total_kills
        m["kd"] = calc_kd(m["pvp_kills"], m["deaths"])
        m["avg_loot"] = round(m["loot"] / m["runs"], 0) if m["runs"] else 0
        m["avg_time"] = round(m["time"] / m["runs"]) if m["runs"] else 0
    return list(maps.values())


@router.get("/by-runner")
def stats_by_runner(db: Session = Depends(get_db)):
    runs = db.query(Run).filter(Run.runner_id.isnot(None)).all()
    # Pre-fetch all runners to avoid N+1 queries
    all_runners = {r.id: r.name for r in db.query(Runner).all()}
    runners: dict[int, dict] = {}
    for r in runs:
        if r.runner_id not in runners:
            runners[r.runner_id] = {
                "runner_id": r.runner_id,
                "runner_name": all_runners.get(r.runner_id, "Unknown"),
                "runs": 0, "survived": 0, "kills": 0, "deaths": 0, "loot": 0,
                "pve_kills": 0, "pvp_kills": 0, "revives": 0, "time": 0,
                "weapon_counts": {},
            }
        s = runners[r.runner_id]
        s["runs"] += 1
        s["survived"] += 1 if r.survived else 0
        s["kills"] += r.kills or 0
        s["pve_kills"] += r.combatant_eliminations or 0
        s["pvp_kills"] += r.runner_eliminations or 0
        s["deaths"] += r.deaths or 0
        s["revives"] += r.crew_revives or 0
        s["loot"] += r.loot_value_total or 0
        s["time"] += r.duration_seconds or 0
        if r.primary_weapon:
            s["weapon_counts"][r.primary_weapon] = s["weapon_counts"].get(r.primary_weapon, 0) + 1
    for s in runners.values():
        s["survival_rate"] = calc_survival_rate(s["survived"], s["runs"])
        s["kd"] = calc_kd(s["pvp_kills"], s["deaths"])
        s["avg_loot"] = round(s["loot"] / s["runs"]) if s["runs"] else 0
        s["avg_time"] = round(s["time"] / s["runs"]) if s["runs"] else 0
        wc = s.pop("weapon_counts")
        s["favorite_weapon"] = max(wc, key=wc.get) if wc else None

    # Weighted performance score: 10% base + 35% survival + 25% rkills + 5% pve + 10% revives + 15% loot
    for s in runners.values():
        surv_factor = s["survival_rate"] / 100
        rkill_factor = min((s["pvp_kills"] / s["runs"]) / 5, 1.0) if s["runs"] else 0  # cap at 5 kills/run
        pve_factor = min((s["pve_kills"] / s["runs"]) / 10, 1.0) if s["runs"] else 0  # cap at 10 kills/run
        revive_factor = min((s["revives"] / s["runs"]) / 3, 1.0) if s["runs"] else 0  # cap at 3 revives/run
        loot_factor = min(s["avg_loot"] / 5000, 1.0) if s["avg_loot"] > 0 else 0  # cap at $5k
        s["score"] = round(s["runs"] * (0.10 + 0.35 * surv_factor + 0.25 * rkill_factor + 0.05 * pve_factor + 0.10 * revive_factor + 0.15 * loot_factor), 2)

    return sorted(runners.values(), key=lambda x: x["score"], reverse=True)


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

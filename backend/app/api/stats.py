from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, Integer

from ..database import get_db
from ..models import Run, Runner
from ..schemas import OverviewStats, MapTime
from ..utils import calc_kd, calc_survival_rate

router = APIRouter()


@router.get("/overview", response_model=OverviewStats)
def get_overview_stats(db: Session = Depends(get_db)):
    # Single aggregation query instead of loading all runs into Python
    agg = db.query(
        func.count(Run.id).label("total"),
        func.sum(func.cast(Run.survived == True, Integer)).label("survived"),
        func.coalesce(func.sum(Run.combatant_eliminations), 0).label("pve_kills"),
        func.coalesce(func.sum(Run.runner_eliminations), 0).label("pvp_kills"),
        func.coalesce(func.sum(Run.deaths), 0).label("deaths"),
        func.coalesce(func.sum(Run.assists), 0).label("assists"),
        func.coalesce(func.sum(Run.crew_revives), 0).label("revives"),
        func.coalesce(func.sum(Run.loot_value_total), 0).label("loot"),
        func.coalesce(func.sum(Run.duration_seconds), 0).label("total_time"),
    ).first()

    total = agg.total or 0
    if total == 0:
        return OverviewStats()

    survived = agg.survived or 0
    pve_kills = agg.pve_kills
    pvp_kills = agg.pvp_kills
    kills = pve_kills + pvp_kills
    deaths = agg.deaths
    assists = agg.assists
    revives = agg.revives
    loot = agg.loot
    total_time = agg.total_time
    kd = calc_kd(pvp_kills, deaths)

    # Favorite map — single GROUP BY query
    fav_map_row = db.query(Run.map_name, func.count(Run.id).label("cnt")).filter(
        Run.map_name.isnot(None)
    ).group_by(Run.map_name).order_by(desc("cnt")).first()
    fav_map = fav_map_row[0] if fav_map_row else None

    # Favorite runner — single GROUP BY + join
    fav_runner_row = db.query(Runner.name, func.count(Run.id).label("cnt")).join(
        Runner, Run.runner_id == Runner.id
    ).group_by(Run.runner_id).order_by(desc("cnt")).first()
    fav_runner_name = fav_runner_row[0] if fav_runner_row else None

    # Favorite weapon — single GROUP BY query
    fav_weapon_row = db.query(Run.primary_weapon, func.count(Run.id).label("cnt")).filter(
        Run.primary_weapon.isnot(None)
    ).group_by(Run.primary_weapon).order_by(desc("cnt")).first()
    fav_weapon = fav_weapon_row[0] if fav_weapon_row else None

    # Favorite squad mate — group by base name (before #tag) so "Pyruuz" and "Pyruuz#7903" merge
    self_tag_rows = db.query(Run.player_gamertag).filter(Run.player_gamertag.isnot(None)).distinct().all()
    self_bases = {tag.split('#')[0].lower() for (tag,) in self_tag_rows}
    mate_rows = db.query(Run.squad_members).filter(Run.squad_members.isnot(None)).all()
    mate_counts: dict[str, int] = {}       # base_name -> count
    mate_display: dict[str, str] = {}      # base_name -> best display name (with #tag if seen)
    for (members,) in mate_rows:
        if not isinstance(members, list):
            continue
        for name in members:
            if not name:
                continue
            base = name.split('#')[0].lower()
            if base in self_bases:
                continue
            mate_counts[base] = mate_counts.get(base, 0) + 1
            if base not in mate_display or ('#' in name and '#' not in mate_display[base]):
                mate_display[base] = name
    fav_base = max(mate_counts, key=mate_counts.get) if mate_counts else None
    fav_mate = mate_display.get(fav_base) if fav_base else None
    fav_mate_runs = mate_counts.get(fav_base, 0) if fav_base else 0

    # Time by map — single GROUP BY query
    map_time_rows = db.query(
        Run.map_name, func.sum(Run.duration_seconds).label("total_s")
    ).filter(Run.map_name.isnot(None), Run.duration_seconds.isnot(None)).group_by(
        Run.map_name
    ).order_by(desc("total_s")).all()
    time_by_map = [MapTime(map_name=r[0], total_seconds=r[1] or 0) for r in map_time_rows]

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
    from sqlalchemy.orm import load_only
    runs = db.query(Run).options(load_only(
        Run.map_name, Run.survived, Run.combatant_eliminations, Run.runner_eliminations,
        Run.deaths, Run.loot_value_total, Run.duration_seconds,
    )).filter(Run.map_name.isnot(None)).all()
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
    from sqlalchemy.orm import load_only
    runs = db.query(Run).options(load_only(
        Run.runner_id, Run.survived, Run.kills, Run.combatant_eliminations, Run.runner_eliminations,
        Run.deaths, Run.crew_revives, Run.loot_value_total, Run.duration_seconds, Run.primary_weapon,
    )).filter(Run.runner_id.isnot(None)).all()
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
def stats_trends(days_back: int = 0, db: Session = Depends(get_db)):
    """Daily aggregated stats for trend charts. Optional days_back filter (0 = all)."""
    from sqlalchemy.orm import load_only
    q = db.query(Run).options(
        load_only(Run.date, Run.survived, Run.kills, Run.deaths, Run.loot_value_total)
    )
    if days_back > 0:
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        q = q.filter(Run.date >= cutoff)
    runs = q.order_by(Run.date).all()
    days_map: dict[str, dict] = {}
    for r in runs:
        day = r.date.strftime("%Y-%m-%d") if r.date else "unknown"
        if day not in days_map:
            days_map[day] = {"date": day, "runs": 0, "survived": 0, "kills": 0, "deaths": 0, "loot": 0}
        d = days_map[day]
        d["runs"] += 1
        d["survived"] += 1 if r.survived else 0
        d["kills"] += r.kills or 0
        d["deaths"] += r.deaths or 0
        d["loot"] += r.loot_value_total or 0
    return list(days_map.values())

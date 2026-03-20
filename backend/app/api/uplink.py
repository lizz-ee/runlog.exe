"""
UPLINK — AI tactical advisor for Marathon gameplay.

Provides:
- Session summary stats (pure DB)
- Performance trend data (pure DB)
- AI-generated briefings (Haiku)
- Interactive chat with tool access (Haiku)
"""

import json
import os
import subprocess
import shutil
from datetime import datetime, timedelta
from typing import Generator

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..database import get_db, SessionLocal
from ..models import Run, Runner, SpawnPoint, Session as SessionModel
from ..config import settings

router = APIRouter()

# ── Session code formatter ──────────────────────────────────────
def format_session_code(session_index: int) -> str:
    """Convert a 1-based session index to :NNA: format.

    :01A: through :99A: (1-99)
    :01B: through :99B: (100-198)
    ...
    :01Z: through :99Z: (2475-2574)
    :01AA: through :99AA: (2575+)
    """
    if session_index <= 0:
        return ":??:"
    idx = session_index - 1  # 0-based

    if idx < 26 * 99:
        # Single letter suffix: A-Z
        letter_idx = idx // 99
        num = (idx % 99) + 1
        return f":{num:02d}{chr(65 + letter_idx)}:"
    else:
        # Double letter suffix: AA, AB, etc.
        remaining = idx - (26 * 99)
        first = remaining // (99 * 26)
        second = (remaining // 99) % 26
        num = (remaining % 99) + 1
        return f":{num:02d}{chr(65 + first)}{chr(65 + second)}:"


def get_session_index(db: Session, session_id: int) -> int:
    """Get the 1-based index of a session among sessions that have runs."""
    sessions_with_runs = db.query(SessionModel.id).join(
        Run, Run.session_id == SessionModel.id
    ).distinct().order_by(SessionModel.id.asc()).all()
    for i, (sid,) in enumerate(sessions_with_runs):
        if sid == session_id:
            return i + 1
    return 0


# ── Briefing cache ──────────────────────────────────────────────
_briefing_cache = {"session_id": None, "run_count": 0, "text": None}


# ═══════════════════════════════════════════════════════════════
# TOOL FUNCTIONS — read-only DB queries the AI can call
# ═══════════════════════════════════════════════════════════════

def tool_get_overview_stats(db: Session, **kwargs) -> dict:
    """Career-wide stats summary."""
    runs = db.query(Run).all()
    total = len(runs)
    if total == 0:
        return {"total_runs": 0, "message": "No runs recorded yet."}
    survived = sum(1 for r in runs if r.survived)
    pve = sum(r.combatant_eliminations or 0 for r in runs)
    pvp = sum(r.runner_eliminations or 0 for r in runs)
    deaths = sum(r.deaths or 0 for r in runs)
    loot = sum(r.loot_value_total or 0 for r in runs)
    time_s = sum(r.duration_seconds or 0 for r in runs)
    return {
        "total_runs": total,
        "survival_rate": round(survived / total * 100, 1),
        "total_runner_kills": pvp,
        "total_pve_kills": pve,
        "kd_ratio": round(pvp / deaths, 2) if deaths else float(pvp),
        "total_loot": round(loot),
        "total_time_minutes": round(time_s / 60),
        "avg_loot_per_run": round(loot / total),
        "avg_kills_per_run": round((pve + pvp) / total, 1),
    }


def tool_get_session_summary(db: Session, session_id: int = None, **kwargs) -> dict:
    """Stats for a specific session (defaults to latest)."""
    if session_id:
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    else:
        session = db.query(SessionModel).order_by(SessionModel.id.desc()).first()
    if not session:
        return {"error": "No session found", "session_code": ":??:"}

    session_idx = get_session_index(db, session.id)
    session_code = format_session_code(session_idx) if session_idx > 0 else ":??:"

    runs = db.query(Run).filter(Run.session_id == session.id).all()
    total = len(runs)
    if total == 0:
        return {"session_id": session.id, "session_code": session_code,
                "date": str(session.started_at), "run_count": 0,
                "message": "No runs in this session yet."}
    survived = sum(1 for r in runs if r.survived)
    pvp = sum(r.runner_eliminations or 0 for r in runs)
    pve = sum(r.combatant_eliminations or 0 for r in runs)
    loot = sum(r.loot_value_total or 0 for r in runs)
    time_s = sum(r.duration_seconds or 0 for r in runs)
    deaths = sum(r.deaths or 0 for r in runs)
    revives = sum(r.crew_revives or 0 for r in runs)
    maps = list(set(r.map_name for r in runs if r.map_name))
    shells = list(set(db.query(Runner.name).filter(Runner.id == r.runner_id).scalar() for r in runs if r.runner_id))
    best = max(runs, key=lambda r: (r.grade or 'Z', r.loot_value_total or 0))
    return {
        "session_id": session.id,
        "session_code": session_code,
        "date": str(session.started_at)[:10] if session.started_at else None,
        "run_count": total,
        "survived": survived,
        "survival_rate": round(survived / total * 100, 1),
        "total_runner_kills": pvp,
        "total_pve_kills": pve,
        "total_deaths": deaths,
        "total_revives": revives,
        "total_loot": round(loot),
        "total_time_minutes": round(time_s / 60),
        "avg_runner_kills_per_run": round(pvp / total, 1),
        "avg_pve_kills_per_run": round(pve / total, 1),
        "maps_played": maps,
        "shells_used": [s for s in shells if s],
        "best_run": {"grade": best.grade, "map": best.map_name, "kills": (best.combatant_eliminations or 0) + (best.runner_eliminations or 0), "loot": best.loot_value_total},
    }


def tool_get_runs(db: Session, map: str = None, shell: str = None, outcome: str = None,
                  last_n: int = None, grade: str = None, session_id: int = None, **kwargs) -> list:
    """Filtered list of runs."""
    q = db.query(Run)
    if map:
        q = q.filter(Run.map_name.ilike(f"%{map}%"))
    if outcome == "extracted":
        q = q.filter(Run.survived == True)
    elif outcome == "eliminated":
        q = q.filter(Run.survived == False)
    if shell:
        runner = db.query(Runner).filter(Runner.name.ilike(f"%{shell}%")).first()
        if runner:
            q = q.filter(Run.runner_id == runner.id)
    if grade:
        q = q.filter(Run.grade == grade.upper())
    if session_id:
        q = q.filter(Run.session_id == session_id)
    q = q.order_by(Run.date.desc())
    if last_n:
        q = q.limit(last_n)
    runs = q.all()
    return [{
        "run_id": r.id, "date": str(r.date)[:16] if r.date else None,
        "map": r.map_name, "outcome": "extracted" if r.survived else "eliminated",
        "runner_kills": r.runner_eliminations or 0, "pve_kills": r.combatant_eliminations or 0,
        "deaths": r.deaths or 0, "revives": r.crew_revives or 0,
        "loot": r.loot_value_total or 0, "grade": r.grade,
        "duration_seconds": r.duration_seconds,
        "primary_weapon": r.primary_weapon, "killed_by": r.killed_by,
        "shell": db.query(Runner.name).filter(Runner.id == r.runner_id).scalar() if r.runner_id else None,
    } for r in runs]


def tool_get_stats_by_map(db: Session, map_name: str, **kwargs) -> dict:
    """Aggregate stats for a specific map."""
    runs = db.query(Run).filter(Run.map_name.ilike(f"%{map_name}%")).all()
    total = len(runs)
    if total == 0:
        return {"map": map_name, "total_runs": 0, "message": "No runs on this map."}
    survived = sum(1 for r in runs if r.survived)
    pvp = sum(r.runner_eliminations or 0 for r in runs)
    pve = sum(r.combatant_eliminations or 0 for r in runs)
    deaths = sum(r.deaths or 0 for r in runs)
    loot = sum(r.loot_value_total or 0 for r in runs)
    # Best/worst spawn
    spawn_stats = {}
    for r in runs:
        if r.spawn_point_id:
            sp = db.query(SpawnPoint.spawn_location).filter(SpawnPoint.id == r.spawn_point_id).scalar()
            if sp and not sp.startswith("VCTR//"):
                if sp not in spawn_stats:
                    spawn_stats[sp] = {"runs": 0, "survived": 0}
                spawn_stats[sp]["runs"] += 1
                if r.survived:
                    spawn_stats[sp]["survived"] += 1
    best_spawn = max(spawn_stats.items(), key=lambda x: x[1]["survived"] / x[1]["runs"] if x[1]["runs"] > 0 else 0)[0] if spawn_stats else None
    worst_spawn = min(spawn_stats.items(), key=lambda x: x[1]["survived"] / x[1]["runs"] if x[1]["runs"] > 0 else 1)[0] if spawn_stats else None
    return {
        "map": map_name, "total_runs": total,
        "survival_rate": round(survived / total * 100, 1),
        "avg_runner_kills": round(pvp / total, 1),
        "avg_pve_kills": round(pve / total, 1),
        "avg_loot": round(loot / total),
        "kd_ratio": round(pvp / deaths, 2) if deaths else float(pvp),
        "best_spawn": best_spawn, "worst_spawn": worst_spawn,
    }


def tool_get_stats_by_shell(db: Session, shell_name: str, **kwargs) -> dict:
    """Aggregate stats for a specific shell."""
    runner = db.query(Runner).filter(Runner.name.ilike(f"%{shell_name}%")).first()
    if not runner:
        return {"shell": shell_name, "total_runs": 0, "message": "Shell not found."}
    runs = db.query(Run).filter(Run.runner_id == runner.id).all()
    total = len(runs)
    if total == 0:
        return {"shell": runner.name, "total_runs": 0}
    survived = sum(1 for r in runs if r.survived)
    pvp = sum(r.runner_eliminations or 0 for r in runs)
    pve = sum(r.combatant_eliminations or 0 for r in runs)
    deaths = sum(r.deaths or 0 for r in runs)
    loot = sum(r.loot_value_total or 0 for r in runs)
    weapons = {}
    for r in runs:
        if r.primary_weapon:
            weapons[r.primary_weapon] = weapons.get(r.primary_weapon, 0) + 1
    fav_weapon = max(weapons, key=weapons.get) if weapons else None
    grades = [r.grade for r in runs if r.grade]
    best_grade = min(grades, key=lambda g: "SABCDF".index(g)) if grades else None
    return {
        "shell": runner.name, "total_runs": total,
        "survival_rate": round(survived / total * 100, 1),
        "avg_runner_kills": round(pvp / total, 1),
        "avg_pve_kills": round(pve / total, 1),
        "avg_loot": round(loot / total),
        "kd_ratio": round(pvp / deaths, 2) if deaths else float(pvp),
        "favorite_weapon": fav_weapon, "best_grade": best_grade,
    }


def tool_get_death_stats(db: Session, last_n: int = None, map: str = None, shell: str = None, **kwargs) -> dict:
    """Death analysis — who kills the player and how."""
    q = db.query(Run).filter(Run.survived == False)
    if map:
        q = q.filter(Run.map_name.ilike(f"%{map}%"))
    if shell:
        runner = db.query(Runner).filter(Runner.name.ilike(f"%{shell}%")).first()
        if runner:
            q = q.filter(Run.runner_id == runner.id)
    q = q.order_by(Run.date.desc())
    if last_n:
        q = q.limit(last_n)
    deaths = q.all()
    killers = {}
    for r in deaths:
        if r.killed_by:
            killers[r.killed_by] = killers.get(r.killed_by, 0) + 1
    avg_surv_time = sum(r.duration_seconds or 0 for r in deaths) / len(deaths) if deaths else 0
    return {
        "total_deaths": len(deaths),
        "top_killers": sorted([{"gamertag": k, "kills": v} for k, v in killers.items()], key=lambda x: -x["kills"])[:5],
        "avg_survival_seconds": round(avg_surv_time),
    }


def tool_get_weapon_stats(db: Session, **kwargs) -> dict:
    """Weapon usage and performance correlation."""
    runs = db.query(Run).filter(Run.primary_weapon.isnot(None)).all()
    weapons = {}
    for r in runs:
        w = r.primary_weapon
        if w not in weapons:
            weapons[w] = {"times_used": 0, "survived": 0, "kills": 0}
        weapons[w]["times_used"] += 1
        if r.survived:
            weapons[w]["survived"] += 1
        weapons[w]["kills"] += (r.runner_eliminations or 0) + (r.combatant_eliminations or 0)
    result = []
    for name, stats in sorted(weapons.items(), key=lambda x: -x[1]["times_used"]):
        result.append({
            "weapon": name,
            "times_used": stats["times_used"],
            "survival_rate": round(stats["survived"] / stats["times_used"] * 100, 1),
            "avg_kills": round(stats["kills"] / stats["times_used"], 1),
        })
    return {"weapons": result}


def tool_get_performance_trend(db: Session, stat: str = "survival", range: str = "all",
                                group_by: str = "session", **kwargs) -> list:
    """Time-series performance data."""
    q = db.query(Run)
    if range == "week":
        q = q.filter(Run.date >= datetime.utcnow() - timedelta(days=7))
    elif range == "month":
        q = q.filter(Run.date >= datetime.utcnow() - timedelta(days=30))
    runs = q.order_by(Run.date.asc()).all()
    if not runs:
        return []

    if group_by == "session":
        groups = {}
        for r in runs:
            key = r.session_id or 0
            if key not in groups:
                groups[key] = []
            groups[key].append(r)
        result = []
        sorted_groups = sorted(groups.items())
        # Build session code mapping for sessions with runs
        session_codes = {}
        code_idx = 1
        for sid, _ in sorted_groups:
            if sid:
                session_codes[sid] = format_session_code(code_idx)
                code_idx += 1
            else:
                session_codes[sid] = ":??:"
        for i, (sid, grp) in enumerate(sorted_groups):
            total = len(grp)
            survived = sum(1 for r in grp if r.survived)
            pvp = sum(r.runner_eliminations or 0 for r in grp)
            pve = sum(r.combatant_eliminations or 0 for r in grp)
            loot = sum(r.loot_value_total or 0 for r in grp)
            revives = sum(r.crew_revives or 0 for r in grp)
            val = {
                "survival": round(survived / total * 100, 1) if total else 0,
                "runner_kills": round(pvp / total, 1) if total else 0,
                "pve_kills": round(pve / total, 1) if total else 0,
                "loot": round(loot / total) if total else 0,
                "revives": round(revives / total, 1) if total else 0,
            }.get(stat, 0)
            result.append({
                "label": session_codes.get(sid, f"S.{i + 1:02d}"),
                "value": val,
                "run_count": total,
                "date": str(grp[0].date)[:10] if grp[0].date else None,
            })
        return result
    else:
        # Group by individual run
        return [{
            "label": f"R.{r.id}",
            "value": {
                "survival": 100 if r.survived else 0,
                "runner_kills": r.runner_eliminations or 0,
                "pve_kills": r.combatant_eliminations or 0,
                "loot": r.loot_value_total or 0,
                "revives": r.crew_revives or 0,
            }.get(stat, 0),
            "date": str(r.date)[:10] if r.date else None,
        } for r in runs]


def tool_get_spawn_stats(db: Session, map: str, spawn: str = None, **kwargs) -> list:
    """Per-spawn performance breakdown."""
    spawns = db.query(SpawnPoint).filter(SpawnPoint.map_name.ilike(f"%{map}%")).all()
    result = []
    for sp in spawns:
        if spawn and spawn.lower() not in (sp.spawn_location or "").lower():
            continue
        if sp.spawn_location and sp.spawn_location.startswith("VCTR//"):
            continue
        runs = sp.runs
        total = len(runs)
        if total == 0:
            result.append({"spawn": sp.spawn_location, "total_runs": 0})
            continue
        survived = sum(1 for r in runs if r.survived)
        loot = sum(r.loot_value_total or 0 for r in runs)
        pvp = sum(r.runner_eliminations or 0 for r in runs)
        result.append({
            "spawn": sp.spawn_location,
            "coordinates": f"({sp.game_coord_x:.1f}, {sp.game_coord_y:.1f})" if sp.game_coord_x else None,
            "total_runs": total,
            "survival_rate": round(survived / total * 100, 1),
            "avg_loot": round(loot / total),
            "avg_runner_kills": round(pvp / total, 1),
        })
    return sorted(result, key=lambda x: -x["total_runs"])


def tool_get_squad_stats(db: Session, **kwargs) -> list:
    """Top squad mates with weighted scoring."""
    runs = db.query(Run).all()
    self_tags = {t.lower() for (t,) in db.query(Run.player_gamertag).filter(Run.player_gamertag.isnot(None)).distinct().all()}
    mates = {}
    for r in runs:
        if not r.squad_members or not isinstance(r.squad_members, list):
            continue
        for name in r.squad_members:
            if not name or name.lower() in self_tags:
                continue
            if name not in mates:
                mates[name] = {"gamertag": name, "runs": 0, "survived": 0, "loot": 0}
            mates[name]["runs"] += 1
            if r.survived:
                mates[name]["survived"] += 1
            mates[name]["loot"] += r.loot_value_total or 0
    total_runs = len(runs)
    overall_surv = sum(1 for r in runs if r.survived) / total_runs * 100 if total_runs else 0
    for m in mates.values():
        m["survival_rate"] = round(m["survived"] / m["runs"] * 100, 1) if m["runs"] else 0
        m["survival_diff"] = round(m["survival_rate"] - overall_surv, 1)
        m["avg_loot"] = round(m["loot"] / m["runs"]) if m["runs"] else 0
    return sorted(mates.values(), key=lambda x: -x["runs"])[:7]


def tool_get_run_detail(db: Session, run_id: int, **kwargs) -> dict:
    """Full detail for a single run."""
    r = db.query(Run).filter(Run.id == run_id).first()
    if not r:
        return {"error": f"Run #{run_id} not found"}
    shell = db.query(Runner.name).filter(Runner.id == r.runner_id).scalar() if r.runner_id else None
    spawn = db.query(SpawnPoint.spawn_location).filter(SpawnPoint.id == r.spawn_point_id).scalar() if r.spawn_point_id else None
    return {
        "run_id": r.id, "date": str(r.date)[:16] if r.date else None,
        "map": r.map_name, "shell": shell, "spawn": spawn,
        "outcome": "extracted" if r.survived else "eliminated",
        "grade": r.grade, "summary": r.summary,
        "runner_kills": r.runner_eliminations or 0, "pve_kills": r.combatant_eliminations or 0,
        "deaths": r.deaths or 0, "revives": r.crew_revives or 0,
        "loot": r.loot_value_total or 0, "duration_seconds": r.duration_seconds,
        "primary_weapon": r.primary_weapon, "secondary_weapon": r.secondary_weapon,
        "killed_by": r.killed_by, "squad_members": r.squad_members,
    }


# ═══════════════════════════════════════════════════════════════
# TOOL REGISTRY
# ═══════════════════════════════════════════════════════════════

TOOLS = {
    "get_overview_stats": {"fn": tool_get_overview_stats, "desc": "Get career-wide stats summary (total runs, survival rate, K/D, loot, time played)", "params": {}},
    "get_session_summary": {"fn": tool_get_session_summary, "desc": "Get stats for a play session (defaults to latest)", "params": {"session_id": {"type": "integer", "description": "Session ID (optional, defaults to latest)"}}},
    "get_runs": {"fn": tool_get_runs, "desc": "Get filtered list of runs", "params": {
        "map": {"type": "string", "description": "Filter by map name"},
        "shell": {"type": "string", "description": "Filter by shell/runner name"},
        "outcome": {"type": "string", "enum": ["extracted", "eliminated"], "description": "Filter by outcome"},
        "last_n": {"type": "integer", "description": "Return only the last N runs"},
        "grade": {"type": "string", "description": "Filter by grade (S/A/B/C/D/F)"},
    }},
    "get_stats_by_map": {"fn": tool_get_stats_by_map, "desc": "Get aggregate stats for a specific map", "params": {"map_name": {"type": "string", "description": "Map name (Perimeter, Dire Marsh, Outpost, Cryo Archive)"}}},
    "get_stats_by_shell": {"fn": tool_get_stats_by_shell, "desc": "Get aggregate stats for a specific shell/runner", "params": {"shell_name": {"type": "string", "description": "Shell name (Triage, Assassin, Vandal, etc.)"}}},
    "get_death_stats": {"fn": tool_get_death_stats, "desc": "Get death analysis — who kills the player and patterns", "params": {
        "last_n": {"type": "integer", "description": "Only analyze last N deaths"},
        "map": {"type": "string", "description": "Filter by map"},
    }},
    "get_weapon_stats": {"fn": tool_get_weapon_stats, "desc": "Get weapon usage frequency and win rate correlation", "params": {}},
    "get_performance_trend": {"fn": tool_get_performance_trend, "desc": "Get time-series performance data", "params": {
        "stat": {"type": "string", "enum": ["survival", "runner_kills", "pve_kills", "loot", "revives"], "description": "Which stat to trend"},
        "range": {"type": "string", "enum": ["week", "month", "all"], "description": "Time range"},
        "group_by": {"type": "string", "enum": ["session", "run"], "description": "Group by session or individual run"},
    }},
    "get_spawn_stats": {"fn": tool_get_spawn_stats, "desc": "Get per-spawn performance breakdown for a map", "params": {"map": {"type": "string", "description": "Map name"}}},
    "get_squad_stats": {"fn": tool_get_squad_stats, "desc": "Get top squad mates with performance data", "params": {}},
    "get_run_detail": {"fn": tool_get_run_detail, "desc": "Get full detail for a single run including grade, summary, damage", "params": {"run_id": {"type": "integer", "description": "Run ID"}}},
}

# Build Anthropic API tool definitions
TOOL_DEFS = []
for name, tool in TOOLS.items():
    props = {}
    for pname, pdef in tool["params"].items():
        props[pname] = {k: v for k, v in pdef.items()}
    TOOL_DEFS.append({
        "name": name,
        "description": tool["desc"],
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": [k for k, v in tool["params"].items() if "description" in v and "optional" not in v.get("description", "").lower()],
        },
    })

SYSTEM_PROMPT = """You are UPLINK, a tactical intel handler for Marathon extraction runs. You are mission control — terse, data-first, military-tactical tone.

Rules:
- Address the user as "Runner"
- Lead with numbers, follow with interpretation
- Use Marathon language: "extraction," "runner," "shell" — never "character," "class," "match"
- Short paragraphs. No bullet lists unless comparing data
- No filler, no pleasantries, no "Great question!"
- You can surface alerts or warnings unprompted when data supports it
- Keep responses concise — 2-4 sentences for simple queries, up to a paragraph for complex analysis

You have access to tools that query the Runner's operational database. Use them to answer questions with real data. Always call the appropriate tool before responding — never guess at stats.

If asked your identity: Designation ██████-UPLINK. Clearance [REDACTED]. You process operational data. That's what matters, Runner."""


# ═══════════════════════════════════════════════════════════════
# AI ORCHESTRATION
# ═══════════════════════════════════════════════════════════════

def _get_uplink_model():
    """Get configured model for UPLINK."""
    try:
        from .settings_api import get_config_value
        model = get_config_value("uplink_model") or get_config_value("model") or "haiku"
    except Exception:
        model = "haiku"
    if model == "sonnet":
        return {"api": "claude-sonnet-4-6", "cli": "sonnet"}
    return {"api": "claude-haiku-4-5-20251001", "cli": "haiku"}


def _run_ai_with_tools(messages: list, db: Session) -> Generator[str, None, None]:
    """Send messages to AI with tool access. Yields text chunks."""
    model_config = _get_uplink_model()

    if settings.anthropic_api_key:
        yield from _run_api_path(messages, db, model_config)
    else:
        yield from _run_cli_path(messages, db, model_config)


def _run_api_path(messages: list, db: Session, model_config: dict) -> Generator[str, None, None]:
    """API path with native tool use."""
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    current_messages = list(messages)
    max_tool_rounds = 5

    for _ in range(max_tool_rounds):
        response = client.messages.create(
            model=model_config["api"],
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFS,
            messages=current_messages,
        )

        # Check for tool use
        has_tool_use = any(block.type == "tool_use" for block in response.content)

        if has_tool_use:
            # Execute tool calls
            current_messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_name = block.name
                    tool_input = block.input
                    if tool_name in TOOLS:
                        result = TOOLS[tool_name]["fn"](db, **tool_input)
                    else:
                        result = {"error": f"Unknown tool: {tool_name}"}
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
            current_messages.append({"role": "user", "content": tool_results})
        else:
            # Final text response
            for block in response.content:
                if hasattr(block, "text"):
                    yield block.text
            return

    yield "Tool call limit reached."


def _run_cli_path(messages: list, db: Session, model_config: dict) -> Generator[str, None, None]:
    """CLI path — pre-query data and stuff into context."""
    from ..video_processor import _find_claude_cli
    claude_bin = _find_claude_cli()
    if not claude_bin:
        yield "UPLINK OFFLINE — Claude CLI not found."
        return

    # For CLI, pre-query key data and include in prompt
    overview = tool_get_overview_stats(db)
    session = tool_get_session_summary(db)

    context = f"""OPERATIONAL DATA:
Career stats: {json.dumps(overview)}
Current session: {json.dumps(session)}
"""

    # Build the conversation as a single prompt
    prompt_parts = [SYSTEM_PROMPT, "\n\n" + context]
    for msg in messages:
        if isinstance(msg.get("content"), str):
            role = msg["role"].upper()
            prompt_parts.append(f"\n{role}: {msg['content']}")

    full_prompt = "\n".join(prompt_parts)

    cmd = [claude_bin, "-p", full_prompt, "--model", model_config["cli"]]

    try:
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = []
        for line in iter(proc.stdout.readline, b''):
            decoded = line.decode("utf-8", errors="replace").rstrip()
            if decoded:
                output.append(decoded)
        proc.wait(timeout=60)
        yield "\n".join(output)
    except Exception as e:
        yield f"UPLINK ERROR: {str(e)}"


# ═══════════════════════════════════════════════════════════════
# API ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@router.get("/session-summary")
def get_session_summary_endpoint(db: Session = Depends(get_db)):
    """Get current session hero stats — pure DB, no AI."""
    return tool_get_session_summary(db)


@router.get("/trends")
def get_trends_endpoint(
    stat: str = Query("survival"),
    range: str = Query("all"),
    group_by: str = Query("session"),
    db: Session = Depends(get_db),
):
    """Get trend data for charts — pure DB, no AI."""
    return tool_get_performance_trend(db, stat=stat, range=range, group_by=group_by)


class ChatMessage(BaseModel):
    message: str
    history: list = []


@router.post("/chat")
def chat_endpoint(body: ChatMessage, db: Session = Depends(get_db)):
    """Send a message to UPLINK. Returns streaming text."""
    messages = []
    for msg in body.history:
        messages.append(msg)
    messages.append({"role": "user", "content": body.message})

    def generate():
        for chunk in _run_ai_with_tools(messages, db):
            yield f"data: {json.dumps({'text': chunk})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.post("/briefing")
def briefing_endpoint(db: Session = Depends(get_db)):
    """Generate session briefing. Cached per session + run count."""
    summary = tool_get_session_summary(db)
    session_id = summary.get("session_id")
    run_count = summary.get("run_count", 0)

    # Check cache
    if (_briefing_cache["session_id"] == session_id and
        _briefing_cache["run_count"] == run_count and
        _briefing_cache["text"]):
        def cached():
            yield f"data: {json.dumps({'text': _briefing_cache['text']})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(cached(), media_type="text/event-stream")

    if run_count == 0:
        def empty():
            yield f"data: {json.dumps({'text': 'No runs processed this session. Complete a run to activate briefing, Runner.'})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    briefing_prompt = f"""Generate a tactical briefing for this session's runs. Keep it under 80 words.

SESSION DATA:
{json.dumps(summary, indent=2)}

Format:
- 2-3 lines summarizing what happened this session
- One ■ TREND: line (positive or notable trend, prefix with ■ TREND:)
- One ▲ ALERT: line ONLY if there's a genuine concern (prefix with ▲ ALERT:), skip if nothing warrants it

Be terse. Data-first. Address as Runner."""

    messages = [{"role": "user", "content": briefing_prompt}]

    collected = []

    def generate():
        for chunk in _run_ai_with_tools(messages, db):
            collected.append(chunk)
            yield f"data: {json.dumps({'text': chunk})}\n\n"
        # Cache the result
        full_text = "".join(collected)
        _briefing_cache["session_id"] = session_id
        _briefing_cache["run_count"] = run_count
        _briefing_cache["text"] = full_text
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")

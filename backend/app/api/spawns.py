import json
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session as DBSession
from PIL import Image
import io

from pydantic import BaseModel

from ..database import get_db
from ..models import SpawnPoint
from ..config import settings
from ..schemas import SpawnPointCreate, SpawnPointOut, ParsedSpawnScreenshot
from .screenshot import _call_claude, _extract_json

router = APIRouter()

SPAWN_PARSE_PROMPT = """Analyze this Marathon (Bungie 2026 extraction shooter) in-game screenshot taken at the start of a run when the player first spawns in.

I need you to identify the spawn location. Look for:
- The map name (shown on the HUD, loading screen, or identifiable from environment)
- The specific spawn location/area name (if displayed on screen or identifiable)
- Any visible landmarks, signs, or environmental cues that help identify where on the map this is

Return ONLY valid JSON:
{
  "map_name": "string or null",
  "spawn_location": "string description of the specific spawn point, or null",
  "landmarks_visible": ["list", "of", "visible", "landmarks/signs"] or null,
  "raw_text": "summary of any text visible on screen (HUD, signs, etc.)",
  "confidence": "high/medium/low"
}

Return ONLY the JSON object, no markdown, no explanation."""


async def _save_spawn_upload(file: UploadFile) -> str:
    """Save a spawn screenshot and return the path."""
    contents = await file.read()

    try:
        img = Image.open(io.BytesIO(contents))
        img.verify()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    os.makedirs(settings.media_upload_dir, exist_ok=True)
    ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else "png"
    filename = f"spawn_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(settings.media_upload_dir, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    return filepath


@router.post("/parse", response_model=ParsedSpawnScreenshot)
async def parse_spawn_screenshot(file: UploadFile = File(...)):
    """Upload a spawn/map screenshot and identify the spawn location.
    Uses Claude CLI (OAuth) if available, otherwise falls back to API key.
    """
    filepath = await _save_spawn_upload(file)

    try:
        response_text = await _call_claude([filepath], SPAWN_PARSE_PROMPT)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Claude error: {str(e)}")

    try:
        parsed = _extract_json(response_text)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=422, detail=f"Could not parse response: {response_text[:500]}")

    return ParsedSpawnScreenshot(**parsed)


@router.post("/", response_model=SpawnPointOut, status_code=201)
def create_spawn(data: SpawnPointCreate, db: DBSession = Depends(get_db)):
    spawn = SpawnPoint(**data.model_dump(exclude_none=True))
    db.add(spawn)
    db.commit()
    db.refresh(spawn)
    return spawn


class CoordsUpdate(BaseModel):
    map_name: str
    spawn_location: str
    x: float
    y: float


@router.put("/update-coords")
def update_spawn_coords(body: CoordsUpdate, db: DBSession = Depends(get_db)):
    """Update x,y coordinates for a spawn point by map + location name."""
    q = db.query(SpawnPoint).filter(
        SpawnPoint.map_name == body.map_name,
        SpawnPoint.spawn_location == body.spawn_location,
    )
    spawns = q.all()

    if not spawns:
        raise HTTPException(status_code=404, detail=f"No spawn found for {body.map_name}/{body.spawn_location}")

    for s in spawns:
        s.x = body.x
        s.y = body.y

    db.commit()
    return {"updated": len(spawns), "map": body.map_name, "location": body.spawn_location, "x": body.x, "y": body.y}


class CoordsUpdateById(BaseModel):
    id: int
    x: float
    y: float


@router.put("/update-coords-by-id")
def update_spawn_coords_by_id(body: CoordsUpdateById, db: DBSession = Depends(get_db)):
    """Update x,y coordinates for a spawn point by its database ID."""
    spawn = db.query(SpawnPoint).filter(SpawnPoint.id == body.id).first()
    if not spawn:
        raise HTTPException(status_code=404, detail=f"Spawn #{body.id} not found")
    spawn.x = body.x
    spawn.y = body.y
    db.commit()
    return {"updated": 1, "id": body.id, "x": body.x, "y": body.y}


class SpawnRename(BaseModel):
    id: int
    spawn_location: str


@router.put("/rename")
def rename_spawn(body: SpawnRename, db: DBSession = Depends(get_db)):
    """Rename a spawn point's display name."""
    spawn = db.query(SpawnPoint).filter(SpawnPoint.id == body.id).first()
    if not spawn:
        raise HTTPException(status_code=404, detail=f"Spawn #{body.id} not found")
    old_name = spawn.spawn_location
    spawn.spawn_location = body.spawn_location.strip()
    db.commit()
    return {"id": body.id, "old_name": old_name, "new_name": spawn.spawn_location}


@router.get("/", response_model=list[SpawnPointOut])
def list_spawns(map_name: str = None, db: DBSession = Depends(get_db)):
    q = db.query(SpawnPoint)
    if map_name:
        q = q.filter(SpawnPoint.map_name == map_name)
    return q.order_by(SpawnPoint.created_at.desc()).all()


@router.get("/heatmap")
def spawn_heatmap(db: DBSession = Depends(get_db)):
    """Get spawn frequency data grouped by map + location for heatmap visualization."""
    spawns = db.query(SpawnPoint).all()

    maps: dict[str, dict[str, dict]] = {}
    for s in spawns:
        map_key = s.map_name or "Unknown"
        loc_key = s.spawn_location or "Unknown"

        if map_key not in maps:
            maps[map_key] = {}
        if loc_key not in maps[map_key]:
            maps[map_key][loc_key] = {
                "location": loc_key,
                "x": s.x,
                "y": s.y,
                "count": 0,
                "runs_survived": 0,
                "runs_died": 0,
                "total_loot": 0,
                "total_time": 0,
                "total_kills": 0,
                "pve_kills": 0,
                "runner_kills": 0,
                "total_deaths": 0,
                "total_revives": 0,
                "best_loot": None,
                "worst_loot": None,
                "longest_run": None,
                "shortest_run": None,
                "weapons": [],
                "shells": [],
                "killed_by": [],
                "last_played": None,
                "loot_values": [],
            }

        entry = maps[map_key][loc_key]
        entry["count"] += len(s.runs)  # count of runs from this spawn
        if s.x is not None:
            entry["x"] = s.x
            entry["y"] = s.y
        for run in s.runs:
            if run.survived is not None:
                if run.survived:
                    entry["runs_survived"] += 1
                else:
                    entry["runs_died"] += 1
            loot = run.loot_value_total or 0
            duration = run.duration_seconds or 0
            entry["total_loot"] += loot
            entry["total_time"] += duration
            entry["loot_values"].append(loot)
            entry["pve_kills"] += run.combatant_eliminations or 0
            entry["runner_kills"] += run.runner_eliminations or 0
            entry["total_kills"] += (run.combatant_eliminations or 0) + (run.runner_eliminations or 0)
            entry["total_deaths"] += run.deaths or 0
            entry["total_revives"] += run.crew_revives or 0

            # Track best/worst loot
            if entry["best_loot"] is None or loot > entry["best_loot"]:
                entry["best_loot"] = loot
            if entry["worst_loot"] is None or loot < entry["worst_loot"]:
                entry["worst_loot"] = loot

            # Track longest/shortest run
            if duration > 0:
                if entry["longest_run"] is None or duration > entry["longest_run"]:
                    entry["longest_run"] = duration
                if entry["shortest_run"] is None or duration < entry["shortest_run"]:
                    entry["shortest_run"] = duration

            # Track weapons
            if run.primary_weapon:
                entry["weapons"].append(run.primary_weapon)

            # Track shells
            if run.runner and run.runner.name:
                entry["shells"].append(run.runner.name)

            # Track killers
            if run.killed_by:
                entry["killed_by"].append({"name": run.killed_by, "damage": run.killed_by_damage})

            # Track last played
            if run.date:
                date_str = run.date.isoformat() if hasattr(run.date, 'isoformat') else str(run.date)
                if entry["last_played"] is None or date_str > entry["last_played"]:
                    entry["last_played"] = date_str

    result = []
    for mn, locations in maps.items():
        loc_list = list(locations.values())
        for loc in loc_list:
            total = loc["runs_survived"] + loc["runs_died"]
            loc["survival_rate"] = round(loc["runs_survived"] / total * 100, 1) if total else None
            loc["avg_loot"] = round(loc["total_loot"] / total, 0) if total else None
            loc["avg_time"] = round(loc["total_time"] / total) if total else None

            # Most used weapon at this spawn
            weapons = loc.pop("weapons")
            if weapons:
                from collections import Counter
                loc["fav_weapon"] = Counter(weapons).most_common(1)[0][0]
            else:
                loc["fav_weapon"] = None

            # Most used shell
            shells = loc.pop("shells")
            if shells:
                from collections import Counter
                loc["fav_shell"] = Counter(shells).most_common(1)[0][0]
            else:
                loc["fav_shell"] = None

            # Clean up internal tracking
            loc.pop("loot_values", None)
        result.append({
            "map": mn,
            "total_spawns": sum(l["count"] for l in loc_list),
            "locations": sorted(loc_list, key=lambda x: x["count"], reverse=True),
        })

    return sorted(result, key=lambda x: x["total_spawns"], reverse=True)

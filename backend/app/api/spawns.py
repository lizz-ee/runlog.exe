import json
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session as DBSession
from PIL import Image
import io

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
- The spawn region — a general area descriptor (e.g. "north", "south", "east wing", "underground", "rooftop", "cargo bay", etc.) based on visible environment, compass, or HUD indicators
- Any visible landmarks, signs, or environmental cues that help identify where on the map this is

Return ONLY valid JSON:
{
  "map_name": "string or null",
  "spawn_location": "string description of the specific spawn point, or null",
  "spawn_region": "string general area/region, or null",
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
        loc_key = s.spawn_location or s.spawn_region or "Unknown"

        if map_key not in maps:
            maps[map_key] = {}
        if loc_key not in maps[map_key]:
            maps[map_key][loc_key] = {
                "location": loc_key,
                "region": s.spawn_region,
                "x": s.x,
                "y": s.y,
                "count": 0,
                "runs_survived": 0,
                "runs_died": 0,
            }

        entry = maps[map_key][loc_key]
        entry["count"] += 1
        # Update x/y if this entry doesn't have one yet
        if entry["x"] is None and s.x is not None:
            entry["x"] = s.x
            entry["y"] = s.y

        if s.run and s.run.survived is not None:
            if s.run.survived:
                entry["runs_survived"] += 1
            else:
                entry["runs_died"] += 1

    result = []
    for mn, locations in maps.items():
        loc_list = list(locations.values())
        for loc in loc_list:
            total = loc["runs_survived"] + loc["runs_died"]
            loc["survival_rate"] = round(loc["runs_survived"] / total * 100, 1) if total else None
        result.append({
            "map": mn,
            "total_spawns": sum(l["count"] for l in loc_list),
            "locations": sorted(loc_list, key=lambda x: x["count"], reverse=True),
        })

    return sorted(result, key=lambda x: x["total_spawns"], reverse=True)

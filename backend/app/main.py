from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
import os
import shutil
from datetime import datetime

from .database import engine, Base
from .api import api_router
from .config import settings, _DATA_DIR

# Auto-backup DB on startup (keep last 7 backups)
_db_file = os.path.join(_DATA_DIR, "runlog.db")
_backup_dir = os.path.join(_DATA_DIR, "backups")
if os.path.exists(_db_file):
    os.makedirs(_backup_dir, exist_ok=True)
    backup_name = f"runlog_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(_db_file, os.path.join(_backup_dir, backup_name))
    # Keep only the 7 most recent backups
    backups = sorted(
        [f for f in os.listdir(_backup_dir) if f.endswith(".db")],
        reverse=True,
    )
    for old in backups[7:]:
        os.remove(os.path.join(_backup_dir, old))
    print(f"[backup] Saved {backup_name} ({len(backups)} total, keeping 7)")

# Create all tables
Base.metadata.create_all(bind=engine)

# Migrate: add new columns to existing tables if missing
with engine.connect() as conn:
    inspector = inspect(engine)
    existing_cols = {c["name"] for c in inspector.get_columns("runs")}
    if "grade" not in existing_cols:
        conn.execute(text("ALTER TABLE runs ADD COLUMN grade VARCHAR(2)"))
        conn.commit()
    if "summary" not in existing_cols:
        conn.execute(text("ALTER TABLE runs ADD COLUMN summary TEXT"))
        conn.commit()
    if "player_gamertag" not in existing_cols:
        conn.execute(text("ALTER TABLE runs ADD COLUMN player_gamertag VARCHAR(100)"))
        conn.commit()
    if "viewed" not in existing_cols:
        conn.execute(text("ALTER TABLE runs ADD COLUMN viewed BOOLEAN DEFAULT 0"))
        conn.commit()
    if "is_favorite" not in existing_cols:
        conn.execute(text("ALTER TABLE runs ADD COLUMN is_favorite BOOLEAN DEFAULT 0"))
        conn.commit()
    if "starting_loadout_value" not in existing_cols:
        conn.execute(text("ALTER TABLE runs ADD COLUMN starting_loadout_value FLOAT"))
        conn.commit()
    if "player_level" not in existing_cols:
        conn.execute(text("ALTER TABLE runs ADD COLUMN player_level INTEGER"))
        conn.commit()
    if "vault_value" not in existing_cols:
        conn.execute(text("ALTER TABLE runs ADD COLUMN vault_value FLOAT"))
        conn.commit()
    if "killed_by_weapon" not in existing_cols:
        conn.execute(text("ALTER TABLE runs ADD COLUMN killed_by_weapon VARCHAR(100)"))
        conn.commit()
    if "damage_contributors" not in existing_cols:
        conn.execute(text("ALTER TABLE runs ADD COLUMN damage_contributors JSON"))
        conn.commit()

# Seed spawn points from reference data if table is empty
from .database import SessionLocal
from .models import SpawnPoint
_seed_db = SessionLocal()
if _seed_db.query(SpawnPoint).count() == 0:
    _seed_file = os.path.join(os.path.dirname(__file__), "data", "spawn_points.json")
    if os.path.exists(_seed_file):
        import json
        with open(_seed_file) as f:
            _seed_spawns = json.load(f)
        for s in _seed_spawns:
            _seed_db.add(SpawnPoint(
                map_name=s["map_name"],
                spawn_location=s["spawn_location"],
                x=s.get("x"),
                y=s.get("y"),
                game_coord_x=s.get("game_coord_x"),
                game_coord_y=s.get("game_coord_y"),
            ))
        _seed_db.commit()
        print(f"[seed] Loaded {len(_seed_spawns)} reference spawn points")
_seed_db.close()

# Session tracking — created on first run, not on startup (Option B)
# This avoids empty sessions from app open/close without playing
current_session_id = None  # Set when first run is processed

def get_or_create_session() -> int:
    """Get current session ID, creating one if needed."""
    global current_session_id
    if current_session_id is not None:
        return current_session_id
    from .models import Session as SessionModel
    db = SessionLocal()
    session = SessionModel(started_at=datetime.utcnow())
    db.add(session)
    db.commit()
    db.refresh(session)
    current_session_id = session.id
    db.close()
    print(f"[session] Created session #{current_session_id}")
    return current_session_id

app = FastAPI(
    title="Marathon RunLog",
    description="Track your Marathon extraction runs with screenshot parsing",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root():
    return {"app": "Marathon RunLog", "version": "1.0.0", "status": "running"}

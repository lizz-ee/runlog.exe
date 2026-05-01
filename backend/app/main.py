from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
import os
import shutil
from datetime import datetime, timezone

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

# Migrate: add new columns to existing tables if missing (single transaction)
with engine.connect() as conn:
    inspector = inspect(engine)
    existing_cols = {c["name"] for c in inspector.get_columns("runs")}
    _migrations = {
        "grade": "ALTER TABLE runs ADD COLUMN grade VARCHAR(2)",
        "summary": "ALTER TABLE runs ADD COLUMN summary TEXT",
        "player_gamertag": "ALTER TABLE runs ADD COLUMN player_gamertag VARCHAR(100)",
        "viewed": "ALTER TABLE runs ADD COLUMN viewed BOOLEAN DEFAULT 0",
        "is_favorite": "ALTER TABLE runs ADD COLUMN is_favorite BOOLEAN DEFAULT 0",
        "starting_loadout_value": "ALTER TABLE runs ADD COLUMN starting_loadout_value FLOAT",
        "player_level": "ALTER TABLE runs ADD COLUMN player_level INTEGER",
        "vault_value": "ALTER TABLE runs ADD COLUMN vault_value FLOAT",
        "killed_by_weapon": "ALTER TABLE runs ADD COLUMN killed_by_weapon VARCHAR(100)",
        "damage_contributors": "ALTER TABLE runs ADD COLUMN damage_contributors JSON",
        "is_ranked": "ALTER TABLE runs ADD COLUMN is_ranked BOOLEAN DEFAULT 0",
    }
    applied = 0
    for col_name, ddl in _migrations.items():
        if col_name not in existing_cols:
            conn.execute(text(ddl))
            applied += 1
    if applied:
        conn.commit()
        print(f"[migrate] Applied {applied} column migrations")

    # Create indexes on existing tables (idempotent — IF NOT EXISTS)
    _indexes = [
        "CREATE INDEX IF NOT EXISTS ix_runs_date ON runs (date)",
        "CREATE INDEX IF NOT EXISTS ix_runs_map_name ON runs (map_name)",
        "CREATE INDEX IF NOT EXISTS ix_runs_survived ON runs (survived)",
        "CREATE INDEX IF NOT EXISTS ix_runs_runner_id ON runs (runner_id)",
        "CREATE INDEX IF NOT EXISTS ix_runs_session_id ON runs (session_id)",
        "CREATE INDEX IF NOT EXISTS ix_runs_spawn_point_id ON runs (spawn_point_id)",
        "CREATE INDEX IF NOT EXISTS ix_runs_grade ON runs (grade)",
        "CREATE INDEX IF NOT EXISTS ix_runs_viewed ON runs (viewed)",
        "CREATE INDEX IF NOT EXISTS ix_runs_is_favorite ON runs (is_favorite)",
        "CREATE INDEX IF NOT EXISTS ix_runs_is_ranked ON runs (is_ranked)",
    ]
    idx_applied = 0
    for ddl in _indexes:
        try:
            conn.execute(text(ddl))
            idx_applied += 1
        except Exception:
            pass
    if idx_applied:
        conn.commit()
        print(f"[migrate] Ensured {idx_applied} indexes exist")

# Seed spawn points from reference data if table is empty
from .database import SessionLocal
from .models import SpawnPoint
_seed_db = SessionLocal()
try:
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

    # Idempotent cleanup: drop any seeded spawn points without game coordinates.
    # Earlier seed data shipped Perimeter/Columns and Perimeter/Tunnels with
    # null game_coord_x/y; those locations have no map placement and shouldn't
    # appear in the spawn list. Re-points dependent runs to NULL first so the
    # FK delete is safe.
    from .models import Run
    _orphan_ids = [
        sid for (sid,) in _seed_db.query(SpawnPoint.id).filter(
            (SpawnPoint.game_coord_x.is_(None)) | (SpawnPoint.game_coord_y.is_(None))
        ).all()
    ]
    if _orphan_ids:
        _seed_db.query(Run).filter(Run.spawn_point_id.in_(_orphan_ids)).update(
            {Run.spawn_point_id: None}, synchronize_session=False
        )
        deleted = _seed_db.query(SpawnPoint).filter(SpawnPoint.id.in_(_orphan_ids)).delete(
            synchronize_session=False
        )
        _seed_db.commit()
        print(f"[seed] Removed {deleted} spawn point(s) without game coordinates")

    # Idempotent dupe consolidation: Outpost/Processing SE was the same
    # physical spawn as Processing E (same screen pos, game coords <1 unit
    # apart). The reference data dropped Processing SE in favour of the
    # recovered "Processing E" name. Migrate any runs pointing at the old
    # row to the surviving Processing E row, then delete the dupe.
    _dupe = _seed_db.query(SpawnPoint).filter_by(
        map_name="Outpost", spawn_location="Processing SE"
    ).one_or_none()
    if _dupe:
        _keep = _seed_db.query(SpawnPoint).filter_by(
            map_name="Outpost", spawn_location="Processing E"
        ).one_or_none()
        if _keep:
            _seed_db.query(Run).filter(Run.spawn_point_id == _dupe.id).update(
                {Run.spawn_point_id: _keep.id}, synchronize_session=False
            )
            _seed_db.delete(_dupe)
            _seed_db.commit()
            print("[seed] Consolidated duplicate spawn point Outpost/Processing SE -> Processing E")
        else:
            # Surviving row not present yet; rename the dupe in-place so we
            # don't lose the data, and let the upsert below skip it.
            _dupe.spawn_location = "Processing E"
            _seed_db.commit()
            print("[seed] Renamed Outpost/Processing SE -> Processing E (no existing duplicate)")

    # Idempotent upsert: any (map_name, spawn_location) in the shipping JSON
    # that is missing from the user's DB gets inserted. Existing rows are left
    # alone so user-edited coordinates aren't clobbered. New users get
    # everything via the empty-table seed above; this branch only matters for
    # users upgrading from an older seed snapshot.
    _seed_file = os.path.join(os.path.dirname(__file__), "data", "spawn_points.json")
    if os.path.exists(_seed_file):
        import json
        with open(_seed_file) as f:
            _ref_spawns = json.load(f)
        existing_keys = {
            (m, l) for (m, l) in _seed_db.query(
                SpawnPoint.map_name, SpawnPoint.spawn_location
            ).all()
        }
        added = 0
        for s in _ref_spawns:
            if (s["map_name"], s["spawn_location"]) in existing_keys:
                continue
            _seed_db.add(SpawnPoint(
                map_name=s["map_name"],
                spawn_location=s["spawn_location"],
                x=s.get("x"),
                y=s.get("y"),
                game_coord_x=s.get("game_coord_x"),
                game_coord_y=s.get("game_coord_y"),
            ))
            added += 1
        if added:
            _seed_db.commit()
            print(f"[seed] Added {added} new spawn point(s) from updated reference data")
finally:
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
    session = SessionModel(started_at=datetime.now(timezone.utc))
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

_api_port = os.environ.get("RUNLOG_PORT", "8000")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", f"http://127.0.0.1:{_api_port}", "app://.", "file://"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)

app.include_router(api_router)


@app.get("/")
def root():
    return {"app": "Marathon RunLog", "version": "1.0.0", "status": "running"}

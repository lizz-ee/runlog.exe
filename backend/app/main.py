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
        # Backfill: set player_gamertag for existing runs where squad_members contains the name
        # This seeds the auto-exclusion so historical squad mate stats work immediately
        conn.execute(text(
            "UPDATE runs SET player_gamertag = 'kale#8064' "
            "WHERE squad_members LIKE '%kale#8064%' AND player_gamertag IS NULL"
        ))
        conn.commit()

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

# Serve uploaded screenshots
os.makedirs(settings.media_upload_dir, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.media_upload_dir), name="media")

app.include_router(api_router)


@app.get("/")
def root():
    return {"app": "Marathon RunLog", "version": "1.0.0", "status": "running"}

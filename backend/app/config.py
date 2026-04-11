import json
import os
import shutil
from pydantic_settings import BaseSettings

# Data location: AppData/Roaming/runlog/marathon/data/
# Structure: runlog/<game>/data/ — supports future multi-game expansion
_APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
_RUNLOG_ROOT = os.path.join(_APPDATA, "runlog")
_DATA_DIR = os.path.join(_RUNLOG_ROOT, "marathon", "data")

# Migrate from old location (marathon-runlog/data/) if it exists
_OLD_DATA_DIR = os.path.join(_APPDATA, "marathon-runlog", "data")
if os.path.isdir(_OLD_DATA_DIR) and not os.path.isdir(_DATA_DIR):
    print(f"[config] Migrating data: {_OLD_DATA_DIR} → {_DATA_DIR}")
    os.makedirs(os.path.dirname(_DATA_DIR), exist_ok=True)
    shutil.move(_OLD_DATA_DIR, _DATA_DIR)
    # Clean up empty old parent dir
    try:
        old_parent = os.path.join(_APPDATA, "marathon-runlog")
        if os.path.isdir(old_parent) and not os.listdir(old_parent):
            os.rmdir(old_parent)
    except Exception as e:
        print(f"[config] Could not clean up old data directory: {e}")

    # Update any absolute paths stored in the database
    _migrated_db = os.path.join(_DATA_DIR, "runlog.db")
    if os.path.exists(_migrated_db):
        try:
            import sqlite3
            _conn = sqlite3.connect(_migrated_db)
            _old_str = os.path.join(_APPDATA, "marathon-runlog", "data").replace("/", "\\")
            _new_str = _DATA_DIR.replace("/", "\\")
            _conn.execute(
                "UPDATE runs SET recording_path = REPLACE(recording_path, ?, ?) WHERE recording_path LIKE ?",
                (_old_str, _new_str, f"%{_old_str}%")
            )
            _conn.commit()
            rows = _conn.total_changes
            _conn.close()
            if rows:
                print(f"[config] Updated {rows} recording path(s) in database")
        except Exception as e:
            print(f"[config] Path migration warning: {e}")

os.makedirs(_DATA_DIR, exist_ok=True)
_DB_PATH = os.path.join(_DATA_DIR, "runlog.db").replace("\\", "/")
_SETTINGS_FILE = os.path.join(_RUNLOG_ROOT, "settings.json")  # Global settings, not per-game


def _get_storage_path() -> str:
    """
    Get the storage path for large media files (recordings, clips, screenshots).

    Reads 'storage_path' from settings.json. If set, media goes to that directory.
    If not set (default), media stays in the standard AppData data directory.

    The DB and settings.json always stay in AppData — only large files move.
    """
    if os.path.exists(_SETTINGS_FILE):
        try:
            with open(_SETTINGS_FILE, "r") as f:
                data = json.load(f)
            custom = data.get("storage_path", "")
            if custom and os.path.isdir(custom):
                return custom
        except (json.JSONDecodeError, OSError):
            pass
    return _DATA_DIR


# Resolved storage path — importable by other modules
_STORAGE_DIR = _get_storage_path()


def _load_saved_api_key() -> str:
    """Load API key from settings.json if it exists."""
    if os.path.exists(_SETTINGS_FILE):
        try:
            with open(_SETTINGS_FILE, "r") as f:
                data = json.load(f)
            return data.get("anthropic_api_key", "")
        except (json.JSONDecodeError, OSError):
            return ""
    return ""


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    database_url: str = f"sqlite:///{_DB_PATH}"
    media_upload_dir: str = os.path.join(_DATA_DIR, "media_uploads")

    class Config:
        env_file = ".env"


settings = Settings()

# Saved key (from Settings UI) takes priority over .env
_saved_key = _load_saved_api_key()
if _saved_key:
    settings.anthropic_api_key = _saved_key

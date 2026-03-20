import json
import os
import shutil
from pydantic_settings import BaseSettings

# Data location: AppData/Roaming/runlog/marathon/data/
# Structure: runlog/<game>/data/ — supports future multi-game expansion
_APPDATA = os.environ.get("APPDATA", os.path.expanduser("~"))
_DATA_DIR = os.path.join(_APPDATA, "runlog", "marathon", "data")

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
    except Exception:
        pass

os.makedirs(_DATA_DIR, exist_ok=True)
_DB_PATH = os.path.join(_DATA_DIR, "runlog.db").replace("\\", "/")
_SETTINGS_FILE = os.path.join(_DATA_DIR, "settings.json")


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

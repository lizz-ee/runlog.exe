import json
import os
from pydantic_settings import BaseSettings

# Single database location: AppData/Roaming/marathon-runlog/data/
# This ensures dev mode, release mode, and CLI all use the same DB.
_DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "marathon-runlog", "data")
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

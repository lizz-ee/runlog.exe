import os
from pydantic_settings import BaseSettings

# Single database location: AppData/Roaming/marathon-runlog/data/
# This ensures dev mode, release mode, and CLI all use the same DB.
_DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "marathon-runlog", "data")
os.makedirs(_DATA_DIR, exist_ok=True)
_DB_PATH = os.path.join(_DATA_DIR, "runlog.db").replace("\\", "/")


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    database_url: str = f"sqlite:///{_DB_PATH}"
    media_upload_dir: str = os.path.join(_DATA_DIR, "media_uploads")

    class Config:
        env_file = ".env"


settings = Settings()

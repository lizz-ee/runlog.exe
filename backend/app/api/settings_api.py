import json
import os
import subprocess

import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import _DATA_DIR, _STORAGE_DIR, _SETTINGS_FILE, settings
from .. import ai_client

router = APIRouter()


def _load_settings() -> dict:
    if os.path.exists(_SETTINGS_FILE):
        with open(_SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {}


def _save_settings(data: dict) -> None:
    with open(_SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


class ApiKeyUpdate(BaseModel):
    api_key: str


class ConfigUpdate(BaseModel):
    key: str
    value: str | int | float | bool


# Defaults for all configurable settings
DEFAULTS = {
    "encoder": "hevc",
    "bitrate": 50,         # Mbps
    "fps": 60,
    "p1_workers": 4,
    "p2_workers": 2,
    "auto_p1": True,       # Auto-run Phase 1 (stats extraction) when recording finishes
    "auto_p2": True,       # Auto-run Phase 2 (narrative + clips) when Phase 1 finishes
    "processor_mode": "alpha",  # "alpha" (local), "hybrid" (local + Claude fallback), "claude" (API/CLI only)
    "auth_mode": "api",    # "api" or "cli"
    "model": "sonnet",     # "sonnet" or "haiku"
    "uplink_model": "haiku",  # "haiku" or "sonnet" for UPLINK chat/briefing
}


def get_config_value(key: str):
    """Get a config value from settings.json, falling back to defaults."""
    saved = _load_settings()
    return saved.get(key, DEFAULTS.get(key))


@router.get("/")
def get_settings():
    """Get current settings. API key is masked for security."""
    saved = _load_settings()
    key = saved.get("anthropic_api_key", "") or settings.anthropic_api_key
    masked = ""
    if key:
        masked = key[:7] + "•••••" + key[-4:] if len(key) > 11 else "••••••••"

    cli_found = ai_client.find_cli() is not None

    return {
        "has_api_key": bool(key),
        "api_key_masked": masked,
        "api_key_source": "settings" if saved.get("anthropic_api_key") else ("env" if settings.anthropic_api_key else "none"),
        "cli_available": cli_found,
        # Config values
        "encoder": saved.get("encoder", DEFAULTS["encoder"]),
        "bitrate": saved.get("bitrate", DEFAULTS["bitrate"]),
        "fps": saved.get("fps", DEFAULTS["fps"]),
        "p1_workers": saved.get("p1_workers", DEFAULTS["p1_workers"]),
        "p2_workers": saved.get("p2_workers", DEFAULTS["p2_workers"]),
        "auto_p1": saved.get("auto_p1", DEFAULTS["auto_p1"]),
        "auto_p2": saved.get("auto_p2", DEFAULTS["auto_p2"]),
        "processor_mode": saved.get("processor_mode", DEFAULTS["processor_mode"]),
        "auth_mode": saved.get("auth_mode", DEFAULTS["auth_mode"]),
        "model": saved.get("model", DEFAULTS["model"]),
        "uplink_model": saved.get("uplink_model", DEFAULTS["uplink_model"]),
        # Storage
        "storage_path": saved.get("storage_path", ""),
        "storage_path_active": _STORAGE_DIR,
        "storage_path_default": _DATA_DIR,
    }


@router.post("/api-key")
def set_api_key(body: ApiKeyUpdate):
    """Save the Anthropic API key."""
    key = body.api_key.strip()
    if not key.startswith("sk-ant-"):
        raise HTTPException(status_code=400, detail="Invalid API key format. Key should start with 'sk-ant-'")

    saved = _load_settings()
    saved["anthropic_api_key"] = key
    _save_settings(saved)

    # Update the runtime config so it takes effect immediately
    settings.anthropic_api_key = key

    return {"status": "saved"}


@router.post("/api-key/test")
def test_api_key_endpoint(body: ApiKeyUpdate):
    """Test an API key by making a minimal API call."""
    key = body.api_key.strip()
    try:
        return ai_client.test_api_key(key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid API key")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Connection error: {str(e)}")


@router.delete("/api-key")
def remove_api_key():
    """Remove the saved API key."""
    saved = _load_settings()
    saved.pop("anthropic_api_key", None)
    _save_settings(saved)
    settings.anthropic_api_key = ""
    return {"status": "removed"}


@router.post("/config")
def update_config(body: ConfigUpdate):
    """Update a single config value."""
    allowed_keys = set(DEFAULTS.keys()) | {"storage_path"}
    if body.key not in allowed_keys:
        raise HTTPException(status_code=400, detail=f"Unknown config key: {body.key}")
    if body.key in ("model", "uplink_model") and body.value not in ("sonnet", "haiku"):
        raise HTTPException(status_code=400, detail=f"Invalid model: {body.value}. Must be 'sonnet' or 'haiku'")
    if body.key == "encoder" and body.value not in ("hevc", "h264"):
        raise HTTPException(status_code=400, detail=f"Invalid encoder: {body.value}. Must be 'hevc' or 'h264'")
    if body.key == "processor_mode" and body.value not in ("alpha", "hybrid", "claude"):
        raise HTTPException(status_code=400, detail=f"Invalid processor_mode: {body.value}. Must be 'alpha', 'hybrid', or 'claude'")

    # Special handling for storage_path — validate directory exists
    if body.key == "storage_path":
        path = str(body.value).strip()
        if path:
            os.makedirs(path, exist_ok=True)
            if not os.path.isdir(path):
                raise HTTPException(status_code=400, detail=f"Cannot create directory: {path}")
            # Create subdirectories
            os.makedirs(os.path.join(path, "recordings"), exist_ok=True)
            os.makedirs(os.path.join(path, "clips"), exist_ok=True)

    saved = _load_settings()
    saved[body.key] = body.value
    _save_settings(saved)
    return {"status": "saved", "key": body.key, "value": body.value,
            "note": "Restart the app for storage_path changes to take effect." if body.key == "storage_path" else None}


@router.get("/browse-folder")
def browse_folder():
    """Open a native Windows folder picker dialog and return the selected path."""
    import threading

    result = {"path": None}

    def _pick():
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Select storage folder")
        root.destroy()
        if path:
            result["path"] = os.path.normpath(path)

    # tkinter must run on its own thread to avoid blocking the event loop
    t = threading.Thread(target=_pick)
    t.start()
    t.join(timeout=120)

    if result["path"]:
        return {"path": result["path"]}
    return {"path": None}


class MigrateStorageRequest(BaseModel):
    new_path: str


@router.post("/migrate-storage")
def migrate_storage(body: MigrateStorageRequest):
    """
    Migrate clips and recordings from current storage to a new directory.

    1. Creates directory structure at new path
    2. Moves all run_* folders from current clips/ to new clips/
    3. Moves recordings from current recordings/ to new recordings/
    4. Updates recording_path in DB for all moved runs
    5. Saves new storage_path to settings
    """
    import shutil
    import sqlite3

    new_path = body.new_path.strip()
    if not new_path:
        raise HTTPException(status_code=400, detail="new_path is required")

    # Create target directories
    new_clips = os.path.join(new_path, "clips")
    new_recordings = os.path.join(new_path, "recordings")
    try:
        os.makedirs(new_clips, exist_ok=True)
        os.makedirs(new_recordings, exist_ok=True)
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Cannot create directory: {e}")

    # Collect all source directories to check — AppData first, then current
    # storage dir (in case of re-migration between custom paths).
    source_dirs = [_DATA_DIR]
    if os.path.normpath(_STORAGE_DIR) != os.path.normpath(_DATA_DIR) \
       and os.path.normpath(_STORAGE_DIR) != os.path.normpath(new_path):
        source_dirs.append(_STORAGE_DIR)

    moved_runs = 0
    moved_recordings = 0
    errors = []

    for source in source_dirs:
        old_clips = os.path.join(source, "clips")
        old_recordings = os.path.join(source, "recordings")

        # Move clip run folders
        if os.path.isdir(old_clips):
            for item in os.listdir(old_clips):
                src = os.path.join(old_clips, item)
                dst = os.path.join(new_clips, item)
                if os.path.isdir(src) and not os.path.exists(dst):
                    try:
                        shutil.move(src, dst)
                        moved_runs += 1
                    except Exception as e:
                        errors.append(f"clips/{item}: {e}")

        # Move loose recordings
        if os.path.isdir(old_recordings):
            for item in os.listdir(old_recordings):
                src = os.path.join(old_recordings, item)
                dst = os.path.join(new_recordings, item)
                if os.path.isfile(src) and not os.path.exists(dst):
                    try:
                        shutil.move(src, dst)
                        moved_recordings += 1
                    except Exception as e:
                        errors.append(f"recordings/{item}: {e}")

    # Update recording_path in DB — replace all known source paths
    db_path = os.path.join(_DATA_DIR, "runlog.db")
    updated_rows = 0
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            new_clips_abs = os.path.abspath(new_clips)
            for source in source_dirs:
                old_clips_abs = os.path.abspath(os.path.join(source, "clips"))
                if old_clips_abs == new_clips_abs:
                    continue
                # Backslash variant (Windows native)
                old_bs = old_clips_abs.replace("/", "\\")
                new_bs = new_clips_abs.replace("/", "\\")
                conn.execute(
                    "UPDATE runs SET recording_path = REPLACE(recording_path, ?, ?) WHERE recording_path LIKE ?",
                    (old_bs, new_bs, f"%{old_bs}%")
                )
                # Forward-slash variant
                old_fs = old_bs.replace("\\", "/")
                new_fs = new_bs.replace("\\", "/")
                conn.execute(
                    "UPDATE runs SET recording_path = REPLACE(recording_path, ?, ?) WHERE recording_path LIKE ?",
                    (old_fs, new_fs, f"%{old_fs}%")
                )
            conn.commit()
            updated_rows = conn.total_changes
            conn.close()
        except Exception as e:
            errors.append(f"DB update: {e}")

    # Save new storage_path to settings
    saved = _load_settings()
    saved["storage_path"] = new_path
    _save_settings(saved)

    return {
        "status": "migrated",
        "moved_runs": moved_runs,
        "moved_recordings": moved_recordings,
        "db_paths_updated": updated_rows,
        "errors": errors if errors else None,
        "note": "Restart the app for changes to take full effect.",
    }


@router.get("/cli-status")
def check_cli_status():
    """Check if Claude CLI is installed and actually authenticated."""
    return ai_client.cli_status()


@router.post("/cli-login")
def cli_login_endpoint():
    """Launch `claude auth login` to open browser for OAuth."""
    try:
        return ai_client.cli_login()
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/cli-logout")
def cli_logout_endpoint():
    """Log out of Claude CLI."""
    try:
        return ai_client.cli_logout()
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cli-update")
def cli_update_endpoint():
    """Update Claude CLI to latest version via npm."""
    try:
        return ai_client.cli_update()
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Update timed out")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")


@router.get("/cli-latest-version")
def cli_latest_version_endpoint():
    """Check the latest published version of Claude CLI from npm."""
    latest = ai_client.cli_latest_version()
    if latest:
        return {"latest": latest}
    raise HTTPException(status_code=500, detail="Could not fetch latest version")

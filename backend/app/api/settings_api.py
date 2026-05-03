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
        try:
            with open(_SETTINGS_FILE, "r") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError) as e:
            print(f"[settings] Could not read settings file: {e}")
    return {}


def _save_settings(data: dict) -> None:
    os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
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
    "resolution": "native",  # native | 1440p | 1080p | 720p
    "audio_capture": True,  # Sidecar loopback audio capture for Alpha P2/clips
    "p1_workers": 4,
    "p2_workers": 1,
    "auto_p1": True,       # Auto-run Phase 1 (stats extraction) when recording finishes
    "auto_p2": True,       # Auto-run Phase 2 (narrative + clips) when Phase 1 finishes
    "pause_processing_while_game_running": True,
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
        "resolution": saved.get("resolution", DEFAULTS["resolution"]),
        "audio_capture": saved.get("audio_capture", DEFAULTS["audio_capture"]),
        "p1_workers": saved.get("p1_workers", DEFAULTS["p1_workers"]),
        "p2_workers": saved.get("p2_workers", DEFAULTS["p2_workers"]),
        "auto_p1": saved.get("auto_p1", DEFAULTS["auto_p1"]),
        "auto_p2": saved.get("auto_p2", DEFAULTS["auto_p2"]),
        "pause_processing_while_game_running": saved.get("pause_processing_while_game_running", DEFAULTS["pause_processing_while_game_running"]),
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
        print(f"[settings] API key validation error: {e}")
        raise HTTPException(status_code=400, detail="Invalid API key format")
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=401, detail="Invalid API key")
    except Exception as e:
        print(f"[settings] API key test failed: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="Could not verify API key")


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
    value = body.value
    if body.key in ("model", "uplink_model") and value not in ("sonnet", "haiku"):
        raise HTTPException(status_code=400, detail=f"Invalid model: {value}. Must be 'sonnet' or 'haiku'")
    if body.key == "encoder" and value not in ("hevc", "h264"):
        raise HTTPException(status_code=400, detail=f"Invalid encoder: {value}. Must be 'hevc' or 'h264'")
    if body.key == "resolution" and value not in ("native", "1440p", "1080p", "720p"):
        raise HTTPException(status_code=400, detail=f"Invalid resolution: {value}. Must be 'native', '1440p', '1080p', or '720p'")
    if body.key == "processor_mode" and value not in ("alpha", "hybrid", "claude"):
        raise HTTPException(status_code=400, detail=f"Invalid processor_mode: {value}. Must be 'alpha', 'hybrid', or 'claude'")
    if body.key == "auth_mode" and value not in ("api", "cli"):
        raise HTTPException(status_code=400, detail=f"Invalid auth_mode: {value}. Must be 'api' or 'cli'")

    numeric_limits = {
        "bitrate": (10, 100),
        "fps": (30, 60),
        "p1_workers": (1, 8),
        "p2_workers": (1, 4),
    }
    if body.key in numeric_limits:
        if isinstance(value, bool):
            raise HTTPException(status_code=400, detail=f"Invalid {body.key}: must be a number")
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Invalid {body.key}: must be a number")
        min_value, max_value = numeric_limits[body.key]
        if value < min_value or value > max_value:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {body.key}: must be between {min_value} and {max_value}",
            )
        if body.key == "fps" and value not in (30, 60):
            raise HTTPException(status_code=400, detail="Invalid fps: must be 30 or 60")

    if body.key in ("auto_p1", "auto_p2", "pause_processing_while_game_running") and not isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"Invalid {body.key}: must be true or false")

    # Special handling for storage_path — validate directory exists
    if body.key == "storage_path":
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail="Invalid storage_path: must be a string")
        path = str(value).strip()
        if path:
            os.makedirs(path, exist_ok=True)
            if not os.path.isdir(path):
                raise HTTPException(status_code=400, detail=f"Cannot create directory: {path}")
            # Create subdirectories
            os.makedirs(os.path.join(path, "recordings"), exist_ok=True)
            os.makedirs(os.path.join(path, "clips"), exist_ok=True)
        value = path

    saved = _load_settings()
    saved[body.key] = value
    _save_settings(saved)

    # Capture engine settings that do not require recreating worker pools can
    # take effect immediately when the engine is already running.
    if body.key == "pause_processing_while_game_running":
        try:
            from . import capture_api
            if capture_api._engine is not None:
                capture_api._engine.set_pause_processing_while_game_running(bool(value))
        except Exception:
            pass

    # The recorder's WGC capture rate cap is set at process startup from the
    # fps env var, so an fps change has to bounce the recorder to take effect.
    # Skip the bounce while a recording is in progress — would cut the run.
    # Instead flag a deferred restart that the capture engine performs in
    # _stop_recording() once the in-flight run is finalized.
    note = None
    if body.key == "fps":
        try:
            from . import capture_api
            engine = capture_api._engine
            if engine is not None and engine._recorder.is_running:
                if engine._recording or engine._recorder.recording:
                    engine._recorder.fps_restart_pending = True
                    note = "FPS change saved — the recorder will restart automatically after the current recording finishes."
                else:
                    engine._recorder.stop()
                    engine._recorder.start()
        except Exception as e:
            print(f"[settings] Recorder restart on fps change failed: {e}")
    elif body.key == "storage_path":
        note = "Restart the app for storage_path changes to take effect."

    return {"status": "saved", "key": body.key, "value": value, "note": note}


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
        print(f"[settings] Cannot create directory: {e}")
        raise HTTPException(status_code=400, detail="Cannot create directory at the specified path")

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
        print(f"[settings] CLI login failed: {e}")
        raise HTTPException(status_code=404, detail="Claude CLI not found")


@router.post("/cli-logout")
def cli_logout_endpoint():
    """Log out of Claude CLI."""
    try:
        return ai_client.cli_logout()
    except RuntimeError as e:
        print(f"[settings] CLI logout failed: {e}")
        raise HTTPException(status_code=500, detail="Logout failed")


@router.post("/cli-update")
def cli_update_endpoint():
    """Update Claude CLI to latest version via npm."""
    try:
        return ai_client.cli_update()
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Update timed out")
    except RuntimeError as e:
        print(f"[settings] CLI update RuntimeError: {e}")
        raise HTTPException(status_code=500, detail="CLI update failed")
    except Exception as e:
        print(f"[settings] CLI update error: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail="CLI update failed")


@router.get("/cli-latest-version")
def cli_latest_version_endpoint():
    """Check the latest published version of Claude CLI from npm."""
    latest = ai_client.cli_latest_version()
    if latest:
        return {"latest": latest}
    raise HTTPException(status_code=500, detail="Could not fetch latest version")

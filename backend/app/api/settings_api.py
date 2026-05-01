import json
import os
import subprocess

import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import _DATA_DIR, _STORAGE_DIR, _SETTINGS_FILE, settings
from .. import ai_client
from ..alpha.health import alpha_health, clear_alpha_health_cache

router = APIRouter()


def _load_settings() -> dict:
    if os.path.exists(_SETTINGS_FILE):
        try:
            with open(_SETTINGS_FILE, "r") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_settings(data: dict) -> None:
    os.makedirs(os.path.dirname(_SETTINGS_FILE), exist_ok=True)
    tmp_file = f"{_SETTINGS_FILE}.tmp"
    with open(tmp_file, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_file, _SETTINGS_FILE)


class ApiKeyUpdate(BaseModel):
    api_key: str


class ConfigUpdate(BaseModel):
    key: str
    value: str | int | float | bool


# Defaults for all configurable settings
DEFAULTS = {
    "quality_preset": "balanced",
    "encoder": "hevc",
    "bitrate": 50,         # Mbps
    "fps": 60,
    "p1_workers": 1,
    "p2_workers": 1,
    "auto_p1": True,       # Auto-run Phase 1 (stats extraction) when recording finishes
    "auto_p2": True,       # Auto-run Phase 2 (narrative + clips) when Phase 1 finishes
    "processor_mode": "alpha",  # "alpha" (local), "hybrid" (local + Claude fallback), "claude" (API/CLI only)
    "auth_mode": "api",    # "api" or "cli"
    "model": "sonnet",     # "sonnet" or "haiku"
    "uplink_model": "haiku",  # "haiku" or "sonnet" for UPLINK chat/briefing
}

QUALITY_PRESETS = {
    "zero_impact": {
        "bitrate_30": 18,
        "bitrate_60": 28,
        "p1_workers": 1,
        "p2_workers": 1,
        "auto_p1": True,
        "auto_p2": True,
        "post_recording_grace_seconds": 30,
        "post_processing_profile": "light",
    },
    "balanced": {
        "bitrate_30": 35,
        "bitrate_60": 50,
        "p1_workers": 1,
        "p2_workers": 1,
        "auto_p1": True,
        "auto_p2": True,
        "post_recording_grace_seconds": 20,
        "post_processing_profile": "balanced",
    },
    "archive": {
        "bitrate_30": 60,
        "bitrate_60": 85,
        "p1_workers": 2,
        "p2_workers": 2,
        "auto_p1": True,
        "auto_p2": True,
        "post_recording_grace_seconds": 10,
        "post_processing_profile": "archive",
    },
}

PRESET_DERIVED_KEYS = {
    "bitrate",
    "p1_workers",
    "p2_workers",
    "auto_p1",
    "auto_p2",
    "post_recording_grace_seconds",
    "post_processing_profile",
}


def _saved_fps(saved: dict) -> int:
    try:
        value = int(saved.get("fps", DEFAULTS["fps"]))
    except (TypeError, ValueError):
        return DEFAULTS["fps"]
    return value if value in (30, 60) else DEFAULTS["fps"]


def _saved_quality_preset(saved: dict) -> str:
    value = saved.get("quality_preset", DEFAULTS["quality_preset"])
    return value if value in QUALITY_PRESETS else DEFAULTS["quality_preset"]


def _effective_preset_values(saved: dict) -> dict:
    preset = _saved_quality_preset(saved)
    fps = _saved_fps(saved)
    preset_values = QUALITY_PRESETS[preset]
    return {
        "quality_preset": preset,
        "bitrate": preset_values["bitrate_30"] if fps == 30 else preset_values["bitrate_60"],
        "p1_workers": preset_values["p1_workers"],
        "p2_workers": preset_values["p2_workers"],
        "auto_p1": preset_values["auto_p1"],
        "auto_p2": preset_values["auto_p2"],
        "post_recording_grace_seconds": preset_values["post_recording_grace_seconds"],
        "post_processing_profile": preset_values["post_processing_profile"],
    }


def get_config_value(key: str):
    """Get a config value from settings.json, falling back to defaults."""
    saved = _load_settings()
    if key in PRESET_DERIVED_KEYS or key == "quality_preset":
        return _effective_preset_values(saved).get(key)
    return saved.get(key, DEFAULTS.get(key))


def _int_config(value: str | int | float | bool, key: str) -> int:
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{key} must be a number")
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"{key} must be a number")
    if isinstance(value, float) and not value.is_integer():
        raise HTTPException(status_code=400, detail=f"{key} must be a whole number")
    return numeric


@router.get("/")
def get_settings():
    """Get current settings. API key is masked for security."""
    saved = _load_settings()
    effective = _effective_preset_values(saved)
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
        "quality_preset": effective["quality_preset"],
        "encoder": saved.get("encoder", DEFAULTS["encoder"]),
        "bitrate": effective["bitrate"],
        "fps": _saved_fps(saved),
        "p1_workers": effective["p1_workers"],
        "p2_workers": effective["p2_workers"],
        "post_recording_grace_seconds": effective["post_recording_grace_seconds"],
        "post_processing_profile": effective["post_processing_profile"],
        "auto_p1": effective["auto_p1"],
        "auto_p2": effective["auto_p2"],
        "processor_mode": saved.get("processor_mode", DEFAULTS["processor_mode"]),
        "auth_mode": saved.get("auth_mode", DEFAULTS["auth_mode"]),
        "model": saved.get("model", DEFAULTS["model"]),
        "uplink_model": saved.get("uplink_model", DEFAULTS["uplink_model"]),
        # Storage
        "storage_path": saved.get("storage_path", ""),
        "storage_path_active": _STORAGE_DIR,
        "storage_path_default": _DATA_DIR,
    }


@router.get("/alpha-health")
def get_alpha_health(refresh: bool = False):
    """Return alpha mode runtime capability status."""
    if refresh:
        clear_alpha_health_cache()
    return alpha_health()


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
    if body.key == "quality_preset" and body.value not in QUALITY_PRESETS:
        allowed = ", ".join(sorted(QUALITY_PRESETS.keys()))
        raise HTTPException(status_code=400, detail=f"Invalid quality_preset: {body.value}. Must be one of: {allowed}")
    if body.key in ("model", "uplink_model") and body.value not in ("sonnet", "haiku"):
        raise HTTPException(status_code=400, detail=f"Invalid model: {body.value}. Must be 'sonnet' or 'haiku'")
    if body.key == "encoder" and body.value not in ("hevc", "h264"):
        raise HTTPException(status_code=400, detail=f"Invalid encoder: {body.value}. Must be 'hevc' or 'h264'")
    if body.key == "processor_mode" and body.value not in ("alpha", "hybrid", "claude"):
        raise HTTPException(status_code=400, detail=f"Invalid processor_mode: {body.value}. Must be 'alpha', 'hybrid', or 'claude'")
    if body.key == "auth_mode" and body.value not in ("api", "cli"):
        raise HTTPException(status_code=400, detail=f"Invalid auth_mode: {body.value}. Must be 'api' or 'cli'")
    if body.key in ("auto_p1", "auto_p2") and not isinstance(body.value, bool):
        raise HTTPException(status_code=400, detail=f"{body.key} must be a boolean")
    if body.key == "fps":
        fps = _int_config(body.value, "fps")
        if fps not in (30, 60):
            raise HTTPException(status_code=400, detail="fps must be 30 or 60")
        body.value = fps
    if body.key == "bitrate":
        bitrate = _int_config(body.value, "bitrate")
        if not (10 <= bitrate <= 100):
            raise HTTPException(status_code=400, detail="bitrate must be between 10 and 100 Mbps")
        body.value = bitrate
    if body.key == "p1_workers":
        p1_workers = _int_config(body.value, "p1_workers")
        if not (1 <= p1_workers <= 4):
            raise HTTPException(status_code=400, detail="p1_workers must be between 1 and 4")
        body.value = p1_workers
    if body.key == "p2_workers":
        p2_workers = _int_config(body.value, "p2_workers")
        if not (1 <= p2_workers <= 2):
            raise HTTPException(status_code=400, detail="p2_workers must be between 1 and 2")
        body.value = p2_workers

    # Special handling for storage_path — validate directory exists
    if body.key == "storage_path":
        target_path = os.path.abspath(str(body.value).strip())
        if str(body.value).strip():
            os.makedirs(target_path, exist_ok=True)
            if not os.path.isdir(target_path):
                raise HTTPException(status_code=400, detail=f"Cannot create directory: {target_path}")
            # Create subdirectories
            os.makedirs(os.path.join(target_path, "recordings"), exist_ok=True)
            os.makedirs(os.path.join(target_path, "clips"), exist_ok=True)
            body.value = target_path

    saved = _load_settings()
    saved[body.key] = body.value
    _save_settings(saved)
    if body.key in ("quality_preset", "p1_workers", "p2_workers", "auto_p1", "auto_p2"):
        try:
            from .capture_api import apply_runtime_config
            apply_runtime_config()
        except Exception as e:
            print(f"[settings] Runtime processing config reload failed: {e}")
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

    raw_new_path = body.new_path.strip()
    if not raw_new_path:
        raise HTTPException(status_code=400, detail="new_path is required")
    new_path = os.path.abspath(raw_new_path)
    for existing in {_DATA_DIR, _STORAGE_DIR}:
        existing_abs = os.path.abspath(existing)
        existing_norm = os.path.normcase(existing_abs)
        new_norm = os.path.normcase(new_path)
        try:
            common = os.path.commonpath([existing_norm, new_norm])
        except ValueError:
            continue
        if common == existing_norm and new_norm != existing_norm:
            raise HTTPException(status_code=400, detail="new_path cannot be inside existing RunLog storage")

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
    storage_norm = os.path.normcase(os.path.normpath(_STORAGE_DIR))
    data_norm = os.path.normcase(os.path.normpath(_DATA_DIR))
    target_norm = os.path.normcase(os.path.normpath(new_path))
    if storage_norm != data_norm and storage_norm != target_norm:
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

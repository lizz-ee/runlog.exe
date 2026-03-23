import json
import os
import subprocess

import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import _DATA_DIR, _SETTINGS_FILE, settings
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
        "auth_mode": saved.get("auth_mode", DEFAULTS["auth_mode"]),
        "model": saved.get("model", DEFAULTS["model"]),
        "uplink_model": saved.get("uplink_model", DEFAULTS["uplink_model"]),
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
    allowed_keys = set(DEFAULTS.keys())
    if body.key not in allowed_keys:
        raise HTTPException(status_code=400, detail=f"Unknown config key: {body.key}")
    if body.key in ("model", "uplink_model") and body.value not in ("sonnet", "haiku"):
        raise HTTPException(status_code=400, detail=f"Invalid model: {body.value}. Must be 'sonnet' or 'haiku'")
    if body.key == "encoder" and body.value not in ("hevc", "h264"):
        raise HTTPException(status_code=400, detail=f"Invalid encoder: {body.value}. Must be 'hevc' or 'h264'")
    saved = _load_settings()
    saved[body.key] = body.value
    _save_settings(saved)
    return {"status": "saved", "key": body.key, "value": body.value}


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

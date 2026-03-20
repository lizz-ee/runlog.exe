import json
import os

import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import _DATA_DIR, _SETTINGS_FILE, settings

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
        masked = key[:7] + "•" * (len(key) - 11) + key[-4:] if len(key) > 11 else "••••••••"

    # Check CLI availability
    import shutil
    cli_found = bool(shutil.which("claude"))
    if not cli_found:
        for candidate in [
            os.path.expanduser("~/.local/bin/claude"),
            os.path.expanduser("~/.local/bin/claude.exe"),
            os.path.expanduser("~/AppData/Local/Programs/claude/claude.exe"),
        ]:
            if os.path.isfile(candidate):
                cli_found = True
                break

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
def test_api_key(body: ApiKeyUpdate):
    """Test an API key by making a minimal API call."""
    key = body.api_key.strip()
    if not key.startswith("sk-ant-"):
        raise HTTPException(status_code=400, detail="Invalid API key format. Key should start with 'sk-ant-'")

    try:
        client = anthropic.Anthropic(api_key=key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": "Say OK"}],
        )
        return {"status": "valid", "response": message.content[0].text.strip()}
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
    saved = _load_settings()
    saved[body.key] = body.value
    _save_settings(saved)
    return {"status": "saved", "key": body.key, "value": body.value}


@router.get("/cli-status")
def check_cli_status():
    """Check if Claude CLI is installed and authenticated."""
    import shutil
    import subprocess

    cli_path = shutil.which("claude")
    if not cli_path:
        for candidate in [
            os.path.expanduser("~/.local/bin/claude"),
            os.path.expanduser("~/.local/bin/claude.exe"),
            os.path.expanduser("~/AppData/Local/Programs/claude/claude.exe"),
        ]:
            if os.path.isfile(candidate):
                cli_path = candidate
                break

    if not cli_path:
        return {"installed": False, "authenticated": False, "path": None}

    # Check if authenticated by running a quick version check
    try:
        result = subprocess.run(
            [cli_path, "--version"],
            capture_output=True, text=True, timeout=10,
        )
        installed = result.returncode == 0
    except Exception:
        installed = True  # binary exists, just couldn't run --version

    return {"installed": True, "authenticated": installed, "path": cli_path}

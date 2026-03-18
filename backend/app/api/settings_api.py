import json
import os

import anthropic
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import _DATA_DIR, settings

router = APIRouter()

_SETTINGS_FILE = os.path.join(_DATA_DIR, "settings.json")


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


@router.get("/")
def get_settings():
    """Get current settings. API key is masked for security."""
    saved = _load_settings()
    key = saved.get("anthropic_api_key", "") or settings.anthropic_api_key
    masked = ""
    if key:
        masked = key[:7] + "•" * (len(key) - 11) + key[-4:] if len(key) > 11 else "••••••••"
    return {
        "has_api_key": bool(key),
        "api_key_masked": masked,
        "api_key_source": "settings" if saved.get("anthropic_api_key") else ("env" if settings.anthropic_api_key else "none"),
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

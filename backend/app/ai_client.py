"""
Centralized AI client — all Claude API and CLI calls go through here.

Provides:
- CLI binary discovery and environment setup
- CLI management (status, login, logout, update)
- Prompt execution via CLI or API
- Auth routing (CLI vs API decision)
- Model configuration
- Auth failure detection

Future: Ollama / local model support will be added here.
"""

import base64
import json
import os
import shutil
import subprocess
from typing import Generator

import anthropic

from .config import settings


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Binary Management
# ═══════════════════════════════════════════════════════════════════════════════

def find_cli() -> str | None:
    """Find the Claude CLI binary. Returns the path or None."""
    cli_path = shutil.which("claude")
    if cli_path:
        return cli_path

    for candidate in [
        os.path.expanduser("~/.local/bin/claude"),
        os.path.expanduser("~/.local/bin/claude.exe"),
        os.path.expanduser("~/AppData/Local/Programs/claude/claude.exe"),
    ]:
        if os.path.isfile(candidate):
            return candidate

    return None


def cli_env() -> dict:
    """Build environment dict for CLI subprocesses with HOME set correctly.

    The Electron-packaged app may not inherit HOME/USERPROFILE,
    causing the CLI to fail to find its auth credentials.
    """
    env = os.environ.copy()
    home = os.path.expanduser("~")
    env.setdefault("HOME", home)
    env.setdefault("USERPROFILE", home)
    return env


def cli_status() -> dict:
    """Check if Claude CLI is installed, authenticated, and get version.

    Returns: {installed: bool, authenticated: bool, path: str|None, version: str|None}
    """
    cli_path = find_cli()
    if not cli_path:
        return {"installed": False, "authenticated": False, "path": None, "version": None}

    # Verify the binary runs
    env = cli_env()
    version = None
    try:
        result = subprocess.run(
            [cli_path, "--version"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        if result.returncode != 0:
            return {"installed": False, "authenticated": False, "path": cli_path, "version": None}
        version = result.stdout.strip().split(" ")[0]
    except Exception:
        return {"installed": False, "authenticated": False, "path": cli_path, "version": None}

    # Check actual authentication via `claude auth status`
    authenticated = False
    try:
        auth_result = subprocess.run(
            [cli_path, "auth", "status"],
            capture_output=True, text=True, timeout=10, env=env,
        )
        if auth_result.returncode == 0 and auth_result.stdout.strip():
            auth_data = json.loads(auth_result.stdout.strip())
            authenticated = auth_data.get("loggedIn", False)
    except json.JSONDecodeError:
        print(f"[ai_client] CLI auth status returned non-JSON: {auth_result.stdout[:100] if auth_result.stdout else 'empty'}")
    except Exception as e:
        print(f"[ai_client] CLI auth status check failed: {e}")

    return {"installed": True, "authenticated": authenticated, "path": cli_path, "version": version}


def cli_login() -> dict:
    """Launch `claude auth login` to open browser for OAuth. Non-blocking."""
    cli_path = find_cli()
    if not cli_path:
        raise RuntimeError("Claude CLI not found")

    subprocess.Popen(
        [cli_path, "auth", "login"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=cli_env(),
    )
    return {"status": "login_started"}


def cli_logout() -> dict:
    """Log out of Claude CLI."""
    cli_path = find_cli()
    if not cli_path:
        raise RuntimeError("Claude CLI not found")

    result = subprocess.run(
        [cli_path, "auth", "logout"],
        capture_output=True, text=True, timeout=10, env=cli_env(),
    )
    if result.returncode == 0:
        return {"status": "logged_out"}
    raise RuntimeError(f"Logout failed: {result.stderr.strip()}")


def cli_update() -> dict:
    """Update Claude CLI to latest version via npm. Returns new version."""
    result = subprocess.run(
        ["npm", "install", "-g", "@anthropic-ai/claude-code"],
        capture_output=True, text=True, timeout=120,
        shell=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Update failed: {result.stderr.strip()}")

    # Get new version
    cli_path = find_cli()
    new_version = None
    if cli_path:
        try:
            ver_result = subprocess.run(
                [cli_path, "--version"],
                capture_output=True, text=True, timeout=10, env=cli_env(),
            )
            new_version = ver_result.stdout.strip().split(" ")[0]
        except Exception:
            pass

    return {"status": "updated", "version": new_version}


def cli_latest_version() -> str | None:
    """Check the latest published version from npm registry."""
    try:
        result = subprocess.run(
            ["npm", "view", "@anthropic-ai/claude-code", "version"],
            capture_output=True, text=True, timeout=15,
            shell=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Model Configuration
# ═══════════════════════════════════════════════════════════════════════════════

MODEL_HAIKU_API = "claude-haiku-4-5-20251001"
MODEL_SONNET_API = "claude-sonnet-4-6"


def get_model_config(purpose: str = "capture") -> dict:
    """Get configured model names for API and CLI.

    Args:
        purpose: "capture" for Phase 1/2 analysis, "uplink" for chat/briefings.

    Returns: {"api": "claude-sonnet-4-6", "cli": "sonnet"}
    """
    try:
        from .api.settings_api import get_config_value
        if purpose == "uplink":
            model = get_config_value("uplink_model") or get_config_value("model") or "haiku"
        else:
            model = get_config_value("model") or "sonnet"
    except Exception:
        model = "haiku" if purpose == "uplink" else "sonnet"

    if model == "haiku":
        return {"api": MODEL_HAIKU_API, "cli": "haiku"}
    return {"api": MODEL_SONNET_API, "cli": "sonnet"}


# ═══════════════════════════════════════════════════════════════════════════════
# Auth Failure Detection
# ═══════════════════════════════════════════════════════════════════════════════

_AUTH_FAILURES = ["not logged in", "please run /login", "authentication required"]


def is_auth_failure(text: str) -> bool:
    """Check if CLI output indicates an authentication failure."""
    lower = text.lower()
    return any(phrase in lower for phrase in _AUTH_FAILURES)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Prompt Execution
# ═══════════════════════════════════════════════════════════════════════════════

def run_cli_prompt(
    prompt: str,
    *,
    model: str | None = None,
    purpose: str = "capture",
    work_dir: str | None = None,
    allowed_tools: list[str] | None = None,
    timeout: int = 300,
    dangerously_skip_permissions: bool = False,
) -> str:
    """Execute a prompt via the Claude CLI. Blocks until complete.

    Args:
        prompt: The full prompt text.
        model: Override model name (e.g. "haiku", "sonnet"). If None, uses config.
        purpose: "capture" or "uplink" — determines default model.
        work_dir: Directory to grant CLI file access to (--add-dir).
        allowed_tools: List of allowed tools (e.g. ["Read"]).
        timeout: Max seconds to wait.
        dangerously_skip_permissions: Pass --dangerously-skip-permissions flag.

    Returns: CLI stdout as string.
    Raises: RuntimeError on failure.
    """
    cli_path = find_cli()
    if not cli_path:
        raise RuntimeError("Claude CLI not found")

    if model is None:
        model = get_model_config(purpose)["cli"]

    cmd = [cli_path, "-p", prompt, "--model", model]
    if dangerously_skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    if work_dir:
        cmd.extend(["--add-dir", work_dir])
    if allowed_tools:
        cmd.extend(["--allowedTools"] + allowed_tools)

    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=cli_env(),
    )

    output_lines = []
    try:
        for line in iter(proc.stdout.readline, b''):
            decoded = line.decode("utf-8", errors="replace").rstrip()
            if decoded:
                output_lines.append(decoded)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError(f"CLI timed out after {timeout}s")

    result = "\n".join(output_lines).strip()

    if is_auth_failure(result):
        raise RuntimeError("Claude CLI is not authenticated. Go to SYS.CONFIG and click LOGIN, or run `claude auth login` in your terminal.")

    return result


async def run_cli_prompt_async(
    prompt: str,
    *,
    model: str | None = None,
    purpose: str = "capture",
    work_dir: str | None = None,
    allowed_tools: list[str] | None = None,
    timeout: int = 300,
) -> str:
    """Async wrapper for run_cli_prompt — runs in a thread executor."""
    import asyncio
    import functools

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        functools.partial(
            run_cli_prompt,
            prompt,
            model=model,
            purpose=purpose,
            work_dir=work_dir,
            allowed_tools=allowed_tools,
            timeout=timeout,
        ),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# API Prompt Execution
# ═══════════════════════════════════════════════════════════════════════════════

def run_api_prompt(
    prompt: str,
    *,
    images: list[str] | None = None,
    video_path: str | None = None,
    model: str | None = None,
    purpose: str = "capture",
    max_tokens: int = 4096,
    system: str | None = None,
    tools: list | None = None,
    messages: list | None = None,
) -> str | object:
    """Execute a prompt via the Claude API. Blocks until complete.

    Args:
        prompt: The text prompt.
        images: List of image file paths to include.
        video_path: Path to a video file to include.
        model: Override model ID. If None, uses config.
        purpose: "capture" or "uplink" — determines default model.
        max_tokens: Maximum response tokens.
        system: System prompt (optional).
        tools: Tool definitions for tool use (optional).
        messages: Full messages array (overrides prompt/images/video if provided).

    Returns: Response text as string, or full response object if tools are provided.
    """
    if not settings.anthropic_api_key:
        raise RuntimeError("No API key configured")

    if model is None:
        model = get_model_config(purpose)["api"]

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Build messages if not provided directly
    if messages is None:
        content = []

        if images:
            for path in images:
                with open(path, "rb") as f:
                    data = f.read()
                ext = path.split(".")[-1].lower()
                media_type = f"image/{ext}" if ext in ("png", "jpeg", "jpg", "gif", "webp") else "image/png"
                if ext == "jpg":
                    media_type = "image/jpeg"
                b64 = base64.b64encode(data).decode("utf-8")
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64},
                })

        if video_path:
            with open(video_path, "rb") as f:
                video_data = base64.b64encode(f.read()).decode("utf-8")
            content.append({
                "type": "video",
                "source": {"type": "base64", "media_type": "video/mp4", "data": video_data},
            })

        content.append({"type": "text", "text": prompt})
        messages = [{"role": "user", "content": content}]

    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools

    response = client.messages.create(**kwargs)

    # If tools are defined, return the full response for the caller to handle
    if tools:
        return response

    return response.content[0].text.strip()


def test_api_key(key: str) -> dict:
    """Test an API key by making a minimal API call.

    Returns: {"status": "valid", "response": "..."} or raises.
    """
    if not key.startswith("sk-ant-"):
        raise ValueError("Invalid API key format. Key should start with 'sk-ant-'")

    client = anthropic.Anthropic(api_key=key)
    message = client.messages.create(
        model=MODEL_HAIKU_API,
        max_tokens=10,
        messages=[{"role": "user", "content": "Say OK"}],
    )
    return {"status": "valid", "response": message.content[0].text.strip()}


# ═══════════════════════════════════════════════════════════════════════════════
# Auth Routing
# ═══════════════════════════════════════════════════════════════════════════════

def _get_auth_mode() -> str:
    """Get the user's preferred auth mode from settings. Returns 'api' or 'cli'."""
    try:
        from .api.settings_api import get_config_value
        return get_config_value("auth_mode") or "api"
    except Exception:
        return "api"


def has_any_auth() -> bool:
    """Check if any authentication method is available."""
    if settings.anthropic_api_key:
        return True
    return find_cli() is not None


def prefer_cli() -> bool:
    """Returns True if CLI should be used (based on user toggle + availability).

    Priority: user's auth_mode setting > availability fallback.
    """
    mode = _get_auth_mode()
    if mode == "cli":
        # User prefers CLI — use it if available, else fall back to API
        return find_cli() is not None
    else:
        # User prefers API — only use CLI if no API key
        if settings.anthropic_api_key:
            return False
        return find_cli() is not None


def prefer_api() -> bool:
    """Returns True if API should be used (based on user toggle + availability).

    Priority: user's auth_mode setting > availability fallback.
    """
    mode = _get_auth_mode()
    if mode == "api":
        # User prefers API — use it if available, else fall back to CLI
        return bool(settings.anthropic_api_key)
    else:
        # User prefers CLI — only use API if no CLI
        if find_cli() is not None:
            return False
        return bool(settings.anthropic_api_key)

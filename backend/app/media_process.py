"""Helpers for launching background media tools without competing with gameplay."""

import os
import subprocess
from typing import Any

_CREATE_NO_WINDOW = 0x08000000
_IDLE_PRIORITY_CLASS = 0x00000040
_BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


def _priority_flag(priority: str) -> int:
    if priority == "below_normal":
        return _BELOW_NORMAL_PRIORITY_CLASS
    return _IDLE_PRIORITY_CLASS


def _media_creationflags(priority: str) -> int:
    if os.name != "nt":
        return 0
    return _CREATE_NO_WINDOW | _priority_flag(priority)


def _apply_background_priority(kwargs: dict[str, Any], priority: str) -> dict[str, Any]:
    if os.name == "nt":
        kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | _media_creationflags(priority)
    return kwargs


def run_media(cmd: list[str], *, priority: str = "idle", **kwargs: Any) -> subprocess.CompletedProcess:
    """Run ffmpeg/ffprobe-style media work at low Windows scheduling priority."""
    _apply_background_priority(kwargs, priority)
    return subprocess.run(cmd, **kwargs)


def popen_background(cmd: list[str], *, priority: str = "below_normal", **kwargs: Any) -> subprocess.Popen:
    """Launch a background processor so any child tools inherit a lower priority."""
    _apply_background_priority(kwargs, priority)
    return subprocess.Popen(cmd, **kwargs)

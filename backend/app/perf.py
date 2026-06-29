"""
perf.py — Windows process/thread QoS helpers for keeping runlog's background
work (live OCR, Phase 1/2 stats + video processing, helper ffmpeg processes)
OFF the game's performance cores.

Mirrors how OBS/ShadowPlay keep capture overhead invisible: the game keeps the
P-cores; everything runlog does is marked background (EcoQoS → E-cores) and
below-normal priority so it only ever yields TO the game, never competes with it.

Every function here is a safe no-op on non-Windows and on CPUs / OS builds that
lack the power-throttling APIs. They only ever *lower* runlog's own priority —
they can never touch the game. Below-normal priority is self-regulating: a
background thread still runs at full speed when nothing else wants the core
(e.g. processing a run after the game has closed), and steps aside the moment
the game needs it.
"""

from __future__ import annotations

import ctypes
import sys

_IS_WIN = sys.platform == "win32"

# Win32 priority-class creation flags (values from processthreadsapi.h).
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
IDLE_PRIORITY_CLASS = 0x00000040

# Default creationflags for spawning helper processes (ffmpeg / ffprobe) as
# background tenants. Below-normal only — deliberately NOT CREATE_NO_WINDOW, so
# console behaviour in dev is unchanged.
BG_CREATIONFLAGS = BELOW_NORMAL_PRIORITY_CLASS if _IS_WIN else 0

_THREAD_PRIORITY_BELOW_NORMAL = -1

# PROCESS_/THREAD_POWER_THROTTLING (EcoQoS). To ENABLE throttling you set both
# ControlMask and StateMask to EXECUTION_SPEED (the recorder does the opposite —
# Control set, State clear — to DISABLE throttling on the capture path).
_THREAD_POWER_THROTTLING = 6
_PROCESS_POWER_THROTTLING = 4
_POWER_THROTTLING_VERSION = 1
_EXECUTION_SPEED = 0x1
_PROCESS_SET_INFORMATION = 0x0200


class _PowerThrottlingState(ctypes.Structure):
    _fields_ = [
        ("Version", ctypes.c_uint32),
        ("ControlMask", ctypes.c_uint32),
        ("StateMask", ctypes.c_uint32),
    ]


def set_thread_eco_qos() -> None:
    """Mark the CURRENT thread as EcoQoS + below-normal priority. Call at the top
    of any long-lived background worker (live OCR loop, P1/P2 pool threads)."""
    if not _IS_WIN:
        return
    try:
        k32 = ctypes.windll.kernel32
        h = k32.GetCurrentThread()
        k32.SetThreadPriority(h, _THREAD_PRIORITY_BELOW_NORMAL)
        state = _PowerThrottlingState(_POWER_THROTTLING_VERSION, _EXECUTION_SPEED, _EXECUTION_SPEED)
        k32.SetThreadInformation(h, _THREAD_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state))
    except Exception:
        pass  # a QoS hint must never break processing


def eco_qos_init() -> None:
    """ThreadPoolExecutor `initializer=` — applies background QoS to each worker
    thread as it spins up."""
    set_thread_eco_qos()


def apply_eco_qos_to_pid(pid: int) -> None:
    """Best-effort EcoQoS for an already-spawned child process (e.g. ffmpeg)."""
    if not _IS_WIN or not pid:
        return
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(_PROCESS_SET_INFORMATION, False, int(pid))
        if not h:
            return
        try:
            state = _PowerThrottlingState(_POWER_THROTTLING_VERSION, _EXECUTION_SPEED, _EXECUTION_SPEED)
            k32.SetProcessInformation(h, _PROCESS_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state))
        finally:
            k32.CloseHandle(h)
    except Exception:
        pass

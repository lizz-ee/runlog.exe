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


def set_pid_background(pid: int) -> bool:
    """Drop an already-spawned child process (ffmpeg/ffprobe) to IDLE priority +
    EcoQoS, so an in-flight decode that overlaps a live match yields to the game.
    Best-effort; never suspends (which would let a parent subprocess.run timeout
    fire mid-decode and fail the job)."""
    if not _IS_WIN or not pid:
        return False
    try:
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(_PROCESS_SET_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            k32.SetPriorityClass(h, IDLE_PRIORITY_CLASS)
            state = _PowerThrottlingState(_POWER_THROTTLING_VERSION, _EXECUTION_SPEED, _EXECUTION_SPEED)
            k32.SetProcessInformation(h, _PROCESS_POWER_THROTTLING, ctypes.byref(state), ctypes.sizeof(state))
            return True
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False


# Backwards-compatible alias (EcoQoS-only intent).
def apply_eco_qos_to_pid(pid: int) -> None:
    set_pid_background(pid)


def _iter_child_pids(parent_pid: int, image_names):
    """Yield PIDs of direct children of parent_pid whose image is in image_names
    (a set of lowercased exe names)."""
    if not _IS_WIN:
        return
    TH32CS_SNAPPROCESS = 0x2
    k32 = ctypes.windll.kernel32

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_uint32), ("cntUsage", ctypes.c_uint32),
                    ("th32ProcessID", ctypes.c_uint32), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", ctypes.c_uint32), ("cntThreads", ctypes.c_uint32),
                    ("th32ParentProcessID", ctypes.c_uint32), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_uint32), ("szExeFile", ctypes.c_wchar * 260)]

    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == -1:
        return
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not k32.Process32FirstW(snap, ctypes.byref(entry)):
            return
        while True:
            if entry.th32ParentProcessID == parent_pid and entry.szExeFile.lower() in image_names:
                yield int(entry.th32ProcessID)
            if not k32.Process32NextW(snap, ctypes.byref(entry)):
                break
    finally:
        k32.CloseHandle(snap)


def background_inflight_decoders(parent_pid: int,
                                 image_names=("ffmpeg.exe", "ffprobe.exe")) -> int:
    """Drop any in-flight ffmpeg/ffprobe children of parent_pid to background
    priority (called when a match starts). Returns how many were re-prioritized."""
    if not _IS_WIN:
        return 0
    names = {n.lower() for n in image_names}
    count = 0
    for pid in _iter_child_pids(int(parent_pid), names):
        if set_pid_background(pid):
            count += 1
    return count


def storage_incurs_seek_penalty(path: str):
    """True if `path` lives on a drive with a seek penalty (a spinning HDD),
    False for SSD/NVMe, None if it can't be determined.

    On an HDD shared with the game, the recorder's continuous write stream makes
    the head seek away from the game's asset reads — the classic capture stutter.
    Bytes are trivial; seek interleave is the problem. SSDs have no seek penalty.
    """
    if not _IS_WIN:
        return None
    try:
        drive = os.path.splitdrive(os.path.abspath(path))[0]  # e.g. "C:"
        if not drive:
            return None
        GENERIC_READ = 0  # query needs no access rights
        FILE_SHARE_RW = 0x1 | 0x2
        OPEN_EXISTING = 3
        IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
        StorageDeviceSeekPenaltyProperty = 7
        PropertyStandardQuery = 0
        INVALID = ctypes.c_void_p(-1).value

        class STORAGE_PROPERTY_QUERY(ctypes.Structure):
            _fields_ = [("PropertyId", ctypes.c_int), ("QueryType", ctypes.c_int),
                        ("AdditionalParameters", ctypes.c_ubyte * 1)]

        class DEVICE_SEEK_PENALTY_DESCRIPTOR(ctypes.Structure):
            _fields_ = [("Version", ctypes.c_uint32), ("Size", ctypes.c_uint32),
                        ("IncursSeekPenalty", ctypes.c_ubyte)]

        k32 = ctypes.windll.kernel32
        k32.CreateFileW.restype = ctypes.c_void_p
        h = k32.CreateFileW(f"\\\\.\\{drive}", GENERIC_READ, FILE_SHARE_RW, None,
                            OPEN_EXISTING, 0, None)
        if not h or h == INVALID:
            return None
        try:
            query = STORAGE_PROPERTY_QUERY(StorageDeviceSeekPenaltyProperty, PropertyStandardQuery, (ctypes.c_ubyte * 1)())
            desc = DEVICE_SEEK_PENALTY_DESCRIPTOR()
            returned = ctypes.c_uint32(0)
            ok = k32.DeviceIoControl(
                ctypes.c_void_p(h), IOCTL_STORAGE_QUERY_PROPERTY,
                ctypes.byref(query), ctypes.sizeof(query),
                ctypes.byref(desc), ctypes.sizeof(desc),
                ctypes.byref(returned), None)
            if not ok:
                return None
            return bool(desc.IncursSeekPenalty)
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    except Exception:
        return None

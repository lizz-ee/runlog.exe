"""
WASAPI per-process loopback capture (Windows 10 2004 / build 19041+).

Captures the audio of ONE process tree (Marathon) instead of the whole system
default-speaker loopback — so Discord, music, and notifications never leak into
clips. Uses ActivateAudioInterfaceAsync with AUDIOCLIENT_ACTIVATION_TYPE_PROCESS
_LOOPBACK via ctypes (no third-party dependency).

`record_process_loopback` performs ALL COM/client init up front and only opens
the WAV once capture has actually started, so a caller can catch any exception
and fall back to whole-system loopback with no half-written file. It is the
caller's job to provide a stop Event and to have found the target PID.

This is the only place in the backend that hand-rolls a COM completion handler
vtable; keep the ctypes plumbing here and out of audio_sidecar.py.
"""

from __future__ import annotations

import ctypes
import time
import wave
from ctypes import wintypes

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
_VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "VAD\\Process_Loopback"
_AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1
_PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0

_AUDCLNT_SHAREMODE_SHARED = 0
_AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
_AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM = 0x80000000
_AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY = 0x08000000

_WAVE_FORMAT_PCM = 1
_VT_BLOB = 0x41
_REFTIMES_PER_SEC = 10_000_000  # 100-ns units
_S_OK = 0
_COINIT_MULTITHREADED = 0x0
_AUDCLNT_BUFFERFLAGS_SILENT = 0x2
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0

# vtable slot indexes (IUnknown occupies 0,1,2 on every interface)
_IAUDIOCLIENT_INITIALIZE = 3
_IAUDIOCLIENT_START = 10
_IAUDIOCLIENT_STOP = 11
_IAUDIOCLIENT_GETSERVICE = 14
_IASYNCOP_GETACTIVATERESULT = 3
_ICAPTURE_GETBUFFER = 3
_ICAPTURE_RELEASEBUFFER = 4
_ICAPTURE_GETNEXTPACKETSIZE = 5
_IUNKNOWN_RELEASE = 2


def _guid(s: str) -> "GUID":
    g = GUID()
    if ctypes.windll.ole32.IIDFromString(ctypes.c_wchar_p("{" + s + "}"), ctypes.byref(g)) != _S_OK:
        raise OSError(f"bad GUID {s}")
    return g


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]


class WAVEFORMATEX(ctypes.Structure):
    _pack_ = 1  # C WAVEFORMATEX is 18 bytes — no tail padding after cbSize
    _fields_ = [("wFormatTag", wintypes.WORD), ("nChannels", wintypes.WORD),
                ("nSamplesPerSec", wintypes.DWORD), ("nAvgBytesPerSec", wintypes.DWORD),
                ("nBlockAlign", wintypes.WORD), ("wBitsPerSample", wintypes.WORD),
                ("cbSize", wintypes.WORD)]


class _PROCESS_LOOPBACK_PARAMS(ctypes.Structure):
    _fields_ = [("TargetProcessId", wintypes.DWORD), ("ProcessLoopbackMode", ctypes.c_int)]


class AUDIOCLIENT_ACTIVATION_PARAMS(ctypes.Structure):
    _fields_ = [("ActivationType", ctypes.c_int), ("ProcessLoopbackParams", _PROCESS_LOOPBACK_PARAMS)]


class PROPVARIANT_BLOB(ctypes.Structure):
    # PROPVARIANT laid out for the VT_BLOB case on 64-bit (vt + 3 reserved WORDs,
    # then a BLOB{ULONG cbSize; void* pBlobData} that is 8-byte aligned).
    _fields_ = [("vt", wintypes.WORD), ("r1", wintypes.WORD), ("r2", wintypes.WORD),
                ("r3", wintypes.WORD), ("cbSize", wintypes.DWORD), ("pad", wintypes.DWORD),
                ("pBlobData", ctypes.c_void_p)]


# IIDs
_IID_IAudioClient = "1CB9AD4C-DBFA-4c32-B178-C2F568A703B2"
_IID_IAudioCaptureClient = "C8ADBD64-E71E-48a0-A4DE-185C395CD317"
_IID_ICompletionHandler = "41D949AB-9862-444A-80F6-C261334DA5EB"
_IID_IAsyncOperation = "72A22D78-CDE4-431D-B8CC-843A71199B6D"
_IID_IUnknown = "00000000-0000-0000-C000-000000000046"


def _vcall(ptr, index, restype, argtypes, *args):
    """Call COM method #index on interface `ptr` (a void* to the interface)."""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    fn_addr = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[index]
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(fn_addr)(ptr, *args)


def _build_completion_handler(done_event_handle):
    """Build a minimal IActivateAudioInterfaceCompletionHandler whose
    ActivateCompleted just signals `done_event_handle`. Returns (this_ptr, keepalive)."""
    QI = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    ADDREF = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
    ACT = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)

    iid_handler = _guid(_IID_ICompletionHandler)
    iid_unknown = _guid(_IID_IUnknown)

    def qi(this, riid, ppv):
        g = ctypes.cast(riid, ctypes.POINTER(GUID))[0]
        if bytes(g.Data4) == bytes(iid_handler.Data4) and g.Data1 == iid_handler.Data1 or \
           bytes(g.Data4) == bytes(iid_unknown.Data4) and g.Data1 == iid_unknown.Data1:
            ctypes.cast(ppv, ctypes.POINTER(ctypes.c_void_p))[0] = this
            return _S_OK
        ctypes.cast(ppv, ctypes.POINTER(ctypes.c_void_p))[0] = None
        return -2147467262  # E_NOINTERFACE

    def addref(this):
        return 1

    def release(this):
        return 1

    def activated(this, op):
        ctypes.windll.kernel32.SetEvent(done_event_handle)
        return _S_OK

    vtbl_type = ctypes.c_void_p * 4
    cb_qi, cb_add, cb_rel, cb_act = QI(qi), ADDREF(addref), ADDREF(release), ACT(activated)
    vtbl = vtbl_type(
        ctypes.cast(cb_qi, ctypes.c_void_p),
        ctypes.cast(cb_add, ctypes.c_void_p),
        ctypes.cast(cb_rel, ctypes.c_void_p),
        ctypes.cast(cb_act, ctypes.c_void_p),
    )
    obj = ctypes.c_void_p * 1
    this = obj(ctypes.cast(ctypes.byref(vtbl), ctypes.c_void_p).value)
    this_ptr = ctypes.cast(ctypes.byref(this), ctypes.c_void_p)
    # Return everything that must outlive the call so nothing is GC'd mid-flight.
    return this_ptr, (vtbl, this, cb_qi, cb_add, cb_rel, cb_act)


def record_process_loopback(pid, wav_path, stop, sample_rate=48000, channels=2):
    """Capture `pid`'s process-tree audio to a 16-bit PCM WAV until `stop` is set.

    Raises on any init failure BEFORE opening the WAV, so the caller can fall back
    to whole-system loopback without a half-written file.
    """
    ole32 = ctypes.windll.ole32
    kernel32 = ctypes.windll.kernel32
    mmdevapi = ctypes.windll.mmdevapi

    ole32.CoInitializeEx(None, _COINIT_MULTITHREADED)
    audio_client = ctypes.c_void_p()
    capture_client = ctypes.c_void_p()
    started = False
    try:
        fmt = WAVEFORMATEX(_WAVE_FORMAT_PCM, channels, sample_rate,
                           sample_rate * channels * 2, channels * 2, 16, 0)

        params = AUDIOCLIENT_ACTIVATION_PARAMS(
            _AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK,
            _PROCESS_LOOPBACK_PARAMS(int(pid), _PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE),
        )
        prop = PROPVARIANT_BLOB()
        prop.vt = _VT_BLOB
        prop.cbSize = ctypes.sizeof(params)
        prop.pBlobData = ctypes.cast(ctypes.byref(params), ctypes.c_void_p)

        done = kernel32.CreateEventW(None, True, False, None)
        handler_ptr, _keep = _build_completion_handler(done)

        iid_client = _guid(_IID_IAudioClient)
        async_op = ctypes.c_void_p()
        hr = mmdevapi.ActivateAudioInterfaceAsync(
            ctypes.c_wchar_p(_VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK),
            ctypes.byref(iid_client), ctypes.byref(prop),
            handler_ptr, ctypes.byref(async_op),
        )
        if hr != _S_OK or not async_op:
            raise OSError(f"ActivateAudioInterfaceAsync failed hr={hr:#x}")

        if kernel32.WaitForSingleObject(done, 5000) != _WAIT_OBJECT_0:
            raise OSError("process-loopback activation timed out")
        kernel32.CloseHandle(done)

        activate_hr = ctypes.c_long(0)
        hr = _vcall(async_op, _IASYNCOP_GETACTIVATERESULT, ctypes.c_long,
                    (ctypes.c_void_p, ctypes.c_void_p),
                    ctypes.byref(activate_hr), ctypes.byref(audio_client))
        if hr != _S_OK or activate_hr.value != _S_OK or not audio_client:
            raise OSError(f"GetActivateResult failed hr={hr:#x} ar={activate_hr.value:#x}")
        _vcall(async_op, _IUNKNOWN_RELEASE, ctypes.c_ulong, ())

        # Loopback capture MUST be initialized with the LOOPBACK flag; AUTOCONVERTPCM
        # lets the engine give us the 16-bit PCM we asked for regardless of the mix.
        flags = (_AUDCLNT_STREAMFLAGS_LOOPBACK | _AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM
                 | _AUDCLNT_STREAMFLAGS_SRC_DEFAULT_QUALITY)
        hr = _vcall(audio_client, _IAUDIOCLIENT_INITIALIZE, ctypes.c_long,
                    (ctypes.c_int, ctypes.c_uint32, ctypes.c_int64, ctypes.c_int64,
                     ctypes.c_void_p, ctypes.c_void_p),
                    _AUDCLNT_SHAREMODE_SHARED, flags, _REFTIMES_PER_SEC, 0,
                    ctypes.byref(fmt), None)
        if hr != _S_OK:
            raise OSError(f"IAudioClient.Initialize failed hr={hr & 0xFFFFFFFF:#x}")

        iid_capture = _guid(_IID_IAudioCaptureClient)
        hr = _vcall(audio_client, _IAUDIOCLIENT_GETSERVICE, ctypes.c_long,
                    (ctypes.c_void_p, ctypes.c_void_p),
                    ctypes.byref(iid_capture), ctypes.byref(capture_client))
        if hr != _S_OK or not capture_client:
            raise OSError(f"GetService(IAudioCaptureClient) failed hr={hr & 0xFFFFFFFF:#x}")

        hr = _vcall(audio_client, _IAUDIOCLIENT_START, ctypes.c_long, ())
        if hr != _S_OK:
            raise OSError(f"IAudioClient.Start failed hr={hr & 0xFFFFFFFF:#x}")
        started = True

        # --- init fully succeeded: now own the WAV and stream until stopped ---
        frame_bytes = channels * 2
        with wave.open(wav_path, "wb") as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)

            p_data = ctypes.c_void_p()
            n_frames = ctypes.c_uint32()
            dw_flags = ctypes.c_uint32()
            while not stop.is_set():
                packet = ctypes.c_uint32()
                if _vcall(capture_client, _ICAPTURE_GETNEXTPACKETSIZE, ctypes.c_long,
                          (ctypes.c_void_p,), ctypes.byref(packet)) != _S_OK:
                    break
                if packet.value == 0:
                    time.sleep(0.008)
                    continue
                hr = _vcall(capture_client, _ICAPTURE_GETBUFFER, ctypes.c_long,
                            (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p),
                            ctypes.byref(p_data), ctypes.byref(n_frames),
                            ctypes.byref(dw_flags), None, None)
                if hr != _S_OK:
                    break
                count = n_frames.value
                if count:
                    if dw_flags.value & _AUDCLNT_BUFFERFLAGS_SILENT:
                        wav.writeframes(b"\x00" * (count * frame_bytes))
                    else:
                        buf = ctypes.string_at(p_data, count * frame_bytes)
                        wav.writeframes(buf)
                _vcall(capture_client, _ICAPTURE_RELEASEBUFFER, ctypes.c_long,
                       (ctypes.c_uint32,), count)
    finally:
        try:
            if started and audio_client:
                _vcall(audio_client, _IAUDIOCLIENT_STOP, ctypes.c_long, ())
        except Exception:
            pass
        for iface in (capture_client, audio_client):
            try:
                if iface:
                    _vcall(iface, _IUNKNOWN_RELEASE, ctypes.c_ulong, ())
            except Exception:
                pass
        try:
            ole32.CoUninitialize()
        except Exception:
            pass


def find_process_id(image_name: str):
    """Return the PID of the first running process matching image_name, or None."""
    TH32CS_SNAPPROCESS = 0x2
    kernel32 = ctypes.windll.kernel32

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1 or snap is None:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        target = image_name.lower()
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return None
        while True:
            if entry.szExeFile.lower() == target:
                return int(entry.th32ProcessID)
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                return None
    finally:
        kernel32.CloseHandle(snap)

"""
Windows Graphics Capture + NVENC — captures a specific game window.

Uses the Windows.Graphics.Capture API (same as OBS) to capture only
the Marathon window, even when alt-tabbed or behind other windows.
NVENC encodes directly from GPU — no ffmpeg pipe during recording.

Architecture:
  WGC captures Marathon window continuously while game is running.
  Every frame:
    - If recording: NVENC encode → raw H.264 file (60fps)
    - Every ~1s: JPEG encode → OCR detection thread
  When recording stops: ffmpeg mux H.264 → MP4 (<1 second)

Falls back to ddagrab if WGC or NVENC is unavailable.
"""

import ctypes
import os
import subprocess
import threading
import time
from ctypes import wintypes
from datetime import datetime

# Check WGC availability
try:
    from windows_capture import WindowsCapture, Frame, InternalCaptureControl
    WGC_AVAILABLE = True
except ImportError:
    WGC_AVAILABLE = False

# Check NVENC availability
try:
    import PyNvVideoCodec as nvc
    NVENC_AVAILABLE = True
except ImportError:
    NVENC_AVAILABLE = False

import cv2
import numpy as np

# Marathon process name to match
MARATHON_PROCESS_NAME = "marathon.exe"


def find_game_window() -> str | None:
    """Find Marathon's window by process name (Marathon.exe).

    Matches by process name to avoid false positives like Discord
    channels with 'Marathon' in the title.
    """
    EnumWindows = ctypes.windll.user32.EnumWindows
    GetWindowTextW = ctypes.windll.user32.GetWindowTextW
    GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId
    IsWindowVisible = ctypes.windll.user32.IsWindowVisible
    OpenProcess = ctypes.windll.kernel32.OpenProcess
    CloseHandle = ctypes.windll.kernel32.CloseHandle
    QueryFullProcessImageNameW = ctypes.windll.kernel32.QueryFullProcessImageNameW
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    found_title = None

    def callback(hwnd, lparam):
        nonlocal found_title
        if not IsWindowVisible(hwnd):
            return True

        # Get process ID for this window
        pid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        # Open process to get its executable name
        handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return True

        try:
            buf = ctypes.create_unicode_buffer(512)
            size = wintypes.DWORD(512)
            if QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                exe_path = buf.value.lower()
                if exe_path.endswith(MARATHON_PROCESS_NAME):
                    # Found Marathon.exe window — get its title
                    length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        title_buf = ctypes.create_unicode_buffer(length + 1)
                        GetWindowTextW(hwnd, title_buf, length + 1)
                        found_title = title_buf.value
                        return False  # stop enumeration
        finally:
            CloseHandle(handle)

        return True

    EnumWindows(WNDENUMPROC(callback), 0)
    return found_title


class WGCEngine:
    """Unified WGC capture engine for both detection and recording.

    Single WGC capture session serves both purposes:
    - Detection: JPEG frame every ~1s for OCR
    - Recording: NVENC H.264 encoding at capture rate

    The OCR thread runs separately and grabs the latest detection frame.
    """

    def __init__(self, recordings_dir: str):
        self.recordings_dir = recordings_dir
        os.makedirs(recordings_dir, exist_ok=True)

        # State
        self._running = False
        self._recording = False
        self._recording_start: float = 0
        self._recording_path: str | None = None

        # Detection frame (JPEG bytes for OCR + live feed)
        self._latest_frame: bytes | None = None
        self._frame_seq: int = 0
        self._frame_lock = threading.Lock()

        # NVENC encoder
        self._encoder: object | None = None
        self._h264_file = None
        self._h264_path: str | None = None
        self._encode_frame_count: int = 0

        # Capture control (to stop WGC from outside)
        self._capture_control: InternalCaptureControl | None = None

        # Frame counter for detection throttle
        self._total_frames: int = 0

    @property
    def available(self) -> bool:
        return WGC_AVAILABLE and NVENC_AVAILABLE

    def start(self, window_name: str) -> bool:
        """Start the WGC capture loop on the specified window."""
        if not self.available:
            print(f"[wgc] Not available (WGC={WGC_AVAILABLE}, NVENC={NVENC_AVAILABLE})")
            return False

        self._running = True
        thread = threading.Thread(
            target=self._capture_loop, args=(window_name,),
            daemon=True, name="wgc-engine"
        )
        thread.start()
        return True

    def stop(self):
        """Stop capture and any active recording."""
        self._running = False
        if self._recording:
            self.stop_recording()
        if self._capture_control:
            try:
                self._capture_control.stop()
            except Exception:
                pass

    def get_latest_frame(self) -> tuple[bytes | None, int]:
        """Return (jpeg_bytes, sequence_number) for OCR/detection feed."""
        with self._frame_lock:
            return self._latest_frame, self._frame_seq

    def start_recording(self) -> str | None:
        """Begin recording. Returns the output file path."""
        if self._recording:
            return self._recording_path

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self._h264_path = os.path.join(self.recordings_dir, f"run_{timestamp}.h264")
        self._recording_path = os.path.join(self.recordings_dir, f"run_{timestamp}.mp4")
        self._h264_file = open(self._h264_path, 'wb')
        self._encoder = None  # created on first frame (need resolution)
        self._encode_frame_count = 0
        self._recording = True
        self._recording_start = time.time()
        print(f"[wgc] Recording started: {self._h264_path}")
        return self._recording_path

    def stop_recording(self) -> tuple[str | None, float]:
        """Stop recording, mux to MP4. Returns (mp4_path, duration)."""
        if not self._recording:
            return None, 0

        self._recording = False
        duration = time.time() - self._recording_start

        # Flush encoder
        if self._encoder:
            try:
                flush_data = self._encoder.EndEncode()
                if flush_data and self._h264_file:
                    self._h264_file.write(flush_data)
            except Exception as e:
                print(f"[wgc] Flush error: {e}")

        self._encoder = None

        if self._h264_file:
            self._h264_file.close()
            self._h264_file = None

        # Mux H.264 → MP4 (instant, no re-encoding)
        mp4_path = self._recording_path
        if self._encode_frame_count == 0:
            print(f"[wgc] No frames encoded, skipping mux")
            if self._h264_path and os.path.exists(self._h264_path):
                os.remove(self._h264_path)
            mp4_path = None
        elif self._h264_path and os.path.exists(self._h264_path):
            # Calculate actual framerate from frames captured / duration
            actual_fps = round(self._encode_frame_count / duration) if duration > 0 else 60
            actual_fps = max(1, min(actual_fps, 240))  # clamp to sane range
            try:
                result = subprocess.run(
                    ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
                     '-r', str(actual_fps),
                     '-i', self._h264_path,
                     '-c:v', 'copy', '-an',
                     '-movflags', 'faststart',
                     mp4_path],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0 and os.path.exists(mp4_path):
                    os.remove(self._h264_path)
                    print(f"[wgc] Muxed to MP4: {mp4_path} ({duration:.0f}s, {self._encode_frame_count} frames)")
                else:
                    print(f"[wgc] Mux failed: {result.stderr[:200]}")
                    mp4_path = None
            except Exception as e:
                print(f"[wgc] Mux error: {e}")
                mp4_path = None
        else:
            mp4_path = None

        self._recording_start = 0
        self._recording_path = None
        self._h264_path = None
        return mp4_path, duration

    def _capture_loop(self, window_name: str):
        """Main WGC capture loop. Runs on a dedicated thread."""
        try:
            capture = WindowsCapture(
                cursor_capture=False,
                draw_border=False,
                window_name=window_name,
            )

            @capture.event
            def on_frame_arrived(frame: Frame, control: InternalCaptureControl):
                if not self._running:
                    control.stop()
                    return

                self._capture_control = control
                self._total_frames += 1

                # --- Recording: encode every frame ---
                if self._recording and self._h264_file:
                    self._encode_frame(frame)

                # --- Detection: JPEG every ~30 frames (~0.5s at 60fps) ---
                if self._total_frames % 30 == 0:
                    self._update_detection_frame(frame)

            @capture.event
            def on_closed():
                print("[wgc] Capture session closed")

            print(f"[wgc] Starting capture on '{window_name}'")
            capture.start()

        except Exception as e:
            print(f"[wgc] Capture error: {e}")
        finally:
            self._running = False
            print("[wgc] Capture loop stopped")

    def _encode_frame(self, frame: Frame):
        """Encode a frame with NVENC and write to H.264 file."""
        try:
            # Create encoder on first frame (need actual resolution)
            if self._encoder is None:
                w, h = frame.width, frame.height
                self._encoder = nvc.CreateEncoder(
                    w, h, "ABGR", True,
                    codec="h264",
                    preset="P4",
                    tuning_info="low_latency",
                    rc="vbr",
                )
                print(f"[wgc] NVENC encoder: {w}x{h}")

            encoded = self._encoder.Encode(frame.frame_buffer)
            if encoded:
                self._h264_file.write(encoded)
                self._encode_frame_count += 1

        except Exception as e:
            print(f"[wgc] Encode error: {e}")

    def _update_detection_frame(self, frame: Frame):
        """JPEG-encode a frame for OCR detection and live feed."""
        try:
            _, jpeg_buf = cv2.imencode('.jpg', frame.frame_buffer,
                                        [cv2.IMWRITE_JPEG_QUALITY, 60])
            jpeg_bytes = jpeg_buf.tobytes()

            with self._frame_lock:
                self._latest_frame = jpeg_bytes
                self._frame_seq += 1
        except Exception as e:
            print(f"[wgc] Detection frame error: {e}")

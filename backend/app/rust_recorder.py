"""
Rust recorder wrapper — communicates with runlog-recorder.exe via JSON IPC.

The Rust binary handles:
  - WGC window capture (Marathon only, privacy safe)
  - H.264 encoding via MediaFoundation hardware encoder (zero-copy GPU)
  - 60fps recording at native resolution (4K)
  - OCR frames sent as base64 JPEG at ~2fps

Python handles:
  - OCR detection (EasyOCR)
  - Start/stop commands based on game state
  - Screenshot management
  - Processing pipeline
"""

import base64
import json
import os
import subprocess
import threading
import time


def _find_recorder_exe() -> str | None:
    """Find the runlog-recorder.exe binary."""
    # Check common locations
    candidates = [
        # Development: built by cargo
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "recorder", "target", "release", "runlog-recorder.exe"),
        # Production: bundled alongside backend
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "runlog-recorder.exe"),
        # Production: in resources
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "runlog-recorder.exe"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return os.path.abspath(path)
    return None


class RustRecorder:
    """Wrapper around the Rust recorder binary."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._reader_thread: threading.Thread | None = None
        self._running = False

        # State reported by Rust
        self.window_name: str | None = None
        self.width: int = 0
        self.height: int = 0
        self.recording: bool = False
        self.recording_path: str | None = None

        # Latest OCR frame (JPEG bytes)
        self._latest_frame: bytes | None = None
        self._frame_seq: int = 0
        self._frame_lock = threading.Lock()

        # Event callbacks
        self.on_recording_started: callable | None = None
        self.on_recording_stopped: callable | None = None
        self.on_error: callable | None = None

    @property
    def available(self) -> bool:
        return _find_recorder_exe() is not None

    @property
    def is_running(self) -> bool:
        return self._running and self._proc is not None and self._proc.poll() is None

    def start(self) -> bool:
        """Start the Rust recorder process."""
        exe = _find_recorder_exe()
        if not exe:
            print("[recorder] runlog-recorder.exe not found")
            return False

        try:
            env = os.environ.copy()
            env.setdefault("RUNLOG_GPU_PRIORITY", "normal")
            self._proc = subprocess.Popen(
                [exe],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,  # binary mode for stdout (JSON lines)
                env=env,
                creationflags=0,
            )
            self._running = True

            # Reader thread for stdout (events from Rust)
            self._reader_thread = threading.Thread(
                target=self._read_events, daemon=True, name="rust-recorder-reader"
            )
            self._reader_thread.start()

            # Stderr reader for debug logs
            threading.Thread(
                target=self._read_stderr, daemon=True, name="rust-recorder-stderr"
            ).start()

            print(f"[recorder] Started runlog-recorder.exe (pid={self._proc.pid})")
            return True
        except Exception as e:
            print(f"[recorder] Failed to start: {e}")
            return False

    def stop(self):
        """Stop the Rust recorder process."""
        self._running = False
        if self._proc and self._proc.poll() is None:
            self._send_command({"cmd": "quit"})
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
        print("[recorder] Stopped")

    def start_recording(self, path: str, bitrate: int = 30_000_000, encoder: str = "hevc", fps: int = 60) -> bool:
        """Tell the Rust binary to start recording."""
        if not self.is_running:
            return False
        self._send_command({"cmd": "start", "path": path, "bitrate": bitrate, "encoder": encoder, "fps": fps})
        return True

    def stop_recording(self):
        """Tell the Rust binary to stop recording."""
        if not self.is_running:
            return
        self._send_command({"cmd": "stop"})

    def take_screenshot(self, path: str, timeout: float = 3.0) -> bool:
        """Tell the Rust binary to save a full-resolution screenshot. Waits for confirmation."""
        if not self.is_running:
            return False
        self._screenshot_confirmed = threading.Event()
        self._send_command({"cmd": "screenshot", "path": path})
        confirmed = self._screenshot_confirmed.wait(timeout=timeout)
        if not confirmed:
            print(f"[recorder] Screenshot confirmation timed out: {path}")
        return confirmed

    def get_latest_frame(self) -> tuple[bytes | None, int]:
        """Return (jpeg_bytes, sequence_number) for OCR detection."""
        with self._frame_lock:
            return self._latest_frame, self._frame_seq

    # -- Internal ----------------------------------------------------------

    def set_ocr_fast(self, enabled: bool):
        """Toggle fast direct OCR mode (after RUN_COMPLETE)."""
        self._send_command({"cmd": "ocr_fast", "enabled": enabled})

    def _send_command(self, cmd: dict):
        """Send a JSON command to the Rust binary via stdin."""
        if not self._proc or self._proc.poll() is not None:
            return
        try:
            line = json.dumps(cmd) + "\n"
            self._proc.stdin.write(line.encode("utf-8"))
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            print(f"[recorder] Send failed: {e}")

    def _read_events(self):
        """Read JSON events from Rust binary's stdout."""
        try:
            for raw_line in self._proc.stdout:
                if not self._running:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                self._handle_event(event)
        except Exception as e:
            if self._running:
                print(f"[recorder] Reader error: {e}")
        print("[recorder] Event reader stopped")

    def _read_stderr(self):
        """Forward Rust binary's stderr to Python's stdout."""
        try:
            for raw_line in self._proc.stderr:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if line:
                    # Encode-safe print — Windows console can't handle all Unicode
                    safe = line.encode("ascii", errors="replace").decode("ascii")
                    print(f"[recorder-rs] {safe}")
        except Exception as e:
            if self._running:
                print(f"[recorder] Stderr reader error: {e}")

    def _handle_event(self, event: dict):
        """Process an event from the Rust binary."""
        evt_type = event.get("event")

        if evt_type == "ready":
            self.window_name = event.get("window")
            self.width = event.get("width", 0)
            self.height = event.get("height", 0)
            print(f"[recorder] Ready: {self.window_name} ({self.width}x{self.height})")

        elif evt_type == "recording_started":
            self.recording = True
            self.recording_path = event.get("path")
            print(f"[recorder] Recording started: {self.recording_path}")
            if self.on_recording_started:
                self.on_recording_started(self.recording_path)

        elif evt_type == "recording_stopped":
            self.recording = False
            path = event.get("path", "")
            duration = event.get("duration", 0)
            frames = event.get("frames", 0)
            fps = frames / duration if duration > 0 else 0
            print(f"[recorder] Recording stopped: {path} ({duration:.1f}s, {frames} frames, {fps:.1f}fps)")
            self.recording_path = None
            if self.on_recording_stopped:
                self.on_recording_stopped(path, duration, frames)

        elif evt_type == "frame":
            # Decode base64 JPEG for OCR
            b64 = event.get("jpeg_base64", "")
            if b64:
                try:
                    jpeg_bytes = base64.b64decode(b64)
                    with self._frame_lock:
                        self._latest_frame = jpeg_bytes
                        self._frame_seq += 1
                except Exception as e:
                    print(f"[recorder] Frame decode error: {e}")

        elif evt_type == "screenshot_saved":
            print(f"[recorder] Screenshot saved: {event.get('path')}")
            if hasattr(self, '_screenshot_confirmed'):
                self._screenshot_confirmed.set()

        elif evt_type == "error":
            msg = event.get("message", "Unknown error")
            print(f"[recorder] Error: {msg}")
            if self.on_error:
                self.on_error(msg)

"""
Rust recorder wrapper — communicates with runlog-recorder.exe via JSON IPC.

The Rust binary handles:
  - WGC window capture (Marathon only, privacy safe)
  - H.264/HEVC encoding via MediaFoundation hardware encoder (zero-copy GPU)
  - 60fps recording at native resolution (4K)
  - OCR region crops (lobby/deploy/endgame) sent as small base64 JPEGs via
    async double-buffered staging — never a synchronous GPU readback
  - Full preview frames at a slow cadence, or on demand via frame_now

Python handles:
  - OCR detection (winocr) on the pre-cropped regions
  - Start/stop commands based on game state
  - Screenshot management
  - Processing pipeline
"""

import base64
import ctypes
import json
import os
import shutil
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
        self._direct_proc: subprocess.Popen | None = None
        self._direct_progress_thread: threading.Thread | None = None
        self._direct_stderr_thread: threading.Thread | None = None
        self._direct_exit_event = threading.Event()
        self._direct_stop_requested = False
        self._direct_focus_thread: threading.Thread | None = None
        self._direct_started_at = 0.0
        self._direct_stderr_tail: list[str] = []
        self._direct_nvenc_available: bool | None = None
        self._direct_output_idx: int | None = None
        self.recording_backend: str = "none"

        # State reported by Rust
        self.window_name: str | None = None
        self.width: int = 0
        self.height: int = 0
        self.recording: bool = False
        self.recording_path: str | None = None
        self.recording_state: str = "idle"
        self.recording_duration: float = 0.0
        self.recording_captured_frames: int = 0
        self.recording_submitted_frames: int = 0
        self.recording_dropped_frames: int = 0
        self.recording_capture_fps: float = 0.0
        self.recording_submitted_fps: float = 0.0
        self.recording_capture_fps_recent: float = 0.0
        self.recording_submitted_fps_recent: float = 0.0
        self.recording_last_progress_at: float = 0.0
        self.recording_last_stop: dict | None = None
        self.last_error: str | None = None

        # Latest full preview frame (JPEG bytes)
        self._latest_frame: bytes | None = None
        self._frame_seq: int = 0
        # Latest OCR region crops ({'lobby'|'deploy'|'endgame': jpeg_bytes})
        self._latest_regions: dict[str, bytes] | None = None
        self._regions_seq: int = 0
        self._frame_lock = threading.Lock()
        self._frame_event = threading.Event()
        self._regions_event = threading.Event()
        self._command_lock = threading.Lock()
        self._recording_op_lock = threading.RLock()
        self._recording_transition = threading.Event()
        self._last_progress_sample: tuple[float, int, int] | None = None

        # Event callbacks
        self.on_recording_started: callable | None = None
        self.on_recording_stopped: callable | None = None
        self.on_error: callable | None = None

        # Deferred restart flag — set when a setting changes that the recorder
        # only reads at process startup (e.g. fps for the WGC capture-rate cap)
        # while a recording is in progress. The capture engine drains this
        # after the recording finishes and bounces the recorder process.
        self.fps_restart_pending: bool = False

    @property
    def available(self) -> bool:
        return _find_recorder_exe() is not None

    @property
    def is_running(self) -> bool:
        return self._running and self._proc is not None and self._proc.poll() is None

    def _can_use_direct_nvenc(self) -> bool:
        """Return whether FFmpeg can keep D3D11 surfaces on-GPU into NVENC."""
        if self._direct_nvenc_available is not None:
            return self._direct_nvenc_available

        ffmpeg = shutil.which("ffmpeg")
        nvidia_smi = shutil.which("nvidia-smi")
        if not ffmpeg or not nvidia_smi or os.name != "nt":
            self._direct_nvenc_available = False
            return False

        try:
            encoders = subprocess.run(
                [ffmpeg, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            filters = subprocess.run(
                [ffmpeg, "-hide_banner", "-filters"],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            gpu = subprocess.run(
                [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self._direct_nvenc_available = (
                encoders.returncode == 0
                and "hevc_nvenc" in encoders.stdout
                and "h264_nvenc" in encoders.stdout
                and filters.returncode == 0
                and "ddagrab" in filters.stdout
                and "scale_d3d11" in filters.stdout
                and gpu.returncode == 0
                and bool(gpu.stdout.strip())
            )
        except Exception:
            self._direct_nvenc_available = False
        return self._direct_nvenc_available

    def _find_direct_output(self) -> int:
        """Choose the DXGI output whose dimensions match the Marathon window."""
        if self._direct_output_idx is not None:
            return self._direct_output_idx
        ffprobe = shutil.which("ffprobe")
        if not ffprobe or not self.width or not self.height:
            self._direct_output_idx = 0
            return 0

        for index in range(8):
            try:
                probe = subprocess.run(
                    [
                        ffprobe,
                        "-v",
                        "error",
                        "-f",
                        "lavfi",
                        "-i",
                        f"ddagrab=output_idx={index}:framerate=1:draw_mouse=0",
                        "-show_entries",
                        "stream=width,height",
                        "-of",
                        "csv=p=0",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=4,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                dims = probe.stdout.strip().split(",")
                if (
                    probe.returncode == 0
                    and len(dims) >= 2
                    and int(dims[0]) == self.width
                    and int(dims[1]) == self.height
                ):
                    self._direct_output_idx = index
                    return index
            except Exception:
                continue
        self._direct_output_idx = 0
        return 0

    @staticmethod
    def _direct_capture_is_safe() -> bool:
        """True when another app is not covering Marathon's capture display."""
        if os.name != "nt":
            return False
        try:
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user32.FindWindowW.restype = wintypes.HWND
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.MonitorFromWindow.restype = wintypes.HANDLE
            game = user32.FindWindowW(None, "Marathon")
            foreground = user32.GetForegroundWindow()
            if not game or not foreground:
                return False
            if game == foreground:
                return True
            # Interacting with a second-monitor app is safe: Desktop
            # Duplication captures only Marathon's output. A foreign window on
            # the same output would be baked into the recording.
            MONITOR_DEFAULTTONEAREST = 2
            game_monitor = user32.MonitorFromWindow(game, MONITOR_DEFAULTTONEAREST)
            foreground_monitor = user32.MonitorFromWindow(
                foreground, MONITOR_DEFAULTTONEAREST
            )
            return bool(game_monitor and foreground_monitor != game_monitor)
        except Exception:
            return False

    def start(self) -> bool:
        """Start the Rust recorder process."""
        if self.is_running:
            return True

        exe = _find_recorder_exe()
        if not exe:
            self.last_error = "runlog-recorder.exe not found"
            print(f"[recorder] {self.last_error}")
            return False

        try:
            # Pass the configured recording fps to the recorder so its WGC
            # capture rate cap matches what we actually encode. Without this,
            # WGC delivers frames at the game's render rate (e.g. 90 fps),
            # wasting GPU cycles on captures we'd just throw away.
            env = os.environ.copy()
            try:
                from .api.settings_api import get_config_value
                fps = get_config_value("fps") or 60
                # On NVIDIA the WGC process is detection-only while FFmpeg owns
                # recording. Thirty WGC callbacks/sec is ample for OCR and
                # avoids duplicating the fast path's 60-FPS capture workload.
                wgc_fps = min(int(fps), 30) if self._can_use_direct_nvenc() else int(fps)
                env["RUNLOG_CAPTURE_FPS"] = str(wgc_fps)
            except Exception:
                pass

            proc = subprocess.Popen(
                [exe],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,  # binary mode for stdout (JSON lines)
                env=env,
            )
            self._proc = proc
            self._running = True
            self.window_name = None
            self.width = 0
            self.height = 0
            self.recording = False
            self.recording_path = None
            self.recording_state = "idle"
            self.recording_last_stop = None
            self._reset_recording_metrics()
            self.last_error = None

            # Reader thread for stdout (events from Rust)
            self._reader_thread = threading.Thread(
                target=self._read_events, args=(proc,), daemon=True, name="rust-recorder-reader"
            )
            self._reader_thread.start()

            # Stderr reader for debug logs
            threading.Thread(
                target=self._read_stderr, args=(proc,), daemon=True, name="rust-recorder-stderr"
            ).start()

            print(f"[recorder] Started runlog-recorder.exe (pid={proc.pid})")
            return True
        except Exception as e:
            self.last_error = f"Failed to start recorder: {e}"
            print(f"[recorder] {self.last_error}")
            return False

    def stop(self):
        """Stop the Rust recorder process."""
        self._frame_event.set()
        self._regions_event.set()
        if self._direct_proc and self._direct_proc.poll() is None:
            self._stop_direct_recording(timeout=20.0)
        if self._proc and self._proc.poll() is None:
            self._send_command({"cmd": "quit"})
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._running = False
        self._proc = None
        # The game-impact guard keys off window_name; a stopped recorder has no
        # window, so clear it (and dims) instead of leaving a stale value that
        # would keep heavy processing blocked after the game closed.
        self.window_name = None
        self.width = 0
        self.height = 0
        self.recording = False
        self.recording_path = None
        self.recording_state = "idle"
        self.recording_backend = "none"
        self._reset_recording_metrics()
        self._recording_transition.set()
        print("[recorder] Stopped")

    def start_recording(
        self,
        path: str,
        bitrate: int = 30_000_000,
        encoder: str = "hevc",
        fps: int = 60,
        target_height: int | None = None,
    ) -> bool:
        """Start recording and wait for Rust to confirm encoder creation.

        target_height: when set, encoder downscales to this height with aspect
        preserved (e.g. 1080 → 1920x1080 from 4K input). None or 0 = native.
        """
        with self._recording_op_lock:
            if not self.is_running or self.recording_state in ("starting", "recording", "stopping"):
                return False

            try:
                from .api.settings_api import get_config_value
                hardware_acceleration = get_config_value("hardware_acceleration")
                if hardware_acceleration is None:
                    hardware_acceleration = True
            except Exception:
                hardware_acceleration = True

            if (
                hardware_acceleration
                and self._can_use_direct_nvenc()
                and self._direct_capture_is_safe()
            ):
                if self._start_direct_recording(
                    path=path,
                    bitrate=bitrate,
                    encoder=encoder,
                    fps=fps,
                    target_height=target_height,
                ):
                    return True
                print(
                    f"[recorder] Direct NVENC unavailable for this run ({self.last_error}); "
                    "falling back to the portable 30fps encoder"
                )
                self._direct_nvenc_available = False
                fps = min(int(fps), 30)
            elif hardware_acceleration and self._can_use_direct_nvenc():
                print(
                    "[recorder] Marathon's display is covered by another app; "
                    "using the private WGC 30fps path for this run"
                )
                fps = min(int(fps), 30)

            self.recording_state = "starting"
            self.recording_backend = "media_foundation"
            self.recording_path = path
            self.recording_last_stop = None
            self._reset_recording_metrics()
            self._recording_transition.clear()
            cmd = {
                "cmd": "start",
                "path": path,
                "bitrate": bitrate,
                "encoder": encoder,
                "fps": fps,
            }
            if target_height and target_height > 0:
                cmd["target_height"] = int(target_height)
            if not self._send_command(cmd):
                self.recording_state = "failed"
                self.recording_path = None
                return False

            if not self._recording_transition.wait(timeout=10.0):
                self.last_error = "Recorder start timed out before encoder confirmation"
                self.recording_state = "failed"
                self._send_command({"cmd": "stop"})
                return False
            return self.recording and self.recording_path == path

    def stop_recording(self, timeout: float = 20.0) -> dict | None:
        """Stop recording and wait for the finalized-file acknowledgement."""
        with self._recording_op_lock:
            if self.recording_backend == "direct_nvenc":
                return self._stop_direct_recording(timeout=max(timeout, 45.0))
            if not self.is_running:
                return self.recording_last_stop
            if not self.recording and self.recording_state not in ("starting", "stopping"):
                return self.recording_last_stop

            expected_path = self.recording_path
            self.recording_state = "stopping"
            self._recording_transition.clear()
            if not self._send_command({"cmd": "stop"}):
                return None
            if not self._recording_transition.wait(timeout=timeout):
                self.last_error = "Recorder stop timed out before MP4 finalization"
                return None
            result = self.recording_last_stop
            if result and expected_path and result.get("path") != expected_path:
                self.last_error = "Recorder finalized a different recording than requested"
                return None
            return result

    def _start_direct_recording(
        self,
        path: str,
        bitrate: int,
        encoder: str,
        fps: int,
        target_height: int | None,
    ) -> bool:
        """Start the zero-copy D3D11 Desktop Duplication -> NVENC pipeline."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            self.last_error = "FFmpeg was not found for direct NVENC capture"
            return False

        self.recording_state = "starting"
        self.recording_backend = "direct_nvenc"
        self.recording_path = path
        self.recording_last_stop = None
        self._reset_recording_metrics()
        self._recording_transition.clear()
        self._direct_exit_event.clear()
        self._direct_stop_requested = False
        self._direct_stderr_tail = []

        fps = max(1, min(int(fps), 240))
        bitrate = max(1_000_000, int(bitrate))
        codec = "h264_nvenc" if str(encoder).lower() == "h264" else "hevc_nvenc"
        output_index = self._find_direct_output()
        output_filter: list[str] = []
        if target_height and self.height and int(target_height) < self.height:
            out_h = int(target_height) & ~1
            out_w = int(round(self.width * out_h / self.height)) & ~1
            output_filter = [
                "-vf",
                f"scale_d3d11=width={out_w}:height={out_h}:format=nv12",
            ]

        args = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "lavfi",
            "-i",
            f"ddagrab=output_idx={output_index}:framerate={fps}:draw_mouse=0",
            *output_filter,
            "-an",
            "-c:v",
            codec,
            # Low-latency performance preset: keep the dedicated encoder fed
            # without borrowing more of Marathon's saturated 3D engine.
            "-preset",
            "p1",
            "-tune",
            "ll",
            "-rc",
            "cbr",
            "-b:v",
            str(bitrate),
            "-maxrate",
            str(bitrate),
            "-bufsize",
            str(bitrate * 2),
            "-g",
            str(fps * 2),
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            "-y",
            path,
        ]

        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            creationflags = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
            )
            proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
            self._direct_proc = proc
            self._direct_started_at = time.monotonic()
            self.recording_last_progress_at = self._direct_started_at
            self._send_command({"cmd": "external_recording", "enabled": True})

            self._direct_progress_thread = threading.Thread(
                target=self._read_direct_progress,
                args=(proc,),
                daemon=True,
                name="direct-nvenc-progress",
            )
            self._direct_progress_thread.start()
            self._direct_stderr_thread = threading.Thread(
                target=self._read_direct_stderr,
                args=(proc,),
                daemon=True,
                name="direct-nvenc-stderr",
            )
            self._direct_stderr_thread.start()

            # Encoder/device setup errors occur immediately. Do not announce
            # REC until the process survives initialization.
            time.sleep(0.5)
            if proc.poll() is not None:
                message = self._direct_error_message(
                    f"Direct NVENC exited during startup (code {proc.returncode})"
                )
                self.last_error = message
                self.recording_state = "failed"
                self.recording_backend = "none"
                self.recording_path = None
                self._send_command({"cmd": "external_recording", "enabled": False})
                return False

            self.recording = True
            self.recording_state = "recording"
            self.last_error = None
            self._recording_transition.set()
            print(
                f"[recorder] Direct NVENC recording started: {path} "
                f"({codec}, {fps}fps, D3D11 GPU surfaces)"
            )
            if self.on_recording_started:
                self.on_recording_started(path)
            self._direct_focus_thread = threading.Thread(
                target=self._monitor_direct_capture_privacy,
                args=(proc,),
                daemon=True,
                name="direct-nvenc-privacy",
            )
            self._direct_focus_thread.start()
            return True
        except Exception as e:
            self.last_error = f"Failed to start direct NVENC capture: {e}"
            self.recording = False
            self.recording_state = "failed"
            self.recording_backend = "none"
            self.recording_path = None
            self._send_command({"cmd": "external_recording", "enabled": False})
            print(f"[recorder] {self.last_error}")
            return False

    def _monitor_direct_capture_privacy(self, proc: subprocess.Popen):
        unsafe_since = 0.0
        while (
            self._direct_proc is proc
            and proc.poll() is None
            and not self._direct_stop_requested
        ):
            if self._direct_capture_is_safe():
                unsafe_since = 0.0
            elif not unsafe_since:
                unsafe_since = time.monotonic()
            elif time.monotonic() - unsafe_since >= 1.0:
                reason = (
                    "Direct capture stopped because another window covered "
                    "Marathon's display"
                )
                self.last_error = reason
                self.recording = False
                self.recording_state = "failed"
                self._direct_stop_requested = True
                try:
                    if proc.stdin:
                        proc.stdin.write("q\n")
                        proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                self._recording_transition.set()
                if self.on_error:
                    self.on_error(reason)
                return
            time.sleep(0.25)

    def _read_direct_progress(self, proc: subprocess.Popen):
        block: dict[str, str] = {}
        try:
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                block[key] = value
                if key != "progress":
                    continue

                now = time.monotonic()
                frames = int(block.get("frame", 0) or 0)
                drops = int(block.get("drop_frames", 0) or 0)
                duration = max(
                    float(block.get("out_time_us", 0) or 0) / 1_000_000,
                    now - self._direct_started_at,
                )
                captured = frames + drops
                if self._last_progress_sample is not None:
                    prior_at, prior_captured, prior_submitted = self._last_progress_sample
                    elapsed = now - prior_at
                    if elapsed > 0:
                        self.recording_capture_fps_recent = max(
                            0.0, (captured - prior_captured) / elapsed
                        )
                        self.recording_submitted_fps_recent = max(
                            0.0, (frames - prior_submitted) / elapsed
                        )
                self._last_progress_sample = (now, captured, frames)
                self.recording_duration = duration
                self.recording_captured_frames = captured
                self.recording_submitted_frames = frames
                self.recording_dropped_frames = drops
                self.recording_capture_fps = captured / duration if duration > 0 else 0.0
                self.recording_submitted_fps = frames / duration if duration > 0 else 0.0
                self.recording_last_progress_at = now
                block = {}
        except Exception as e:
            if not self._direct_stop_requested:
                self._direct_stderr_tail.append(f"progress reader: {e}")
        finally:
            self._direct_exit_event.set()
            if (
                self._direct_proc is proc
                and not self._direct_stop_requested
                and self.recording_backend == "direct_nvenc"
            ):
                self.recording = False
                self.recording_state = "failed"
                self.last_error = self._direct_error_message(
                    f"Direct NVENC exited unexpectedly (code {proc.poll()})"
                )
                self._send_command({"cmd": "external_recording", "enabled": False})
                self._recording_transition.set()
                if self.on_error:
                    self.on_error(self.last_error)

    def _read_direct_stderr(self, proc: subprocess.Popen):
        try:
            for raw_line in proc.stderr:
                line = raw_line.strip()
                if line:
                    self._direct_stderr_tail.append(line)
                    del self._direct_stderr_tail[:-12]
        except Exception:
            pass

    def _direct_error_message(self, fallback: str) -> str:
        detail = self._direct_stderr_tail[-1] if self._direct_stderr_tail else ""
        return f"{fallback}: {detail}" if detail else fallback

    def _stop_direct_recording(self, timeout: float = 45.0) -> dict | None:
        proc = self._direct_proc
        path = self.recording_path or ""
        if not proc:
            return self.recording_last_stop

        self.recording_state = "stopping"
        self._direct_stop_requested = True
        try:
            if proc.poll() is None and proc.stdin:
                proc.stdin.write("q\n")
                proc.stdin.flush()
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except (BrokenPipeError, OSError):
            pass

        self._direct_exit_event.wait(timeout=2)
        self._send_command({"cmd": "external_recording", "enabled": False})
        duration = self.recording_duration or max(
            0.0, time.monotonic() - self._direct_started_at
        )
        frames = self.recording_submitted_frames
        captured = self.recording_captured_frames or frames
        drops = self.recording_dropped_frames
        finalized = (
            proc.returncode == 0
            and bool(path)
            and os.path.exists(path)
            and os.path.getsize(path) > 0
        )
        error = None if finalized else self._direct_error_message(
            f"Direct NVENC finalization failed (code {proc.returncode})"
        )
        fps = frames / duration if duration > 0 else 0.0
        result = {
            "path": path,
            "duration": duration,
            "frames": frames,
            "captured_frames": captured,
            "dropped_frames": drops,
            "finalized": finalized,
            "error": error,
            "fps": fps,
        }
        self.recording_last_stop = result
        self.recording = False
        self.recording_state = "idle" if finalized else "failed"
        self.recording_backend = "none"
        self.recording_path = None
        self.last_error = error
        self._direct_proc = None
        self._recording_transition.set()
        print(
            f"[recorder] Direct NVENC stopped: {path} "
            f"({duration:.1f}s, {frames}/{captured} frames, "
            f"{drops} dropped, {fps:.1f}fps, finalized={finalized})"
        )
        if self.on_recording_stopped:
            self.on_recording_stopped(path, duration, frames)
        return result

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
        """Return (jpeg_bytes, sequence_number) for the full preview frame."""
        with self._frame_lock:
            return self._latest_frame, self._frame_seq

    def get_latest_regions(self) -> tuple[dict[str, bytes] | None, int]:
        """Return ({region: jpeg_bytes}, sequence_number) for OCR detection."""
        with self._frame_lock:
            return self._latest_regions, self._regions_seq

    @staticmethod
    def _wait_for_update(event, getter, last_seq: int, timeout: float):
        """Wait without polling until `getter` reports a new sequence number.

        Clear/re-check avoids losing an update that lands between the first
        sequence check and Event.clear().
        """
        data, seq = getter()
        if seq != last_seq:
            return data, seq
        event.clear()
        data, seq = getter()
        if seq != last_seq:
            return data, seq
        event.wait(timeout=timeout)
        return getter()

    def wait_for_frame(self, last_seq: int, timeout: float = 1.0):
        return self._wait_for_update(self._frame_event, self.get_latest_frame, last_seq, timeout)

    def wait_for_regions(self, last_seq: int, timeout: float = 1.0):
        return self._wait_for_update(self._regions_event, self.get_latest_regions, last_seq, timeout)

    def request_full_frame(self):
        """Ask the recorder for a fresh full preview frame on the next capture."""
        self._send_command({"cmd": "frame_now"})

    # -- Internal ----------------------------------------------------------

    def set_ocr_fast(self, enabled: bool):
        """Toggle fast direct OCR mode (after RUN_COMPLETE)."""
        self._send_command({"cmd": "ocr_fast", "enabled": enabled})

    def _send_command(self, cmd: dict) -> bool:
        """Send a JSON command to the Rust binary via stdin."""
        if not self._proc or self._proc.poll() is not None:
            return False
        try:
            line = json.dumps(cmd) + "\n"
            with self._command_lock:
                self._proc.stdin.write(line.encode("utf-8"))
                self._proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError) as e:
            self.last_error = f"Recorder command failed: {e}"
            print(f"[recorder] Send failed: {e}")
            return False

    def _read_events(self, proc: subprocess.Popen):
        """Read JSON events from Rust binary's stdout."""
        try:
            for raw_line in proc.stdout:
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
        finally:
            # Closing Marathon ends WGC and therefore the Rust process. Clear
            # stale game state so Python can re-arm discovery for the next
            # launch. Process identity prevents an old reader from touching a
            # newer recorder instance.
            if self._proc is proc:
                self._running = False
                self.window_name = None
                self.width = 0
                self.height = 0
                if self.recording or self.recording_state in ("starting", "stopping"):
                    self.recording = False
                    self.recording_state = "failed"
                    self.last_error = self.last_error or "Recorder process exited during recording"
                self._recording_transition.set()
                self._frame_event.set()
                self._regions_event.set()
        print("[recorder] Event reader stopped")

    def _read_stderr(self, proc: subprocess.Popen):
        """Forward Rust binary's stderr to Python's stdout."""
        try:
            for raw_line in proc.stderr:
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
            self.recording_state = "recording"
            self.recording_path = event.get("path")
            self.last_error = None
            self.recording_last_progress_at = time.monotonic()
            self._recording_transition.set()
            print(f"[recorder] Recording started: {self.recording_path}")
            if self.on_recording_started:
                self.on_recording_started(self.recording_path)

        elif evt_type == "recording_failed":
            self.recording = False
            self.recording_state = "failed"
            self.recording_path = event.get("path") or self.recording_path
            self.last_error = event.get("message", "Recorder failed to start")
            self._recording_transition.set()
            print(f"[recorder] Recording failed: {self.last_error}")
            if self.on_error:
                self.on_error(self.last_error)

        elif evt_type == "recording_progress":
            path = event.get("path")
            if self.recording_path and path and path != self.recording_path:
                return
            now = time.monotonic()
            captured = int(event.get("captured_frames", 0))
            submitted = int(event.get("submitted_frames", 0))
            if self._last_progress_sample is not None:
                prior_at, prior_captured, prior_submitted = self._last_progress_sample
                elapsed = now - prior_at
                if elapsed > 0:
                    self.recording_capture_fps_recent = max(
                        0.0, (captured - prior_captured) / elapsed
                    )
                    self.recording_submitted_fps_recent = max(
                        0.0, (submitted - prior_submitted) / elapsed
                    )
            self._last_progress_sample = (now, captured, submitted)
            self.recording_duration = float(event.get("duration", 0))
            self.recording_captured_frames = captured
            self.recording_submitted_frames = submitted
            self.recording_dropped_frames = int(event.get("dropped_frames", 0))
            self.recording_capture_fps = float(event.get("capture_fps", 0))
            self.recording_submitted_fps = float(event.get("submitted_fps", 0))
            self.recording_last_progress_at = now

        elif evt_type == "recording_stopped":
            self.recording = False
            path = event.get("path", "")
            duration = event.get("duration", 0)
            frames = event.get("frames", 0)
            captured = event.get("captured_frames", frames)
            dropped = event.get("dropped_frames", 0)
            finalized = bool(event.get("finalized", True))
            final_error = event.get("error")
            fps = frames / duration if duration > 0 else 0
            self.recording_state = "idle" if finalized else "failed"
            self.recording_last_stop = {
                "path": path,
                "duration": duration,
                "frames": frames,
                "captured_frames": captured,
                "dropped_frames": dropped,
                "finalized": finalized,
                "error": final_error,
                "fps": fps,
            }
            if final_error:
                self.last_error = str(final_error)
            elif finalized:
                self.last_error = None
            print(
                f"[recorder] Recording stopped: {path} "
                f"({duration:.1f}s, {frames}/{captured} submitted, "
                f"{dropped} dropped, {fps:.1f}fps, finalized={finalized})"
            )
            self.recording_path = None
            self._recording_transition.set()
            if self.on_recording_stopped:
                self.on_recording_stopped(path, duration, frames)

        elif evt_type == "frame":
            # Full preview frame (UI + screenshot saves)
            b64 = event.get("jpeg_base64", "")
            if b64:
                try:
                    jpeg_bytes = base64.b64decode(b64)
                    with self._frame_lock:
                        self._latest_frame = jpeg_bytes
                        self._frame_seq += 1
                    self._frame_event.set()
                except Exception as e:
                    print(f"[recorder] Frame decode error: {e}")

        elif evt_type == "regions":
            # OCR region crops — small JPEGs, one per scan region
            try:
                regions: dict[str, bytes] = {}
                for key in ("hud", "lobby", "crew", "deploy", "endgame", "killfeed"):
                    b64 = event.get(key) or ""
                    if b64:
                        regions[key] = base64.b64decode(b64)
                if regions:
                    with self._frame_lock:
                        self._latest_regions = regions
                        self._regions_seq += 1
                    self._regions_event.set()
            except Exception as e:
                print(f"[recorder] Region decode error: {e}")

        elif evt_type == "screenshot_saved":
            print(f"[recorder] Screenshot saved: {event.get('path')}")
            if hasattr(self, '_screenshot_confirmed'):
                self._screenshot_confirmed.set()

        elif evt_type == "error":
            msg = event.get("message", "Unknown error")
            self.last_error = msg
            print(f"[recorder] Error: {msg}")
            if self.on_error:
                self.on_error(msg)

    def _reset_recording_metrics(self):
        self.recording_duration = 0.0
        self.recording_captured_frames = 0
        self.recording_submitted_frames = 0
        self.recording_dropped_frames = 0
        self.recording_capture_fps = 0.0
        self.recording_submitted_fps = 0.0
        self.recording_capture_fps_recent = 0.0
        self.recording_submitted_fps_recent = 0.0
        self.recording_last_progress_at = 0.0
        self._last_progress_sample = None

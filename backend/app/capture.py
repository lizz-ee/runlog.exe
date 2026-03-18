"""
AutoCapture -- Automatic screen recording triggered by Marathon game state.

Architecture (WGC + NVENC primary, ddagrab fallback):

  PRIMARY (Window Capture):
    WGC captures Marathon window only (privacy safe, works when alt-tabbed)
    Every frame: NVENC GPU encode → H.264 file
    Every ~30 frames: JPEG encode → OCR detection
    On stop: ffmpeg mux H.264 → MP4 (<1 second)

  FALLBACK (Full Monitor):
    ddagrab → JPEG pipe → OCR (detection, 1fps)
    ddagrab → h264_nvenc → MP4 (recording, 60fps)

  OCR state machine:
    IDLE  --[READY_UP/RUN/DEPLOYING detected]--->  RECORDING
    RECORDING  --[PREPARE detected]--->  IDLE
      - if recording < 90s: delete (user backed out of lobby)
      - if recording >= 90s: queue for Sonnet processing

Debounce: require 2 consecutive identical readings before acting.
"""

import os
import queue
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .detection.ocr import detect_button_text

# Try importing WGC + NVENC
try:
    from .wgc_capture import WGCEngine, find_game_window, WGC_AVAILABLE, NVENC_AVAILABLE
    USE_WGC = WGC_AVAILABLE and NVENC_AVAILABLE
except ImportError:
    USE_WGC = False

MIN_RECORDING_SECONDS = 90
DEBOUNCE_COUNT = 2
MAX_PROCESSING_WORKERS = 2


class AutoCapture:
    """Automatic screen recorder driven by OCR game state detection.

    Uses WGC + NVENC when available (captures game window only).
    Falls back to ddagrab when WGC is unavailable or game not found.
    """

    def __init__(self, recordings_dir: str, clips_dir: str):
        self.recordings_dir = os.path.abspath(recordings_dir)
        self.clips_dir = os.path.abspath(clips_dir)
        os.makedirs(self.recordings_dir, exist_ok=True)
        os.makedirs(self.clips_dir, exist_ok=True)

        # State
        self._running = False
        self._recording = False
        self._recording_start: float = 0
        self._recording_path: str | None = None
        self._capture_mode: str = "none"  # "wgc" or "ddagrab"

        # WGC engine (if available)
        self._wgc: WGCEngine | None = None

        # Threads
        self._reader_thread: threading.Thread | None = None
        self._ocr_thread: threading.Thread | None = None
        self._dispatcher_thread: threading.Thread | None = None
        self._executor: ThreadPoolExecutor | None = None

        # FFmpeg processes (ddagrab fallback only)
        self._detection_proc: subprocess.Popen | None = None
        self._recording_proc: subprocess.Popen | None = None

        # Latest detection frame (JPEG bytes) for /frame endpoint + OCR
        self._latest_frame: bytes | None = None
        self._frame_seq: int = 0
        self._frame_lock = threading.Lock()

        # Debounce state
        self._last_detection: str | None = None
        self._consecutive_count: int = 0

        # Processing queue
        self._process_queue: queue.Queue = queue.Queue()
        self._last_process_result: dict | None = None
        self._processing_items: list[dict] = []
        self._processing_lock = threading.Lock()
        self.resumed_count: int = 0

    # -- Public API ----------------------------------------------------

    def start(self) -> dict:
        """Start detection and processing."""
        if self._running:
            return self.get_status()

        self._running = True
        print("[capture] Starting AutoCapture...")

        # Auto-resume unprocessed recordings
        self._resume_unprocessed()

        # Try WGC — if Marathon not found, wait (OCR loop will retry)
        if USE_WGC:
            game_window = find_game_window()
            if game_window:
                self._start_wgc(game_window)
            else:
                print("[capture] Marathon not found. Launch Marathon for game capture.")
                self._capture_mode = "waiting"
                # Start a watcher thread that checks for Marathon periodically
                self._reader_thread = threading.Thread(
                    target=self._wait_for_game, daemon=True, name="game-watcher"
                )
                self._reader_thread.start()
        else:
            print("[capture] WGC not available")
            self._capture_mode = "unavailable"

        # OCR loop (works with both WGC and ddagrab frames)
        self._ocr_thread = threading.Thread(
            target=self._ocr_loop, daemon=True, name="ocr"
        )
        self._ocr_thread.start()

        # Processing pool
        self._executor = ThreadPoolExecutor(
            max_workers=MAX_PROCESSING_WORKERS, thread_name_prefix="processor"
        )
        self._dispatcher_thread = threading.Thread(
            target=self._dispatcher_loop, daemon=True, name="dispatcher"
        )
        self._dispatcher_thread.start()

        return self.get_status()

    def stop(self) -> dict:
        """Stop everything."""
        self._running = False

        if self._recording:
            self._stop_recording()

        # Stop capture
        if self._wgc:
            self._wgc.stop()
            self._wgc = None

        self._kill_proc(self._detection_proc)
        self._detection_proc = None

        if self._executor:
            self._executor.shutdown(wait=False)

        for thread in [self._reader_thread, self._ocr_thread, self._dispatcher_thread]:
            if thread and thread.is_alive():
                thread.join(timeout=5)

        print("[capture] AutoCapture stopped.")
        return self.get_status()

    def get_status(self) -> dict:
        recording_seconds = 0
        if self._recording and self._recording_start:
            recording_seconds = time.time() - self._recording_start

        with self._processing_lock:
            items = [
                {
                    "file": i["file"],
                    "status": i["status"],
                    "run_id": i["run_id"],
                    "duration_seconds": i.get("duration_seconds"),
                    "created_at": i.get("created_at"),
                    "thumbnail": i.get("thumbnail"),
                }
                for i in self._processing_items
            ]

        processing_phase = None
        for item in items:
            if item["status"] not in ("queued", "done", "error"):
                processing_phase = item["status"]
                break

        status_counts = {}
        for item in items:
            s = item["status"]
            status_counts[s] = status_counts.get(s, 0) + 1

        return {
            "active": self._running,
            "recording": self._recording,
            "recording_seconds": round(recording_seconds, 1),
            "recording_path": self._recording_path,
            "queue_size": self._process_queue.qsize(),
            "processing_phase": processing_phase,
            "processing_items": items,
            "status_counts": status_counts,
            "resumed_count": self.resumed_count,
            "capture_mode": self._capture_mode,
            "last_result": self._last_process_result,
        }

    def get_latest_frame_jpeg(self) -> bytes | None:
        with self._frame_lock:
            return self._latest_frame

    # -- Game watcher (waits for Marathon to launch) ---------------------

    def _wait_for_game(self):
        """Poll for Marathon window every 5 seconds until found."""
        while self._running and self._capture_mode == "waiting":
            game_window = find_game_window()
            if game_window:
                print(f"[capture] Marathon detected! Starting WGC...")
                self._start_wgc(game_window)
                return
            time.sleep(5)
        print("[capture] Game watcher stopped.")

    # -- WGC capture (primary) -----------------------------------------

    def _start_wgc(self, window_name: str):
        """Start WGC window capture for both detection and recording."""
        self._wgc = WGCEngine(self.recordings_dir)
        if self._wgc.start(window_name):
            self._capture_mode = "wgc"
            print(f"[capture] WGC started on '{window_name}'")

            # WGC updates detection frames internally.
            # Start a thread to relay them to our frame store.
            self._reader_thread = threading.Thread(
                target=self._wgc_frame_relay, daemon=True, name="wgc-relay"
            )
            self._reader_thread.start()
        else:
            print("[capture] WGC failed to start, falling back to ddagrab")
            self._wgc = None
            self._start_ddagrab()

    def _wgc_frame_relay(self):
        """Relay detection frames from WGC engine to our frame store."""
        last_seq = -1
        while self._running:
            if self._wgc:
                frame, seq = self._wgc.get_latest_frame()
                if frame and seq != last_seq:
                    last_seq = seq
                    with self._frame_lock:
                        self._latest_frame = frame
                        self._frame_seq += 1
            time.sleep(0.1)
        print("[capture] WGC frame relay stopped.")

    # -- ddagrab fallback ----------------------------------------------

    def _start_ddagrab(self):
        """Start ddagrab full-monitor capture (fallback)."""
        self._capture_mode = "ddagrab"
        self._reader_thread = threading.Thread(
            target=self._ddagrab_reader, daemon=True, name="ddagrab-reader"
        )
        self._reader_thread.start()

    def _ddagrab_reader(self):
        """Read 1fps via ddagrab, store latest JPEG frame."""
        try:
            cmd = [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i',
                'ddagrab=framerate=2:output_idx=0,hwdownload,format=bgra',
                '-vf', 'fps=1',
                '-f', 'image2pipe', '-c:v', 'mjpeg', '-q:v', '5',
                'pipe:1',
            ]

            self._detection_proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            print("[capture] ddagrab reader started: 1fps")

            buf = b''
            while self._running:
                chunk = self._detection_proc.stdout.read(524288)
                if not chunk:
                    break
                buf += chunk

                latest_jpeg = None
                while True:
                    soi = buf.find(b'\xff\xd8')
                    if soi == -1:
                        buf = b''
                        break
                    eoi = buf.find(b'\xff\xd9', soi + 2)
                    if eoi == -1:
                        buf = buf[soi:]
                        break
                    latest_jpeg = buf[soi:eoi + 2]
                    buf = buf[eoi + 2:]

                if latest_jpeg:
                    with self._frame_lock:
                        self._latest_frame = latest_jpeg
                        self._frame_seq += 1

        except Exception as e:
            print(f"[capture] ddagrab reader error: {e}")
        finally:
            print("[capture] ddagrab reader stopped.")

    # -- OCR loop (works with both capture modes) ----------------------

    def _ocr_loop(self):
        """OCR the latest frame for game state detection."""
        last_seq = -1
        while self._running:
            with self._frame_lock:
                frame = self._latest_frame
                seq = self._frame_seq

            if frame is not None and seq != last_seq:
                last_seq = seq
                self._handle_detection(detect_button_text(frame))
            else:
                time.sleep(0.1)

        print("[capture] OCR loop stopped.")

    def _handle_detection(self, button_text: str | None):
        """Process OCR result with debounce."""
        if button_text == self._last_detection:
            self._consecutive_count += 1
        else:
            self._last_detection = button_text
            self._consecutive_count = 1

        if self._consecutive_count < DEBOUNCE_COUNT:
            return

        # Start recording: matchmaking "SEARCHING" screen (reliable, sits for 10s-3min)
        if not self._recording and button_text == 'SEARCHING':
            print(f"[capture] Detected 'SEARCHING' -- starting recording")
            self._start_recording()

        # Stop recording: lobby buttons mean run is over
        # PREPARE and READY_UP only — DEPLOYING/RUN are transient in-game states
        elif self._recording and button_text in ('PREPARE', 'READY_UP'):
            print(f"[capture] Detected '{button_text}' -- stopping recording")
            self._stop_recording()

    # -- Recording management ------------------------------------------

    def _start_recording(self):
        """Start recording using WGC+NVENC."""
        if self._capture_mode != "wgc" or not self._wgc:
            print("[capture] Cannot record — WGC not active")
            return

        path = self._wgc.start_recording()
        if path:
            self._recording = True
            self._recording_start = time.time()
            self._recording_path = path
            print(f"[capture] WGC recording to: {path}")
        else:
            print("[capture] WGC recording failed to start")

    def _stop_recording(self):
        """Stop WGC recording and handle the output file."""
        if self._wgc:
            mp4_path, duration = self._wgc.stop_recording()
            filepath = mp4_path
        else:
            duration = time.time() - self._recording_start
            filepath = self._recording_path

        self._recording = False
        self._recording_start = 0
        self._recording_path = None

        if not filepath or not os.path.exists(filepath):
            print("[capture] Recording file not found, skipping.")
            return

        if duration < MIN_RECORDING_SECONDS:
            print(f"[capture] Recording too short ({duration:.0f}s < {MIN_RECORDING_SECONDS}s), deleting.")
            try:
                os.remove(filepath)
            except OSError:
                pass
        else:
            print(f"[capture] Recording complete: {duration:.0f}s -> queued for processing")
            self._add_processing_item(filepath, duration)
            self._process_queue.put(filepath)

    # -- Processing queue tracking -------------------------------------

    def _add_processing_item(self, filepath: str, duration: float):
        """Add a recording to the processing items list."""
        filename = os.path.basename(filepath)
        thumb_name = filename.replace(".mp4", "_thumb.jpg")
        thumb_path = os.path.join(self.recordings_dir, thumb_name)

        # Generate thumbnail at 50% — always in-game for Marathon recordings.
        # -ss before -i for fast seeking (doesn't decode the whole file).
        if not (os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 5000):
            try:
                seek = max(1, int(duration * 0.5))
                subprocess.run(
                    ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                     '-ss', str(seek), '-i', filepath,
                     '-vframes', '1', '-vf', 'scale=384:-1',
                     '-q:v', '5', thumb_path],
                    capture_output=True, timeout=15,
                )
            except Exception:
                pass
        if not (os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 5000):
            thumb_name = None

        created_at = None
        try:
            ts_str = filename.replace("run_", "").replace(".mp4", "")
            dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            created_at = dt.isoformat()
        except ValueError:
            pass

        with self._processing_lock:
            self._processing_items.append({
                "file": filename,
                "path": filepath,
                "status": "queued",
                "run_id": None,
                "duration_seconds": round(duration),
                "created_at": created_at,
                "thumbnail": thumb_name,
            })

    def _update_processing_item(self, filepath: str, status: str, run_id: int | None = None):
        filename = os.path.basename(filepath)
        with self._processing_lock:
            for item in self._processing_items:
                if item["file"] == filename:
                    item["status"] = status
                    if run_id is not None:
                        item["run_id"] = run_id
                    break

    def remove_processing_item(self, filename: str):
        """Remove a processing item by filename (after keep/delete)."""
        with self._processing_lock:
            self._processing_items = [
                i for i in self._processing_items if i["file"] != filename
            ]

    # -- Processing (dispatcher + workers) -----------------------------

    def _dispatcher_loop(self):
        while self._running:
            try:
                filepath = self._process_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            self._executor.submit(self._process_one, filepath)
            self._process_queue.task_done()
        print("[dispatcher] Stopped.")

    def _process_one(self, filepath: str):
        from .video_processor import process_recording

        def on_phase(phase):
            self._update_processing_item(filepath, phase)

        print(f"[processor] Processing: {filepath}")
        try:
            result = process_recording(filepath, self.clips_dir, on_phase=on_phase)
            self._last_process_result = result
            if result["status"] == "success":
                self._update_processing_item(filepath, "done", run_id=result["run_id"])
                # Mark as processed so _resume_unprocessed skips it on next startup
                try:
                    with open(filepath + ".done", "w") as f:
                        f.write(str(result["run_id"]))
                except Exception:
                    pass
                print(f"[processor] Done: run #{result['run_id']}, {len(result['clips'])} clips")
            else:
                self._update_processing_item(filepath, "error")
                print(f"[processor] Failed: {result}")
        except Exception as e:
            self._update_processing_item(filepath, "error")
            print(f"[processor] Error: {e}")

    # -- Resume + helpers ----------------------------------------------

    def _resume_unprocessed(self):
        """Scan recordings directory for unprocessed .mp4 files."""
        try:
            mp4_files = [
                f for f in os.listdir(self.recordings_dir)
                if f.endswith(".mp4") and f.startswith("run_")
                and not any(f.endswith(s) for s in ("_compressed.mp4", "_2k.mp4", "_thumb.jpg"))
            ]
            if not mp4_files:
                return

            # Check what's already in the processing queue to avoid duplicates
            existing_files = set()
            with self._processing_lock:
                existing_files = {item["file"] for item in self._processing_items}

            resumed = 0
            for filename in sorted(mp4_files):
                if filename in existing_files:
                    continue

                filepath = os.path.join(self.recordings_dir, filename)

                # Skip if already processed (marker file from previous session)
                if os.path.exists(filepath + ".done"):
                    continue

                file_size = os.path.getsize(filepath)
                if file_size < 1024 * 1024:
                    continue

                try:
                    probe = subprocess.run(
                        ['ffprobe', '-v', 'quiet', '-show_entries',
                         'format=duration', '-of', 'csv=p=0', filepath],
                        capture_output=True, text=True, timeout=10,
                    )
                    duration = float(probe.stdout.strip()) if probe.stdout.strip() else 300
                except Exception:
                    duration = 300

                self._add_processing_item(filepath, duration)
                self._process_queue.put(filepath)
                resumed += 1

            if resumed:
                self.resumed_count = resumed
                print(f"[capture] Auto-resumed {resumed} unprocessed recording(s)")

        except Exception as e:
            print(f"[capture] Resume scan failed: {e}")

    @staticmethod
    def _kill_proc(proc: subprocess.Popen | None):
        """Gracefully terminate an FFmpeg subprocess."""
        if proc is None or proc.poll() is not None:
            return
        try:
            if proc.stdin:
                proc.stdin.write(b'q')
                proc.stdin.flush()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

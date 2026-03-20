"""
AutoCapture -- Automatic screen recording triggered by Marathon game state.

Architecture:
  Rust binary (runlog-recorder.exe) handles:
    - WGC window capture (Marathon only, privacy safe)
    - H.264 encoding via MediaFoundation HW encoder (zero-copy GPU, 60fps 4K)
    - OCR frames sent as base64 JPEG at ~2fps

  Python handles:
    - OCR game state detection (EasyOCR)
    - Recording start/stop commands
    - Screenshot management
    - Processing pipeline (Sonnet analysis)

  Three OCR regions:
    OCR.DEPLOY  (center)  — map name on deployment screen → START recording + screenshots
    OCR.ENDGAME (upper)   — //RUN_COMPLETE banner → log timestamp for stats
    OCR.LOBBY   (bottom)  — READY_UP → save loadout screenshot | PREPARE → STOP recording

  Detection flow:
    READY_UP detected → save readyup_latest.jpg (loadout/shell screenshot)
    Map name detected → START RECORDING + move readyup to run folder + save deploy screenshot
    RUN_COMPLETE detected → log endgame timestamp (recording continues)
    PREPARE detected → STOP RECORDING → queue for processing
"""

import os
import queue
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from PIL import Image
import io

from .detection.ocr import detect_game_state, DEPLOY_REGION
from .rust_recorder import RustRecorder

MAX_P1_WORKERS = 4   # Phase 1 (fast stats extraction) — unconstrained
MAX_P2_WORKERS = 2   # Phase 2 (video narrative + clips) — heavy, capped


class AutoCapture:
    """Automatic screen recorder driven by OCR game state detection."""

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
        self._capture_mode: str = "none"

        # Rust recorder
        self._recorder = RustRecorder()

        # Threads
        self._ocr_thread: threading.Thread | None = None
        self._dispatcher_thread: threading.Thread | None = None
        self._executor: ThreadPoolExecutor | None = None

        # Latest detection frame (JPEG bytes) for /frame endpoint + OCR
        self._latest_frame: bytes | None = None
        self._frame_seq: int = 0
        self._frame_lock = threading.Lock()

        # Detection state
        self._last_detection: str | None = None
        self._endgame_timestamp: float | None = None

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

        # Set Python process to above normal priority to prevent background throttling
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetCurrentProcess()
            kernel32.SetPriorityClass(handle, 0x00008000)  # ABOVE_NORMAL_PRIORITY_CLASS
            print("[capture] Python process priority: ABOVE_NORMAL")
        except Exception:
            pass

        # Auto-resume unprocessed recordings
        self._resume_unprocessed()

        # Start Rust recorder
        if self._recorder.available:
            if self._recorder.start():
                self._capture_mode = "wgc"
                print("[capture] Rust recorder started")
            else:
                print("[capture] Rust recorder failed to start")
                self._capture_mode = "unavailable"
        else:
            print("[capture] runlog-recorder.exe not found")
            self._capture_mode = "unavailable"

        # Frame relay thread (gets OCR frames from Rust binary)
        threading.Thread(
            target=self._frame_relay, daemon=True, name="frame-relay"
        ).start()

        # OCR loop
        self._ocr_thread = threading.Thread(
            target=self._ocr_loop, daemon=True, name="ocr"
        )
        self._ocr_thread.start()

        # Processing pools — Phase 1 (fast) + Phase 2 (heavy)
        self._p1_executor = ThreadPoolExecutor(
            max_workers=MAX_P1_WORKERS, thread_name_prefix="p1-processor"
        )
        self._p2_executor = ThreadPoolExecutor(
            max_workers=MAX_P2_WORKERS, thread_name_prefix="p2-processor"
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

        self._recorder.stop()

        if self._executor:
            self._executor.shutdown(wait=False)

        for thread in [self._ocr_thread, self._dispatcher_thread]:
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
                    "detail": i.get("detail"),
                    "p1_failed": i.get("p1_failed"),
                    "loading_screen_found": i.get("loading_screen_found"),
                    "stats_tab_found": i.get("stats_tab_found"),
                    "loadout_tab_found": i.get("loadout_tab_found"),
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
            "has_frame": self._latest_frame is not None,
            "window_found": self._recorder.window_name is not None,
            "last_detection": self._last_detection,
            "detection_count": 0,
            "last_result": self._last_process_result,
        }

    def get_latest_frame_jpeg(self) -> bytes | None:
        with self._frame_lock:
            return self._latest_frame

    # -- Frame relay (OCR frames from Rust binary) -------------------------

    def _frame_relay(self):
        """Relay OCR frames from Rust recorder to our frame store (~2fps)."""
        last_seq = -1
        while self._running:
            frame, seq = self._recorder.get_latest_frame()
            if frame and seq != last_seq:
                last_seq = seq
                with self._frame_lock:
                    self._latest_frame = frame
                    self._frame_seq += 1
            time.sleep(0.3)  # Rust sends frames at ~2fps, check ~3x/sec
        print("[capture] Frame relay stopped.")

    # -- OCR loop (state machine) ------------------------------------------
    # States: lobby → deploy → endgame → postgame → lobby
    # Each state scans ONE region for maximum speed (~300ms per detection)

    # State timeouts — fall back to lobby if stuck too long
    _STATE_TIMEOUTS = {
        'deploy': 90,     # 90s without finding map name → probably backed out
        'endgame': 1800,  # 30min without RUN_COMPLETE → game crashed or alt-tabbed
    }

    def _ocr_loop(self):
        """OCR the latest frame using state machine — one region at a time."""
        last_seq = -1
        self._scan_state = 'lobby'  # lobby | deploy | endgame | postgame
        self._state_changed_at = time.time()
        while self._running:
            with self._frame_lock:
                frame = self._latest_frame
                seq = self._frame_seq

            if frame is not None and seq != last_seq:
                last_seq = seq

                # Check for state timeout — fall back to lobby if stuck
                timeout = self._STATE_TIMEOUTS.get(self._scan_state)
                if timeout and (time.time() - self._state_changed_at) > timeout:
                    old_state = self._scan_state
                    self._scan_state = 'lobby'
                    self._state_changed_at = time.time()
                    print(f"[capture] State timeout: stuck in '{old_state}' for >{timeout}s, falling back to lobby")
                    if self._recording and old_state == 'endgame':
                        print(f"[capture] Stopping orphaned recording due to timeout")
                        self._stop_recording()

                result = detect_game_state(frame, scan_mode=self._scan_state)
                if self._running:
                    self._handle_detection(result, frame)
            else:
                time.sleep(0.1)

        print("[capture] OCR loop stopped.")

    # Map detection phases to screenshot slots (1 per phase, guaranteed)
    _PHASE_SLOTS = {'ready_up': 1, 'run': 2, 'deploying': 3}

    def _save_phase_screenshot(self, name: str, phase: str, frame_jpeg: bytes):
        """Save one screenshot per phase (overwrites within same phase, keeps latest)."""
        slot = self._PHASE_SLOTS.get(phase)
        if not slot:
            return 0
        path = os.path.join(self.recordings_dir, f"{name}_buf_{slot}.jpg")
        with open(path, "wb") as f:
            f.write(frame_jpeg)
        count = sum(1 for i in range(1, 4) if os.path.exists(os.path.join(self.recordings_dir, f"{name}_buf_{i}.jpg")))
        return count

    def _move_buffer(self, name: str, screenshots_dir: str):
        """Move all phase screenshots to the run screenshots folder."""
        import shutil
        moved = 0
        for i in range(1, 4):
            buf_path = os.path.join(self.recordings_dir, f"{name}_buf_{i}.jpg")
            if os.path.exists(buf_path):
                try:
                    shutil.move(buf_path, os.path.join(screenshots_dir, f"{name}_{i}.jpg"))
                    moved += 1
                except Exception:
                    pass
        return moved

    def _handle_detection(self, result: dict | None, frame_jpeg: bytes):
        """Process OCR detection result — act on first match, no debounce."""
        det_type = result['type'] if result else None

        self._last_detection = det_type if det_type else self._last_detection

        if not det_type:
            return

        # --- State transitions (simple toggle between 3 OCR regions) ---
        prev_state = self._scan_state
        if det_type == 'searching':
            self._scan_state = 'deploy'    # Matchmaking started → watch for map name
        elif det_type == 'deploy':
            self._scan_state = 'endgame'   # Map found → watch for RUN_COMPLETE
        elif det_type == 'endgame':
            self._scan_state = 'lobby'     # Run complete → watch lobby for PREPARE
        if self._scan_state != prev_state:
            self._state_changed_at = time.time()

        # --- READY UP / RUN / DEPLOYING: one screenshot per phase ---
        if det_type in ('ready_up', 'run', 'deploying'):
            try:
                count = self._save_phase_screenshot('readyup', det_type, frame_jpeg)
                slot = self._PHASE_SLOTS.get(det_type, '?')
                print(f"[capture] Readyup screenshot: slot {slot}/3 ({det_type}), {count} total")
            except Exception as e:
                print(f"[capture] Failed to save readyup screenshot: {e}")

        # --- DEPLOY: single screenshot + start recording + move readyup buffer ---
        elif det_type == 'deploy' and not self._recording:
            import shutil
            map_name = result.get('map_name', 'Unknown')
            print(f"[capture] Detected deployment: {map_name} -- starting recording")
            self._start_recording()

            if self._recording_path:
                rec_name = os.path.basename(self._recording_path).replace(".mp4", "")
                screenshots_dir = os.path.join(self.clips_dir, rec_name, "screenshots")
                os.makedirs(screenshots_dir, exist_ok=True)

                # Save single deploy screenshot (OCR frame — guaranteed correct)
                with open(os.path.join(screenshots_dir, "deploy.jpg"), "wb") as f:
                    f.write(frame_jpeg)
                print(f"[capture] Deploy screenshot saved: {map_name}")

                # Move readyup buffer to run folder (3 shots)
                readyup_moved = self._move_buffer('readyup', screenshots_dir)
                print(f"[capture] Moved {readyup_moved} readyup screenshots")

        # --- ENDGAME: single screenshot + log timestamp ---
        elif det_type == 'endgame' and self._recording:
            elapsed = time.time() - self._recording_start
            self._endgame_timestamp = elapsed
            print(f"[capture] RUN_COMPLETE at {elapsed:.1f}s into recording")

            if self._recording_path:
                rec_name = os.path.basename(self._recording_path).replace(".mp4", "")
                screenshots_dir = os.path.join(self.clips_dir, rec_name, "screenshots")
                os.makedirs(screenshots_dir, exist_ok=True)
                with open(os.path.join(screenshots_dir, "endgame.jpg"), "wb") as f:
                    f.write(frame_jpeg)
                print(f"[capture] Endgame screenshot saved")

        # --- PREPARE: stop recording (back in lobby) ---
        elif det_type == 'prepare' and self._recording:
            print(f"[capture] Detected PREPARE -- stopping recording")
            self._stop_recording()

        # --- SEARCHING: visual only, no action needed ---
        elif det_type == 'searching':
            pass

    # -- Recording management ------------------------------------------

    def _start_recording(self):
        """Start recording via Rust binary."""
        if not self._recorder.is_running:
            print("[capture] Cannot record — Rust recorder not running")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"run_{timestamp}.mp4"
        path = os.path.join(self.recordings_dir, filename)

        if self._recorder.start_recording(path):
            self._recording = True
            self._recording_start = time.time()
            self._recording_path = path
            print(f"[capture] Recording to: {path}")
        else:
            print("[capture] Recording failed to start")

    def _stop_recording(self):
        """Stop recording and queue the file for processing."""
        self._recorder.stop_recording()

        duration = time.time() - self._recording_start
        filepath = self._recording_path
        endgame_ts = self._endgame_timestamp

        self._recording = False
        self._recording_start = 0
        self._recording_path = None
        self._scan_state = 'lobby'
        self._endgame_timestamp = None

        if not filepath:
            print("[capture] No recording path, skipping.")
            return

        # Wait briefly for Rust to finalize the MP4
        time.sleep(1)

        if not os.path.exists(filepath):
            print(f"[capture] Recording file not found: {filepath}")
            return

        file_size = os.path.getsize(filepath)
        if file_size < 1024 * 1024:  # Less than 1MB = corrupt or empty
            print(f"[capture] Recording too small ({file_size} bytes), skipping: {filepath}")
            return

        print(f"[capture] Recording complete: {duration:.0f}s ({file_size / (1024*1024):.1f}MB)")

        # Save endgame timestamp for Phase 1
        if endgame_ts:
            try:
                with open(filepath + ".endgame", "w") as f:
                    f.write(str(round(endgame_ts, 1)))
                print(f"[capture] Endgame timestamp saved: {endgame_ts:.1f}s")
            except Exception:
                pass

        # Rust binary produces proper H.264 MP4 with faststart — no re-encode needed
        # Write encoded marker so processor doesn't try to re-encode
        try:
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            with open(filepath + ".encoded", "w") as f:
                f.write(f"{file_size_mb:.1f}MB")
        except Exception:
            pass

        # Add to processing queue
        self._add_processing_item(filepath, duration)
        self._generate_thumbnail(filepath, duration)
        self._process_queue.put(filepath)

    # -- Processing queue tracking -------------------------------------

    def _add_processing_item(self, filepath: str, duration: float, skip_thumbnail: bool = False):
        """Add a recording to the processing items list immediately."""
        filename = os.path.basename(filepath)

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
                "thumbnail": None,
            })

        if not skip_thumbnail:
            self._generate_thumbnail(filepath, duration)

    def _generate_thumbnail(self, filepath: str, duration: float):
        """Generate thumbnail in background — updates the processing item when done."""
        filename = os.path.basename(filepath)

        def _gen_thumb():
            thumb_name = filename.replace(".mp4", "_thumb.jpg")
            thumb_path = os.path.join(self.recordings_dir, thumb_name)
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
            if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 5000:
                with self._processing_lock:
                    for item in self._processing_items:
                        if item["file"] == filename:
                            item["thumbnail"] = thumb_name
                            break

        threading.Thread(target=_gen_thumb, daemon=True).start()

    def _update_processing_item(self, filepath: str, status: str, run_id: int | None = None, detail: str | None = None, p1_failed: bool | None = None):
        filename = os.path.basename(filepath)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._processing_lock:
            for item in self._processing_items:
                if item["file"] == filename:
                    old_status = item.get("status")
                    item["status"] = status
                    if run_id is not None:
                        item["run_id"] = run_id
                    if p1_failed is not None:
                        item["p1_failed"] = p1_failed
                    if detail is not None:
                        item["detail"] = detail
                    elif status != old_status:
                        item.pop("detail", None)
                    # Track phase timestamps
                    if status != old_status:
                        item["phase_started_at"] = now
                        if status == "extracting_frames":
                            item["p1_started_at"] = now
                        if status in ("phase1_done", "phase1_failed") and "p1_started_at" in item:
                            item["p1_ended_at"] = now
                        if status == "phase1_failed":
                            item["p1_failed"] = True
                        if status == "compressing":
                            item["p2_started_at"] = now
                        if status == "done" and "p2_started_at" in item:
                            item["p2_ended_at"] = now
                    break

    def remove_processing_item(self, filename: str):
        """Remove a processing item by filename (after keep/delete)."""
        with self._processing_lock:
            self._processing_items = [
                i for i in self._processing_items if i["file"] != filename
            ]

    def reset_processing_item(self, filename: str):
        """Reset a failed processing item to queued and re-queue it."""
        filepath = os.path.join(self.recordings_dir, filename)
        with self._processing_lock:
            for item in self._processing_items:
                if item["file"] == filename:
                    item["status"] = "queued"
                    item["run_id"] = None
                    item.pop("p1_failed", None)
                    break
        # Re-add to processing queue
        if os.path.exists(filepath):
            self._process_queue.put(filepath)
            print(f"[capture] Re-queued for processing: {filename}")

    # -- Processing (dispatcher + workers) -----------------------------

    def _dispatcher_loop(self):
        while self._running:
            try:
                filepath = self._process_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            self._p1_executor.submit(self._process_phase1, filepath)
            self._process_queue.task_done()
        print("[dispatcher] Stopped.")

    def _process_phase1(self, filepath: str):
        """Phase 1: encoding + stats extraction. Runs in P1 pool (fast, uncapped)."""
        from .video_processor import process_recording

        def on_phase(phase, detail=None):
            self._update_processing_item(filepath, phase, detail=detail)

        print(f"[p1] Processing: {filepath}")

        # New recordings from Rust recorder have .encoded marker (skip re-encode).
        encoded_marker = filepath + ".encoded"
        if not os.path.exists(encoded_marker):
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            on_phase("encoding")
            print(f"[p1] Legacy recording ({file_size_mb:.0f}MB), re-encoding...")
            encoded = self._reencode_recording(filepath)
            if encoded:
                filepath = encoded

        # Check if Phase 1 was already completed in a previous session
        p1_marker = filepath + ".p1done"
        if os.path.exists(p1_marker):
            try:
                run_id = int(open(p1_marker).read().strip())
                print(f"[p1] Already done (run #{run_id}), submitting to Phase 2...")
                self._update_processing_item(filepath, "phase1_done", run_id=run_id)
                self._p2_executor.submit(self._process_phase2, filepath, run_id)
                return
            except Exception as e:
                print(f"[p1] Resume failed: {e}, starting fresh")
                os.remove(p1_marker)

        try:
            result = process_recording(filepath, self.clips_dir, on_phase=on_phase)
            self._last_process_result = result
            if result["status"] != "success":
                self._update_processing_item(filepath, "error")
                print(f"[p1] Failed: {result}")
                return

            run_id = result["run_id"]

            # Store P1 detection flags on the processing item
            analysis = result.get("analysis", {})
            filename = os.path.basename(filepath)
            with self._processing_lock:
                for item in self._processing_items:
                    if item["file"] == filename:
                        item["loading_screen_found"] = analysis.get("loading_screen_found", False)
                        item["stats_tab_found"] = analysis.get("stats_tab_found", False)
                        item["loadout_tab_found"] = analysis.get("loadout_tab_found", False)
                        break

            if result.get("phase1_only"):
                self._update_processing_item(filepath, "phase1_done", run_id=run_id)
                try:
                    with open(filepath + ".p1done", "w") as f:
                        f.write(str(run_id))
                except Exception:
                    pass

                # Submit Phase 2 to the P2 pool (capped at 2 concurrent)
                print(f"[p1] Done, submitting Phase 2 for run #{run_id}...")
                self._p2_executor.submit(self._process_phase2, filepath, run_id)
            else:
                # Legacy pipeline — no Phase 2 needed
                self._update_processing_item(filepath, "done", run_id=run_id)
                self._last_process_result = result
                try:
                    with open(filepath + ".done", "w") as f:
                        f.write(str(run_id))
                except Exception:
                    pass
                print(f"[p1] Done (legacy): run #{run_id}")

        except Exception as e:
            self._update_processing_item(filepath, "error")
            print(f"[p1] Error: {e}")

    def _process_phase2(self, filepath: str, run_id: int):
        """Phase 2: video narrative + clip cutting. Runs in P2 pool (capped at 2)."""
        from .video_processor import process_recording_phase2

        def on_phase(phase, detail=None):
            self._update_processing_item(filepath, phase, detail=detail)

        try:
            time.sleep(1)
            print(f"[p2] Starting Phase 2 for run #{run_id}...")
            p2_result = process_recording_phase2(
                filepath, self.clips_dir, run_id, on_phase=on_phase
            )
            if p2_result["status"] == "success":
                print(f"[p2] Done: run #{run_id}, {len(p2_result.get('clips', []))} clips")
            else:
                print(f"[p2] Failed: {p2_result}")
                try:
                    log_path = os.path.join(self.recordings_dir, "phase2_errors.log")
                    with open(log_path, "a") as f:
                        from datetime import datetime
                        f.write(f"\n--- {datetime.now().isoformat()} | run #{run_id} | {os.path.basename(filepath)} ---\n")
                        f.write(f"Result: {p2_result}\n")
                except Exception:
                    pass

            # Check if Phase 2 actually completed by looking at the DB
            p2_failed = False
            if not p2_result or p2_result["status"] != "success":
                try:
                    from .database import SessionLocal
                    from .models import Run
                    db = SessionLocal()
                    run = db.query(Run).filter(Run.id == run_id).first()
                    p2_failed = run is None or not run.summary
                    db.close()
                except Exception:
                    p2_failed = True

            self._update_processing_item(filepath, "done", run_id=run_id, p1_failed=p2_failed)
            try:
                with open(filepath + ".done", "w") as f:
                    f.write(str(run_id))
                # Clean up p1done marker
                p1_marker = filepath + ".p1done"
                if os.path.exists(p1_marker):
                    os.remove(p1_marker)
            except Exception:
                pass

        except Exception as e:
            self._update_processing_item(filepath, "error")
            print(f"[p2] Error: {e}")

    def _reencode_recording(self, raw_path: str) -> str | None:
        """Re-encode recording to proper seekable H.264 MP4 (fallback for old recordings)."""
        encoded_path = raw_path.replace(".mp4", "_enc.mp4")
        raw_size = os.path.getsize(raw_path) / (1024 * 1024)
        print(f"[capture] Re-encoding {raw_size:.0f}MB recording via NVENC...")
        t0 = time.time()

        try:
            result = subprocess.run([
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
                '-i', raw_path,
                '-c:v', 'h264_nvenc', '-preset', 'p4', '-cq', '23',
                '-an', '-movflags', '+faststart', '-pix_fmt', 'yuv420p',
                encoded_path,
            ], capture_output=True, text=True, timeout=300)

            if result.returncode != 0:
                print(f"[capture] Re-encode failed: {result.stderr[:200]}")
                if os.path.exists(encoded_path):
                    os.remove(encoded_path)
                return None

            enc_size = os.path.getsize(encoded_path) / (1024 * 1024)
            elapsed = time.time() - t0
            print(f"[capture] Re-encoded: {raw_size:.0f}MB -> {enc_size:.0f}MB in {elapsed:.1f}s")

            final_path = raw_path
            os.remove(raw_path)
            os.rename(encoded_path, final_path)
            try:
                with open(final_path + ".encoded", "w") as f:
                    f.write(f"{enc_size:.1f}MB")
            except Exception:
                pass

            return final_path
        except subprocess.TimeoutExpired:
            print("[capture] Re-encode timed out (300s)")
            if os.path.exists(encoded_path):
                os.remove(encoded_path)
            return None
        except Exception as e:
            print(f"[capture] Re-encode error: {e}")
            if os.path.exists(encoded_path):
                os.remove(encoded_path)
            return None

    # -- Resume + helpers ----------------------------------------------

    def _resume_unprocessed(self):
        """Scan recordings directory for unprocessed .mp4 files."""
        try:
            mp4_files = [
                f for f in os.listdir(self.recordings_dir)
                if f.endswith(".mp4") and f.startswith("run_")
                and not any(f.endswith(s) for s in ("_compressed.mp4", "_2k.mp4", "_enc.mp4", "_thumb.jpg"))
            ]
            if not mp4_files:
                return

            existing_files = set()
            with self._processing_lock:
                existing_files = {item["file"] for item in self._processing_items}

            resumed = 0
            for filename in sorted(mp4_files):
                if filename in existing_files:
                    continue

                filepath = os.path.join(self.recordings_dir, filename)

                file_size = os.path.getsize(filepath)
                if file_size < 1024 * 1024:
                    continue

                # Already processed — restore to queue as "done" so user can SAVE/DISCARD
                done_marker = filepath + ".done"
                if os.path.exists(done_marker):
                    try:
                        run_id = int(open(done_marker).read().strip())
                    except Exception:
                        run_id = None
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
                    self._update_processing_item(filepath, "done", run_id=run_id)
                    resumed += 1
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

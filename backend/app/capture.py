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
        self._scan_state: str = 'lobby'
        self._state_changed_at: float = 0

        # Processing queue + executors
        self._process_queue: queue.Queue = queue.Queue()
        self._last_process_result: dict | None = None
        self._processing_items: list[dict] = []
        self._processing_lock = threading.Lock()
        self.resumed_count: int = 0
        self._p1_executor: ThreadPoolExecutor | None = None
        self._p2_executor: ThreadPoolExecutor | None = None

        # P2 gating — track active count, hold overflow in waiting list
        self._p2_active: int = 0
        self._p2_active_lock = threading.Lock()
        self._p2_waiting: list[tuple[str, int]] = []  # [(filepath, run_id), ...]
        self._p2_max_workers: int = MAX_P2_WORKERS

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
        except Exception as e:
            print(f"[capture] Could not set process priority: {e}")

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
        # Read worker counts from config, fall back to defaults
        from .api.settings_api import get_config_value
        p1_workers = get_config_value("p1_workers") or MAX_P1_WORKERS
        p2_workers = get_config_value("p2_workers") or MAX_P2_WORKERS
        self._p2_max_workers = p2_workers
        print(f"[capture] Processing pools: P1={p1_workers} workers, P2={p2_workers} workers")
        self._p1_executor = ThreadPoolExecutor(
            max_workers=p1_workers, thread_name_prefix="p1-processor"
        )
        self._p2_executor = ThreadPoolExecutor(
            max_workers=p2_workers, thread_name_prefix="p2-processor"
        )
        self._dispatcher_thread = threading.Thread(
            target=self._dispatcher_loop, daemon=True, name="dispatcher"
        )
        self._dispatcher_thread.start()

        # Auto-resume unprocessed recordings (after executors are ready)
        self._resume_unprocessed()

        self._broadcast_status()
        return self.get_status()

    def stop(self) -> dict:
        """Stop everything."""
        self._running = False

        if self._recording:
            self._stop_recording()

        self._recorder.stop()

        # Clear stale frame so detection feed shows "AWAITING SIGNAL" instead of frozen game screen
        with self._frame_lock:
            self._latest_frame = None
        self._last_detection = None

        if self._executor:
            self._executor.shutdown(wait=False)
        if self._p1_executor:
            self._p1_executor.shutdown(wait=False)
        if self._p2_executor:
            self._p2_executor.shutdown(wait=False)

        for thread in [self._ocr_thread, self._dispatcher_thread]:
            if thread and thread.is_alive():
                thread.join(timeout=5)

        print("[capture] AutoCapture stopped.")
        self._broadcast_status()
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
                    "file_size_mb": i.get("file_size_mb"),
                    "p1_failed": i.get("p1_failed"),
                    "p2_failed": i.get("p2_failed"),
                    "loading_screen_found": i.get("loading_screen_found"),
                    "stats_tab_found": i.get("stats_tab_found"),
                    "loadout_tab_found": i.get("loadout_tab_found"),
                }
                for i in self._processing_items
            ]

        processing_phase = None
        for item in items:
            if item["status"] not in ("queued", "error"):
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
            "last_result": self._last_process_result,  # protected by _processing_lock at write site
        }

    def get_latest_frame_jpeg(self) -> bytes | None:
        with self._frame_lock:
            return self._latest_frame

    def _broadcast_status(self):
        """Push current status to all SSE clients."""
        try:
            from .api.sse import broadcast
            broadcast("capture_status", self.get_status())
        except Exception:
            pass

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
            time.sleep(0.05)  # Poll fast — relay is just a reference copy, negligible CPU
        print("[capture] Frame relay stopped.")

    # -- OCR loop (state machine) ------------------------------------------
    # States: lobby → deploy → endgame → postgame → lobby
    # Each state scans ONE region for maximum speed (~300ms per detection)

    # State timeouts — fall back to lobby if stuck too long
    _STATE_TIMEOUTS = {
        'endgame': 1800,  # 30min without RUN_COMPLETE → game crashed or alt-tabbed
        'postgame': 30,   # 30s without stats screen → missed it, back to lobby
    }

    def _ocr_loop(self):
        """OCR the latest frame using state machine — one region at a time."""
        last_seq = -1
        self._scan_state = 'lobby'  # lobby | deploy | endgame | postgame
        self._state_changed_at = time.time()
        deploy_cycle = 0  # Counter for lobby re-check while in deploy state
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

                # While in deploy state, check lobby every 5th cycle to detect
                # if user cancelled matchmaking and returned to lobby
                if self._scan_state == 'deploy':
                    deploy_cycle += 1
                    if deploy_cycle % 5 == 0:
                        lobby_result = detect_game_state(frame, scan_mode='lobby')
                        if lobby_result and lobby_result['type'] in ('prepare', 'select_zone', 'ready_up'):
                            print(f"[capture] Lobby re-detected ({lobby_result['type']}) while in deploy — returning to lobby state")
                            self._scan_state = 'lobby'
                            self._state_changed_at = time.time()
                            deploy_cycle = 0
                            continue
                else:
                    deploy_cycle = 0

                result = detect_game_state(frame, scan_mode=self._scan_state)
                if self._running:
                    self._handle_detection(result, frame)
            else:
                time.sleep(0.1)

        print("[capture] OCR loop stopped.")

    # Map detection phases to descriptive filenames
    _PHASE_NAMES = {'ready_up': 'readyup', 'run': 'run', 'deploying': 'deploying'}
    _PHASE_SLOTS = {'ready_up': 1, 'run': 2, 'deploying': 3}

    def _save_phase_screenshot(self, name: str, phase: str, frame_jpeg: bytes):
        """Save one screenshot per phase — full + center crop. Overwrites within same phase."""
        phase_name = self._PHASE_NAMES.get(phase)
        if not phase_name:
            return 0

        # Save full screenshot
        full_path = os.path.join(self.recordings_dir, f"{name}_buf_{phase_name}.jpg")
        with open(full_path, "wb") as f:
            f.write(frame_jpeg)

        # Save center-cropped version (39-61%w, 39-64%h — loadout/shell/HUD)
        try:
            img = Image.open(io.BytesIO(frame_jpeg))
            w, h = img.size
            crop = img.crop((int(w * 0.39), int(h * 0.39), int(w * 0.61), int(h * 0.64)))
            crop_path = os.path.join(self.recordings_dir, f"{name}_buf_{phase_name}_crop.jpg")
            crop.save(crop_path, "JPEG", quality=85)

            # For deploying phase: also generate character model + face crops for shell ID
            if phase_name == 'deploying':
                char_crop = img.crop((int(w * 0.395), int(h * 0.10), int(w * 0.605), int(h * 0.43)))
                char_crop.save(os.path.join(self.recordings_dir, f"{name}_buf_character_crop.jpg"), "JPEG", quality=90)
                face_crop = img.crop((int(w * 0.395), int(h * 0.43), int(w * 0.439), int(h * 0.581)))
                face_crop.save(os.path.join(self.recordings_dir, f"{name}_buf_face_crop.jpg"), "JPEG", quality=90)
        except Exception as e:
            print(f"[capture] Crop failed for {phase_name}: {e}")

        phases = ['readyup', 'run', 'deploying']
        count = sum(1 for p in phases if os.path.exists(os.path.join(self.recordings_dir, f"{name}_buf_{p}.jpg")))
        return count

    def _save_deploy_shot(self, screenshots_dir: str, name: str, frame_jpeg: bytes):
        """Save a deploy screenshot — full + center crop for coordinate reading."""
        try:
            with open(os.path.join(screenshots_dir, f"{name}.jpg"), "wb") as f:
                f.write(frame_jpeg)
            # Center crop (39-61%w, 39-64%h) for coordinate readability
            img = Image.open(io.BytesIO(frame_jpeg))
            w, h = img.size
            crop = img.crop((int(w * 0.39), int(h * 0.39), int(w * 0.61), int(h * 0.64)))
            crop.save(os.path.join(screenshots_dir, f"{name}_crop.jpg"), "JPEG", quality=85)
        except Exception as e:
            print(f"[capture] Deploy shot save failed ({name}): {e}")

    def _save_stats_shot(self, screenshots_dir: str, name: str, frame_jpeg: bytes):
        """Save a stats screenshot — full + wide crop (all columns, ELIMINATED through Run Time)."""
        try:
            with open(os.path.join(screenshots_dir, f"{name}.jpg"), "wb") as f:
                f.write(frame_jpeg)
            # Wide crop: all 3 player columns, from ELIMINATED banner to Run Time
            img = Image.open(io.BytesIO(frame_jpeg))
            w, h = img.size
            crop = img.crop((int(w * 0.03), int(h * 0.55), int(w * 0.97), int(h * 0.92)))
            crop.save(os.path.join(screenshots_dir, f"{name}_crop.jpg"), "JPEG", quality=95)
        except Exception as e:
            print(f"[capture] Stats shot save failed ({name}): {e}")

    def _move_buffer(self, name: str, screenshots_dir: str):
        """Move all phase screenshots (full + crop) to the run screenshots folder."""
        import shutil
        moved = 0
        for phase_name in ['readyup', 'run', 'deploying']:
            # Move full screenshot
            buf_path = os.path.join(self.recordings_dir, f"{name}_buf_{phase_name}.jpg")
            if os.path.exists(buf_path):
                try:
                    shutil.move(buf_path, os.path.join(screenshots_dir, f"{phase_name}.jpg"))
                    moved += 1
                except Exception as e:
                    print(f"[capture] Failed to move {phase_name}.jpg buffer: {e}")
            # Move crop
            crop_path = os.path.join(self.recordings_dir, f"{name}_buf_{phase_name}_crop.jpg")
            if os.path.exists(crop_path):
                try:
                    shutil.move(crop_path, os.path.join(screenshots_dir, f"{phase_name}_crop.jpg"))
                except Exception as e:
                    print(f"[capture] Failed to move {phase_name}_crop.jpg buffer: {e}")
        # Move character model + face crops (from deploying phase)
        for crop_name in ['character_crop', 'face_crop']:
            buf_path = os.path.join(self.recordings_dir, f"{name}_buf_{crop_name}.jpg")
            if os.path.exists(buf_path):
                try:
                    shutil.move(buf_path, os.path.join(screenshots_dir, f"{crop_name}.jpg"))
                except Exception as e:
                    print(f"[capture] Failed to move {crop_name}.jpg buffer: {e}")
        # Also move legacy numbered files if they exist
        for i in range(1, 4):
            buf_path = os.path.join(self.recordings_dir, f"{name}_buf_{i}.jpg")
            if os.path.exists(buf_path):
                try:
                    shutil.move(buf_path, os.path.join(screenshots_dir, f"{name}_{i}.jpg"))
                    moved += 1
                except Exception as e:
                    print(f"[capture] Failed to move numbered buffer {i}: {e}")
        return moved

    def _handle_detection(self, result: dict | None, frame_jpeg: bytes):
        """Process OCR detection result — act on first match, no debounce."""
        det_type = result['type'] if result else None

        if not det_type:
            return

        # --- State transitions (simple toggle between 3 OCR regions) ---
        prev_state = self._scan_state
        if det_type == 'searching':
            self._scan_state = 'deploy'    # Matchmaking started → watch for map name
        elif det_type == 'deploy':
            self._scan_state = 'endgame'   # Map found → watch for RUN_COMPLETE
        elif det_type == 'endgame':
            # Ignore false endgame during deploy/loading — require at least 30s of recording
            if self._recording and (time.time() - self._recording_start) < 30:
                return  # Don't update last_detection either — prevents overlay showing RUN.COMPLETE prematurely
            self._scan_state = 'postgame'  # Run complete → watch for stats screen
        elif det_type in ('exfiltrated', 'eliminated'):
            self._scan_state = 'lobby'     # Stats captured → watch lobby for PREPARE

        # Only update last_detection AFTER guard checks pass
        self._last_detection = det_type
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

        # --- DEPLOY: 3-shot burst + start recording + move readyup buffer ---
        elif det_type == 'deploy' and not self._recording:
            import shutil
            import json as _json
            map_name = result.get('map_name', 'Unknown')
            is_ranked = result.get('is_ranked', False)
            print(f"[capture] Detected deployment: {map_name}{' (RANKED)' if is_ranked else ''} -- starting recording")
            self._start_recording()

            # Write session marker alongside recording
            if self._recording_path:
                try:
                    from .main import get_or_create_session
                    with open(self._recording_path + ".session", "w") as f:
                        f.write(str(get_or_create_session()))
                except Exception as e:
                    print(f"[capture] Failed to write session marker: {e}")

            if self._recording_path:
                rec_name = os.path.basename(self._recording_path).replace(".mp4", "")
                screenshots_dir = os.path.join(self.clips_dir, rec_name, "screenshots")
                os.makedirs(screenshots_dir, exist_ok=True)

                # Save run metadata for the processor (ranked flag)
                if is_ranked:
                    with open(os.path.join(screenshots_dir, "metadata.json"), "w") as f:
                        _json.dump({"is_ranked": True}, f)

                # Shot 1: immediate (may catch contract screen — too early)
                self._save_deploy_shot(screenshots_dir, "deploy_1", frame_jpeg)
                print(f"[capture] Deploy shot 1/3 saved: {map_name}")

                # Shots 2 & 3: wait for genuinely new frames (2s apart like stats)
                def _delayed_deploy_shots():
                    prev_seq = self._frame_seq
                    # Shot 2: wait ~2s for a new frame
                    time.sleep(2.0)
                    for _ in range(10):
                        if self._frame_seq != prev_seq:
                            break
                        time.sleep(0.1)
                    frame2 = self._latest_frame
                    if frame2:
                        self._save_deploy_shot(screenshots_dir, "deploy_2", frame2)
                        print(f"[capture] Deploy shot 2/3 saved (seq {self._frame_seq})")
                    # Shot 3: wait another ~2s
                    prev_seq = self._frame_seq
                    time.sleep(2.0)
                    for _ in range(10):
                        if self._frame_seq != prev_seq:
                            break
                        time.sleep(0.1)
                    frame3 = self._latest_frame
                    if frame3:
                        self._save_deploy_shot(screenshots_dir, "deploy_3", frame3)
                        print(f"[capture] Deploy shot 3/3 saved (seq {self._frame_seq})")

                threading.Thread(target=_delayed_deploy_shots, daemon=True).start()

                # Move readyup buffer to run folder (3 shots)
                readyup_moved = self._move_buffer('readyup', screenshots_dir)
                print(f"[capture] Moved {readyup_moved} readyup screenshots")

        # --- ENDGAME: single screenshot + log timestamp ---
        elif det_type == 'endgame' and self._recording:
            elapsed = time.time() - self._recording_start
            self._endgame_timestamp = elapsed
            print(f"[capture] RUN_COMPLETE at {elapsed:.1f}s into recording")
            # Switch Rust OCR to fast direct mode for postgame detection
            self._recorder.set_ocr_fast(True)

            if self._recording_path:
                rec_name = os.path.basename(self._recording_path).replace(".mp4", "")
                screenshots_dir = os.path.join(self.clips_dir, rec_name, "screenshots")
                os.makedirs(screenshots_dir, exist_ok=True)
                with open(os.path.join(screenshots_dir, "endgame.jpg"), "wb") as f:
                    f.write(frame_jpeg)
                print(f"[capture] Endgame screenshot saved")

                # Crop the damage widget (Neural Link Severed / death screen)
                try:
                    from PIL import Image
                    import io
                    img = Image.open(io.BytesIO(frame_jpeg))
                    w, h = img.size
                    crop = img.crop((int(w * 0.74), int(h * 0.17), int(w * 0.97), int(h * 0.75)))
                    crop.save(os.path.join(screenshots_dir, "endgame_damage.jpg"), "JPEG", quality=95)
                    print(f"[capture] Endgame damage crop saved ({crop.size[0]}x{crop.size[1]})")
                except Exception as e:
                    print(f"[capture] Damage crop failed: {e}")

        # --- POSTGAME: stats screenshot (exfiltrated/eliminated) ---
        elif det_type in ('exfiltrated', 'eliminated') and self._recording:
            print(f"[capture] Detected {det_type.upper()} — saving stats screenshots (3-shot burst)")
            if self._recording_path:
                rec_name = os.path.basename(self._recording_path).replace(".mp4", "")
                screenshots_dir = os.path.join(self.clips_dir, rec_name, "screenshots")
                os.makedirs(screenshots_dir, exist_ok=True)

                # Shot 1: immediate (banner screen)
                self._save_stats_shot(screenshots_dir, "stats_1", frame_jpeg)
                print(f"[capture] Stats shot 1/3 saved ({det_type})")

                # Shots 2 & 3: faster timing to catch stats before player clicks to PROGRESS
                def _delayed_stats_shots():
                    prev_seq = self._frame_seq
                    # Shot 2: wait ~1s for stats animation to complete
                    time.sleep(1.0)
                    for _ in range(10):
                        if self._frame_seq != prev_seq:
                            break
                        time.sleep(0.1)
                    frame2 = self._latest_frame
                    if frame2:
                        self._save_stats_shot(screenshots_dir, "stats_2", frame2)
                        print(f"[capture] Stats shot 2/3 saved (seq {self._frame_seq})")
                    # Shot 3: wait another ~1.5s
                    prev_seq = self._frame_seq
                    time.sleep(1.5)
                    for _ in range(10):
                        if self._frame_seq != prev_seq:
                            break
                        time.sleep(0.1)
                    frame3 = self._latest_frame
                    if frame3:
                        self._save_stats_shot(screenshots_dir, "stats_3", frame3)
                        print(f"[capture] Stats shot 3/3 saved (seq {self._frame_seq})")

                threading.Thread(target=_delayed_stats_shots, daemon=True).start()

        # --- PREPARE: stop recording (back in lobby) ---
        elif det_type == 'prepare' and self._recording:
            print(f"[capture] Detected PREPARE -- stopping recording")
            self._stop_recording()

        # --- SEARCHING: visual only, no action needed ---
        elif det_type == 'searching':
            pass

    # -- Recording management ------------------------------------------

    def _start_recording(self):
        """Start recording via Rust binary, using settings from config."""
        if not self._recorder.is_running:
            print("[capture] Cannot record — Rust recorder not running")
            return

        # Load recording settings from config
        from .api.settings_api import get_config_value
        encoder = get_config_value("encoder") or "hevc"
        bitrate_mbps = get_config_value("bitrate") or 50
        fps = get_config_value("fps") or 60
        bitrate = int(bitrate_mbps) * 1_000_000

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"run_{timestamp}.mp4"
        path = os.path.join(self.recordings_dir, filename)

        if self._recorder.start_recording(path, bitrate=bitrate, encoder=encoder, fps=fps):
            self._recording = True
            self._recording_start = time.time()
            self._recording_path = path
            print(f"[capture] Recording to: {path} ({encoder.upper()}, {bitrate_mbps}Mbps, {fps}fps)")
            self._broadcast_status()
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
        self._broadcast_status()

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

        # Get file size
        file_size_mb = None
        try:
            file_size_mb = round(os.path.getsize(filepath) / (1024 * 1024), 1)
        except Exception:
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
                "file_size_mb": file_size_mb,
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
                # Prefer endgame screenshot (RUN_COMPLETE / death screen)
                run_tag = filename.replace(".mp4", "")
                endgame_jpg = os.path.join(self.clips_dir, run_tag, "screenshots", "endgame.jpg")
                if os.path.exists(endgame_jpg):
                    import shutil
                    shutil.copy2(endgame_jpg, thumb_path)
                else:
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

    def _update_processing_item(self, filepath: str, status: str, run_id: int | None = None, detail: str | None = None, p1_failed: bool | None = None, p2_failed: bool | None = None):
        filename = os.path.basename(filepath)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        status_changed = False
        with self._processing_lock:
            for item in self._processing_items:
                if item["file"] == filename:
                    old_status = item.get("status")
                    item["status"] = status
                    if run_id is not None:
                        item["run_id"] = run_id
                    if p1_failed is not None:
                        item["p1_failed"] = p1_failed
                    if p2_failed is not None:
                        item["p2_failed"] = p2_failed
                    if detail is not None:
                        item["detail"] = detail
                    elif status != old_status:
                        item.pop("detail", None)
                    # Track phase timestamps
                    if status != old_status:
                        status_changed = True
                        item["phase_started_at"] = now
                        if status == "extracting_frames":
                            item["p1_started_at"] = now
                        if status in ("phase1_done", "phase1_failed") and "p1_started_at" in item:
                            item["p1_ended_at"] = now
                        if status == "phase1_failed":
                            item["p1_failed"] = True
                        if status == "analyzing_gameplay":
                            item["p2_started_at"] = now
                        if status == "done" and "p2_started_at" in item:
                            item["p2_ended_at"] = now
                    break
        if status_changed:
            self._broadcast_status()

    def remove_processing_item(self, filename: str):
        """Remove a processing item by filename (after keep/delete)."""
        with self._processing_lock:
            self._processing_items = [
                i for i in self._processing_items if i["file"] != filename
            ]
        self._broadcast_status()

    def _auto_save_recording(self, filepath: str, run_id: int | None):
        """Auto-save recording after processing completes. Moves to clips folder,
        links to run, generates thumbnail + sprite sheet, sets status to 'complete'."""
        import shutil
        filename = os.path.basename(filepath)
        run_tag = filename.replace(".mp4", "")
        run_folder = os.path.join(self.clips_dir, run_tag)
        os.makedirs(run_folder, exist_ok=True)
        saved_path = os.path.join(run_folder, filename)

        if os.path.exists(saved_path):
            # Already moved (previous session) — just use existing path
            print(f"[auto-save] Recording already in place: {saved_path}")
        elif os.path.exists(filepath):
            try:
                shutil.move(filepath, saved_path)
            except Exception as e:
                print(f"[auto-save] Failed to move recording: {e}")
                return
        else:
            print(f"[auto-save] Recording not found: {filepath}")
            return

        # Move thumbnail if it exists
        thumb = filename.replace(".mp4", "_thumb.jpg")
        thumb_path = os.path.join(self.recordings_dir, thumb)
        if os.path.exists(thumb_path):
            shutil.move(thumb_path, os.path.join(run_folder, thumb))

        # Link recording to run in database
        if run_id:
            try:
                from .database import SessionLocal
                from .models import Run
                db = SessionLocal()
                run = db.query(Run).filter(Run.id == run_id).first()
                if run:
                    run.recording_path = saved_path
                    db.commit()
                db.close()
            except Exception as e:
                print(f"[auto-save] DB update failed: {e}")

        # Generate thumbnail + sprite sheet BEFORE marking complete
        try:
            probe = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-show_entries',
                 'format=duration', '-of', 'csv=p=0', saved_path],
                capture_output=True, text=True, timeout=10
            )
            duration = float(probe.stdout.strip()) if probe.stdout.strip() else 300

            keep_thumb = saved_path.replace(".mp4", "_thumb.jpg")
            if not os.path.exists(keep_thumb):
                endgame_jpg = os.path.join(os.path.dirname(saved_path), "screenshots", "endgame.jpg")
                if os.path.exists(endgame_jpg):
                    shutil.copy2(endgame_jpg, keep_thumb)
                else:
                    mid = duration * 0.5
                    subprocess.run(
                        ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                         '-ss', str(mid), '-i', saved_path,
                         '-vframes', '1', '-vf', 'scale=384:-1',
                         '-q:v', '5', keep_thumb],
                        capture_output=True, timeout=30,
                    )

            sprite_path = saved_path.replace(".mp4", "_sprite.jpg")
            if not os.path.exists(sprite_path):
                from .video_processor import _generate_sprite_sheet
                _generate_sprite_sheet(saved_path, duration)
        except Exception as e:
            print(f"[auto-save] Asset generation failed: {e}")

        # Clean up marker files
        for ext in ('.p1done', '.encoded', '.endgame', '.session'):
            marker = filepath + ext
            if os.path.exists(marker):
                os.remove(marker)

        print(f"[auto-save] Recording saved: {saved_path}")

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

    def retry_processing(self, filename: str):
        """Retry a failed processing item. Resumes from where it left off."""
        filepath = os.path.join(self.recordings_dir, filename)
        run_id = None
        has_p1 = os.path.exists(filepath + ".p1done")

        with self._processing_lock:
            for item in self._processing_items:
                if item["file"] == filename:
                    run_id = item.get("run_id")
                    break

        if has_p1 and run_id and self._p2_executor:
            # Phase 1 done — retry just Phase 2 (gated by P2 worker limit)
            self._submit_phase2(filepath, run_id)
            print(f"[capture] Retrying Phase 2 for run #{run_id}: {filename}")
            return True
        elif os.path.exists(filepath):
            # Full retry from Phase 1
            self._update_processing_item(filepath, "queued")
            self._process_queue.put(filepath)
            print(f"[capture] Retrying from Phase 1: {filename}")
            return True
        return False

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
        """Phase 1: stats extraction. Runs in P1 pool."""
        from .video_processor import process_recording

        def on_phase(phase, detail=None):
            self._update_processing_item(filepath, phase, detail=detail)

        print(f"[p1] Processing: {filepath}")

        # Check if Phase 1 was already completed in a previous session
        p1_marker = filepath + ".p1done"
        if os.path.exists(p1_marker):
            try:
                run_id = int(open(p1_marker).read().strip())
                print(f"[p1] Already done (run #{run_id}), submitting to Phase 2...")
                self._submit_phase2(filepath, run_id)
                return
            except Exception as e:
                print(f"[p1] Resume failed: {e}, starting fresh")
                os.remove(p1_marker)

        try:
            result = process_recording(filepath, self.clips_dir, on_phase=on_phase)
            with self._processing_lock:
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

            self._update_processing_item(filepath, "phase1_done", run_id=run_id)
            try:
                with open(filepath + ".p1done", "w") as f:
                    f.write(str(run_id))
            except Exception as e:
                print(f"[p1] Failed to write .p1done marker: {e}")

            # Submit Phase 2 (gated by worker limit)
            self._submit_phase2(filepath, run_id)

        except Exception as e:
            self._update_processing_item(filepath, "error")
            print(f"[p1] Error: {e}")

    def _submit_phase2(self, filepath: str, run_id: int):
        """Submit a Phase 2 job if a slot is available, otherwise hold in waiting list."""
        with self._p2_active_lock:
            if self._p2_active < self._p2_max_workers:
                self._p2_active += 1
                self._update_processing_item(filepath, "analyzing_gameplay", run_id=run_id)
                self._p2_executor.submit(self._process_phase2, filepath, run_id)
                print(f"[p2] Submitted Phase 2 for run #{run_id} ({self._p2_active}/{self._p2_max_workers} active)")
            else:
                self._p2_waiting.append((filepath, run_id))
                self._update_processing_item(filepath, "queued", run_id=run_id)
                print(f"[p2] P2 full ({self._p2_active}/{self._p2_max_workers}), run #{run_id} waiting ({len(self._p2_waiting)} in queue)")

    def _p2_finished(self):
        """Called when a P2 job completes. Drains waiting list if slots available."""
        with self._p2_active_lock:
            self._p2_active = max(0, self._p2_active - 1)
            while self._p2_waiting and self._p2_active < self._p2_max_workers:
                filepath, run_id = self._p2_waiting.pop(0)
                self._p2_active += 1
                self._update_processing_item(filepath, "analyzing_gameplay", run_id=run_id)
                self._p2_executor.submit(self._process_phase2, filepath, run_id)
                print(f"[p2] Slot freed, submitting run #{run_id} from waiting list ({self._p2_active}/{self._p2_max_workers} active)")

    def _process_phase2(self, filepath: str, run_id: int):
        """Phase 2: video narrative + clip cutting. Runs in P2 pool.

        On success: auto-save → remove from queue (item vanishes).
        On failure: set error status → RETRY available.
        """
        from .video_processor import process_recording_phase2

        def on_phase(phase, detail=None):
            self._update_processing_item(filepath, phase, detail=detail)

        try:
            print(f"[p2] Starting Phase 2 for run #{run_id}...")
            p2_result = process_recording_phase2(
                filepath, self.clips_dir, run_id, on_phase=on_phase
            )

            # Check if narrative actually made it to the DB
            p2_success = False
            if p2_result and p2_result.get("status") == "success":
                p2_success = True
            else:
                # Double-check DB in case CLI succeeded but result parsing failed
                try:
                    from .database import SessionLocal
                    from .models import Run
                    db = SessionLocal()
                    run = db.query(Run).filter(Run.id == run_id).first()
                    p2_success = run is not None and run.summary is not None
                    db.close()
                except Exception:
                    pass

            if p2_success:
                print(f"[p2] Done: run #{run_id}, {len(p2_result.get('clips', []) if p2_result else [])} clips")
                # Auto-save: move recording, generate assets, clean up markers
                self._auto_save_recording(filepath, run_id)
                # Remove from processing queue — item vanishes
                self.remove_processing_item(os.path.basename(filepath))
            else:
                print(f"[p2] Failed: {p2_result}")
                self._update_processing_item(filepath, "error", run_id=run_id, p2_failed=True)
                try:
                    log_path = os.path.join(self.recordings_dir, "phase2_errors.log")
                    with open(log_path, "a") as f:
                        f.write(f"\n--- {datetime.now().isoformat()} | run #{run_id} | {os.path.basename(filepath)} ---\n")
                        f.write(f"Result: {p2_result}\n")
                except Exception:
                    pass

        except Exception as e:
            self._update_processing_item(filepath, "error", run_id=run_id)
            print(f"[p2] Error: {e}")
        finally:
            self._p2_finished()

    # -- Resume + helpers ----------------------------------------------

    def _resume_unprocessed(self):
        """Scan recordings directory for unprocessed .mp4 files."""
        try:
            mp4_files = [
                f for f in os.listdir(self.recordings_dir)
                if f.endswith(".mp4") and f.startswith("run_")
                and not f.endswith("_thumb.jpg")
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

                # Check marker files for previous progress
                p1_marker = filepath + ".p1done"

                if os.path.exists(p1_marker):
                    try:
                        run_id = int(open(p1_marker).read().strip())
                    except Exception:
                        run_id = None

                    # Check DB: is this run fully processed (has summary)?
                    fully_done = False
                    if run_id:
                        try:
                            from .database import SessionLocal
                            from .models import Run
                            db = SessionLocal()
                            run = db.query(Run).filter(Run.id == run_id).first()
                            fully_done = run is not None and run.summary is not None
                            db.close()
                        except Exception:
                            pass

                    if fully_done:
                        # Fully processed — just auto-save and we're done
                        print(f"[resume] Run #{run_id} fully processed — auto-saving")
                        self._auto_save_recording(filepath, run_id)
                        # Don't add to queue — it's done
                    else:
                        # Phase 1 done, phase 2 needed
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
                        self._submit_phase2(filepath, run_id)
                        print(f"[resume] Run #{run_id} — resuming Phase 2")
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

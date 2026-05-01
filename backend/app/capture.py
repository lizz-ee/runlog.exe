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

        # Auto-run flags — can be paused via SYS.CONFIG
        self._auto_p1: bool = True   # submit to P1 pool automatically
        self._auto_p2: bool = True   # submit to P2 pool automatically after P1
        self._p2_held: list[tuple[str, int]] = []  # items held when auto_p2 is off
        self._dismissed_files: set[str] = set()    # filenames dismissed from queue
        # Pre-load dismissed markers from clips dirs so they survive reboots
        try:
            for entry in os.listdir(self.clips_dir):
                run_dir = os.path.join(self.clips_dir, entry)
                if os.path.isdir(run_dir):
                    for f in os.listdir(run_dir):
                        if f.endswith(".mp4.dismissed"):
                            self._dismissed_files.add(f.replace(".dismissed", ""))
        except Exception:
            pass

    # -- Public API ----------------------------------------------------

    def start(self) -> dict:
        """Start detection and processing."""
        if self._running:
            return self.get_status()

        self._running = True
        print("[capture] Starting AutoCapture...")

        # Set Python process to below normal priority — detection is fast (winocr ~16ms),
        # so we don't need to compete with the game for CPU scheduling.
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetCurrentProcess()
            kernel32.SetPriorityClass(handle, 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS
            print("[capture] Python process priority: BELOW_NORMAL")
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
        self._auto_p1 = get_config_value("auto_p1") if get_config_value("auto_p1") is not None else True
        self._auto_p2 = get_config_value("auto_p2") if get_config_value("auto_p2") is not None else True
        print(f"[capture] Processing pools: P1={p1_workers} workers, P2={p2_workers} workers")
        print(f"[capture] Auto-run: P1={self._auto_p1}, P2={self._auto_p2}")
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
            "capture_resolution": f"{self._recorder.width}x{self._recorder.height}" if self._recorder.width else None,
            "has_frame": self._latest_frame is not None,
            "window_found": self._recorder.window_name is not None,
            "last_detection": self._last_detection,
            "detection_count": 0,
            "last_result": self._last_process_result,  # protected by _processing_lock at write site
            "auto_p1": self._auto_p1,
            "auto_p2": self._auto_p2,
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
        'postgame': 45,   # Stats screen should appear quickly after RUN_COMPLETE
    }

    def _ocr_loop(self):
        """OCR state machine — one region at a time.

        Always consumes Rust-side OCR frames via the relay. In menus the Rust
        recorder pushes at ~2fps; during recording it uses double-buffered
        staging textures (~3s cadence) so there are no GPU pipeline stalls.
        """
        last_seq = -1
        self._scan_state = 'lobby'  # lobby | deploy | endgame | postgame
        self._state_changed_at = time.time()
        deploy_cycle = 0
        endgame_cycle = 0

        while self._running:
            # ---- Acquire frame ------------------------------------------------
            # frame_img: PIL.Image used for OCR (no encode roundtrip)
            # frame_bytes: JPEG bytes, kept as None until a save actually needs them
            frame_img: Image.Image | None = None
            frame_bytes: bytes | None = None
            with self._frame_lock:
                frame_bytes = self._latest_frame
                seq = self._frame_seq
            if frame_bytes is None or seq == last_seq:
                time.sleep(0.1)
                continue
            last_seq = seq
            try:
                frame_img = Image.open(io.BytesIO(frame_bytes))
                frame_img.load()  # force decode now so downstream ops are cheap
            except Exception as e:
                print(f"[capture] frame decode failed: {e}")
                time.sleep(0.1)
                continue

            # ---- State timeout ------------------------------------------------
            timeout = self._STATE_TIMEOUTS.get(self._scan_state)
            if timeout and (time.time() - self._state_changed_at) > timeout:
                old_state = self._scan_state
                self._scan_state = 'lobby'
                self._state_changed_at = time.time()
                print(f"[capture] State timeout: stuck in '{old_state}' for >{timeout}s, falling back to lobby")
                if self._recording and old_state in ('endgame', 'postgame'):
                    print(f"[capture] Stopping orphaned recording due to timeout")
                    self._stop_recording()
                    continue

            # ---- Deploy cancel check (every 5th cycle) ------------------------
            if self._scan_state == 'deploy':
                deploy_cycle += 1
                if deploy_cycle % 5 == 0:
                    lobby_result = detect_game_state(frame_img, scan_mode='lobby')
                    if lobby_result and lobby_result['type'] in ('prepare', 'select_zone', 'ready_up'):
                        print(f"[capture] Lobby re-detected ({lobby_result['type']}) while in deploy — returning to lobby state")
                        self._scan_state = 'lobby'
                        self._state_changed_at = time.time()
                        deploy_cycle = 0
                        continue
            else:
                deploy_cycle = 0

            # ---- Endgame escape check (every 5th cycle) -----------------------
            # If RUN_COMPLETE was never detected and the player is back in lobby,
            # the state machine would be stuck in 'endgame' for 30 minutes.
            # Check the lobby region periodically as an escape hatch.
            if self._scan_state == 'endgame':
                endgame_cycle += 1
                if endgame_cycle % 5 == 0:
                    lobby_result = detect_game_state(frame_img, scan_mode='lobby')
                    if lobby_result and lobby_result['type'] in ('prepare', 'select_zone', 'ready_up'):
                        print(f"[capture] Lobby re-detected ({lobby_result['type']}) while in endgame — missed RUN_COMPLETE, stopping recording")
                        self._scan_state = 'lobby'
                        self._state_changed_at = time.time()
                        endgame_cycle = 0
                        if self._recording:
                            self._stop_recording()
                        continue
            else:
                endgame_cycle = 0

            # ---- OCR ---------------------------------------------------------
            result = detect_game_state(frame_img, scan_mode=self._scan_state)
            if self._running:
                self._handle_detection(result, frame_img, frame_bytes)

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

    def _handle_detection(self, result: dict | None, frame_img: "Image.Image | None", frame_bytes: bytes | None):
        """Process OCR detection result — act on first match, no debounce.

        frame_img: PIL image from the OCR cycle (always present on detection).
        frame_bytes: JPEG bytes if already available (menu path from Rust);
                     None during recording — encoded lazily below only if a save fires.
        """
        det_type = result['type'] if result else None

        if not det_type:
            return

        # Lazy-encode JPEG bytes only when a save actually fires (avoids the
        # ~10ms encode on every OCR cycle during recording when no hit occurs).
        SAVE_TYPES = {'ready_up', 'run', 'deploying', 'deploy', 'endgame', 'exfiltrated', 'eliminated'}
        frame_jpeg: bytes | None = frame_bytes
        if det_type in SAVE_TYPES and frame_jpeg is None and frame_img is not None:
            try:
                buf = io.BytesIO()
                frame_img.save(buf, format="JPEG", quality=75)
                frame_jpeg = buf.getvalue()
            except Exception as e:
                print(f"[capture] Lazy JPEG encode failed: {e}")
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

        # Stable lobby states while recording mean the run has ended. Stop on
        # all of them so a missed postgame screen cannot leave capture running.
        if self._recording and det_type in ('prepare', 'select_zone', 'ready_up'):
            print(f"[capture] Detected {det_type.upper()} while recording -- stopping recording")
            self._stop_recording()
            return

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
                screenshots_dir = os.path.join(os.path.dirname(self._recording_path), "screenshots")
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
            self._recorder.set_ocr_fast(True)
            print(f"[capture] RUN_COMPLETE at {elapsed:.1f}s into recording")

            if self._recording_path:
                screenshots_dir = os.path.join(os.path.dirname(self._recording_path), "screenshots")
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
                screenshots_dir = os.path.join(os.path.dirname(self._recording_path), "screenshots")
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
        bitrate_mbps = get_config_value("bitrate") or 30
        fps = get_config_value("fps") or 60
        bitrate = int(bitrate_mbps) * 1_000_000

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_tag = f"run_{timestamp}"
        filename = f"{run_tag}.mp4"
        # Record directly into the run's clips folder — no move needed later
        run_folder = os.path.join(self.clips_dir, run_tag)
        os.makedirs(os.path.join(run_folder, "screenshots"), exist_ok=True)
        path = os.path.join(run_folder, filename)

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

        # Release any P2 jobs that were held while this match was recording.
        # Only drain when auto_p2 is on — if it's off, the user has explicitly
        # chosen to hold them and we respect that.
        if self._auto_p2:
            with self._p2_active_lock:
                held = self._p2_held[:]
                self._p2_held.clear()
            for held_filepath, held_run_id in held:
                print(f"[p2] Recording stopped — releasing held run #{held_run_id}")
                self._submit_phase2(held_filepath, held_run_id)

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
        run_dir = os.path.dirname(filepath)  # clips/run_XXX/

        def _gen_thumb():
            thumb_name = filename.replace(".mp4", "_thumb.jpg")
            thumb_path = os.path.join(run_dir, thumb_name)
            if not (os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 5000):
                endgame_jpg = os.path.join(run_dir, "screenshots", "endgame.jpg")
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

    def set_auto_phase(self, phase: int, enabled: bool):
        """Enable or disable auto-run for Phase 1 or Phase 2. Saves to config."""
        from .api.settings_api import _load_settings, _save_settings
        if phase == 1:
            self._auto_p1 = enabled
            key = "auto_p1"
        else:
            self._auto_p2 = enabled
            key = "auto_p2"
        saved = _load_settings()
        saved[key] = enabled
        _save_settings(saved)
        print(f"[capture] Auto P{phase} set to {enabled}")
        # When re-enabling P2, drain held items
        if phase == 2 and enabled:
            with self._p2_active_lock:
                held = self._p2_held[:]
                self._p2_held.clear()
            for filepath, run_id in held:
                self._submit_phase2(filepath, run_id)
                print(f"[capture] Released held P2 run #{run_id}")

    def dismiss_item(self, filename: str):
        """Remove an item from the processing queue entirely without processing it."""
        # Mark for dispatcher to skip if still in _process_queue
        self._dismissed_files.add(filename)
        # Remove from P2 waiting and held lists
        with self._p2_active_lock:
            self._p2_waiting = [(f, r) for f, r in self._p2_waiting if os.path.basename(f) != filename]
            self._p2_held = [(f, r) for f, r in self._p2_held if os.path.basename(f) != filename]
        # Write persistent .dismissed marker next to the recording
        run_tag = filename.replace(".mp4", "")
        run_dir = os.path.join(self.clips_dir, run_tag)
        if os.path.isdir(run_dir):
            try:
                open(os.path.join(run_dir, filename + ".dismissed"), "w").close()
            except Exception:
                pass
            # Clean up marker files so the recording isn't re-queued
            for ext in ('.p1done', '.encoded', '.endgame', '.session'):
                marker_path = os.path.join(run_dir, filename + ext)
                if os.path.exists(marker_path):
                    try:
                        os.remove(marker_path)
                    except Exception:
                        pass
        # Remove from UI
        self.remove_processing_item(filename)
        print(f"[capture] Dismissed: {filename}")

    def dismiss_all_failed(self):
        """Remove all error-status items from the processing queue."""
        with self._processing_lock:
            failed = [i["file"] for i in self._processing_items if i["status"] == "error"]
        for filename in failed:
            self.dismiss_item(filename)
        print(f"[capture] Dismissed {len(failed)} failed item(s)")

    def _generate_recording_assets(self, filepath: str):
        """Generate thumbnail + sprite sheet for a full-run recording.

        Idempotent: each artifact is skipped if it already exists. Safe to call
        as soon as the .mp4 is closed on disk — we run this at Phase 1 completion
        so the FULL RUN pill in the UI has a thumb + scrubbable sprite immediately,
        without waiting for Phase 2.
        """
        import shutil
        if not os.path.exists(filepath):
            return

        run_dir = os.path.dirname(filepath)
        try:
            probe = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-show_entries',
                 'format=duration', '-of', 'csv=p=0', filepath],
                capture_output=True, text=True, timeout=10
            )
            duration = float(probe.stdout.strip()) if probe.stdout.strip() else 300

            keep_thumb = filepath.replace(".mp4", "_thumb.jpg")
            if not os.path.exists(keep_thumb):
                endgame_jpg = os.path.join(run_dir, "screenshots", "endgame.jpg")
                if os.path.exists(endgame_jpg):
                    shutil.copy2(endgame_jpg, keep_thumb)
                else:
                    mid = duration * 0.5
                    subprocess.run(
                        ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                         '-ss', str(mid), '-i', filepath,
                         '-vframes', '1', '-vf', 'scale=384:-1',
                         '-q:v', '5', keep_thumb],
                        capture_output=True, timeout=30,
                    )

            sprite_path = filepath.replace(".mp4", "_sprite.jpg")
            if not os.path.exists(sprite_path):
                from .video_processor import _generate_sprite_sheet
                _generate_sprite_sheet(filepath, duration)
        except Exception as e:
            print(f"[assets] Generation failed for {os.path.basename(filepath)}: {e}")

    def _auto_save_recording(self, filepath: str, run_id: int | None):
        """Finalize recording after Phase 2. Assets were already generated at
        Phase 1 completion — this just regenerates if missing and cleans markers."""
        filename = os.path.basename(filepath)

        if not os.path.exists(filepath):
            print(f"[auto-save] Recording not found: {filepath}")
            return

        # Regenerate any missing assets (no-op if P1 already produced them)
        self._generate_recording_assets(filepath)

        # Clean up marker files
        for ext in ('.p1done', '.encoded', '.endgame', '.session'):
            marker = filepath + ext
            if os.path.exists(marker):
                os.remove(marker)

        print(f"[auto-save] Finalized: {filepath}")

    def _resolve_filepath(self, filename: str) -> str:
        """Resolve a recording filename to its full path in clips."""
        run_tag = filename.replace(".mp4", "")
        return os.path.join(self.clips_dir, run_tag, filename)

    def reset_processing_item(self, filename: str):
        """Reset a failed processing item to queued and re-queue it."""
        filepath = self._resolve_filepath(filename)
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
        filepath = self._resolve_filepath(filename)
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
            filename = os.path.basename(filepath)
            # Skip dismissed items
            if filename in self._dismissed_files:
                self._dismissed_files.discard(filename)
                self._process_queue.task_done()
                continue
            # Hold if auto_p1 is disabled — put back and wait
            if not self._auto_p1:
                self._process_queue.put(filepath)
                self._process_queue.task_done()
                time.sleep(1.0)
                continue
            # Hold while a new match is being recorded — Phase 1 decodes 4K
            # video + JPEG-encodes ~120s of frames, which eats CPU headroom the
            # game wants. Defer until recording stops; stats are unaffected.
            if self._recording:
                self._process_queue.put(filepath)
                self._process_queue.task_done()
                time.sleep(1.0)
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

            # Update recording_path in DB (already in clips folder)
            if run_id:
                try:
                    from .database import SessionLocal
                    from .models import Run
                    db = SessionLocal()
                    run = db.query(Run).filter(Run.id == run_id).first()
                    if run:
                        run.recording_path = filepath
                        db.commit()
                    db.close()
                except Exception as e:
                    print(f"[p1] DB recording_path update failed: {e}")

            # Generate thumbnail + sprite sheet now — the FULL RUN pill needs
            # these, and there's no reason to wait for Phase 2 to show them.
            self._generate_recording_assets(filepath)

            # Invalidate clips cache so the new recording shows up immediately
            from .api.capture_api import invalidate_clips_cache
            invalidate_clips_cache()

            # Submit Phase 2 (gated by worker limit)
            self._submit_phase2(filepath, run_id)

        except Exception as e:
            self._update_processing_item(filepath, "error")
            print(f"[p1] Error: {e}")

    def _submit_phase2(self, filepath: str, run_id: int):
        """Submit a Phase 2 job if a slot is available, otherwise hold in waiting list."""
        # Hold at phase1_done if auto_p2 is disabled
        if not self._auto_p2:
            with self._p2_active_lock:
                self._p2_held.append((filepath, run_id))
            # Surface the held state in the UI so the user knows it's waiting.
            self._update_processing_item(filepath, "phase1_done", run_id=run_id)
            print(f"[p2] Auto P2 disabled — holding run #{run_id}")
            return
        # Hold while recording — P2 does ffmpeg clip extraction + sprite gen
        # which contend with the game. _stop_recording() drains held items.
        if self._recording:
            with self._p2_active_lock:
                self._p2_held.append((filepath, run_id))
            self._update_processing_item(filepath, "phase1_done", run_id=run_id)
            print(f"[p2] Recording in progress — holding run #{run_id}")
            return
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
                    log_path = os.path.join(self.clips_dir, "phase2_errors.log")
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
        """Scan clips directory for unprocessed run recordings."""
        try:
            # Scan clips/run_*/run_*.mp4 for recordings
            mp4_files = []
            for entry in os.listdir(self.clips_dir):
                if not entry.startswith("run_"):
                    continue
                run_dir = os.path.join(self.clips_dir, entry)
                if not os.path.isdir(run_dir):
                    continue
                mp4 = os.path.join(run_dir, entry + ".mp4")
                if os.path.exists(mp4):
                    mp4_files.append((entry + ".mp4", mp4))

            if not mp4_files:
                return

            existing_files = set()
            with self._processing_lock:
                existing_files = {item["file"] for item in self._processing_items}

            resumed = 0
            for filename, filepath in sorted(mp4_files):
                if filename in existing_files:
                    continue

                # Skip permanently dismissed recordings
                if os.path.exists(filepath + ".dismissed"):
                    continue

                file_size = os.path.getsize(filepath)
                if file_size < 1024 * 1024:
                    continue

                # Check if this run is *fully* processed (Phase 2 summary written).
                # Note: Phase 1 also writes a Run row (with stats) but leaves summary
                # NULL — those need to fall through to the .p1done resume branch so
                # Phase 2 picks them up. Only skip when summary is present.
                try:
                    from .database import SessionLocal
                    from .models import Run
                    db = SessionLocal()
                    existing_run = db.query(Run).filter(Run.recording_path == filepath).first()
                    if existing_run is None:
                        # Also check by date match (older runs may have a different recording_path)
                        run_tag = filename.replace(".mp4", "")  # run_YYYYMMDD_HHMMSS
                        ts_str = run_tag.replace("run_", "")    # YYYYMMDD_HHMMSS
                        try:
                            from datetime import datetime
                            run_date = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
                            existing_run = db.query(Run).filter(Run.date == run_date).first()
                        except Exception:
                            pass
                    db.close()
                    if existing_run is not None and existing_run.summary is not None:
                        continue  # Fully processed — skip
                except Exception:
                    pass

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
                        # Generate any missing assets (thumbnail, sprite) — these
                        # are cheap, idempotent, and runs finalized under older
                        # code may not have them yet.
                        self._generate_recording_assets(filepath)
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

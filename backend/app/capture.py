"""
AutoCapture -- Automatic screen recording triggered by Marathon game state.

Architecture:
  Rust binary (runlog-recorder.exe) handles:
    - WGC window capture (Marathon only, privacy safe)
    - HEVC/H.264 encoding via MediaFoundation HW encoder (zero-copy GPU, 60fps 4K)
    - OCR region crops shipped as small base64 JPEGs via async double-buffered
      staging textures — the game's GPU pipeline is never stalled
    - Full preview frames at a slow cadence + on demand (frame_now)

  Python handles:
    - OCR game state detection (winocr) on the pre-cropped regions
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

from . import perf
from . import cli_registry
from .detection.ocr import (
    detect_crew_size,
    detect_game_state,
    detect_kill_feed,
    detect_map_variant,
)
from .rust_recorder import RustRecorder
from .audio_sidecar import AudioSidecarRecorder

MAX_P1_WORKERS = 4   # Phase 1 (fast stats extraction) — unconstrained
MAX_P2_WORKERS = 1   # Phase 2 (video narrative + clips) — heavy, capped


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
        self._recording_lock = threading.RLock()
        self._capture_health_error: str | None = None
        self._low_submit_fps_since: float = 0.0
        self._recording_failure_latched: str | None = None
        self._capture_mode: str = "none"

        # Rust recorder
        self._recorder = RustRecorder()
        self._audio = AudioSidecarRecorder()

        # Threads
        self._ocr_thread: threading.Thread | None = None
        self._dispatcher_thread: threading.Thread | None = None
        self._recorder_watchdog_thread: threading.Thread | None = None
        self._recorder_restart_lock = threading.RLock()
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
        # Kill feed dedup: normalized line -> seconds-into-recording last seen
        self._recent_kill_feed: dict[str, float] = {}
        self._selected_crew_size: int | None = None
        self._selected_crew_size_at: float = 0

        # Processing queue + executors
        self._process_queue: queue.Queue = queue.Queue()
        self._last_process_result: dict | None = None
        self._processing_items: list[dict] = []
        self._processing_lock = threading.Lock()
        self._asset_lock = threading.Lock()
        self._asset_generating: set[str] = set()
        self.resumed_count: int = 0
        self._p1_executor: ThreadPoolExecutor | None = None
        self._p2_executor: ThreadPoolExecutor | None = None

        # P2 gating — track active count, hold overflow in waiting list
        self._p2_active: int = 0
        self._p2_active_lock = threading.Lock()
        self._p2_waiting: list[tuple[str, int]] = []  # [(filepath, run_id), ...]
        self._p2_max_workers: int = MAX_P2_WORKERS

        # Processing mode — "alpha" (local), "hybrid" (local + Claude fallback),
        # "claude" (network only). Used by the game-impact gate: claude-mode P1
        # uploads, so it must be held while the game is open like P2.
        self._processor_mode: str = "alpha"

        # Auto-run flags — can be paused via SYS.CONFIG
        self._auto_p1: bool = True   # submit to P1 pool automatically
        self._auto_p2: bool = True   # submit to P2 pool automatically after P1

        # Set once at start if recordings live on a spinning HDD (seek-thrash
        # stutter risk when shared with the game). Surfaced in status for the UI.
        self._storage_warning: str | None = None
        self._processing_guard_mode: str = "recording"
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

        # Recorder lifetime belongs to the backend. The Rust WGC process exits
        # when Marathon closes; the watchdog re-arms its low-cost window wait
        # without relying on Electron or the React dashboard.
        self._recorder_watchdog_thread = threading.Thread(
            target=self._recorder_watchdog_loop,
            daemon=True,
            name="recorder-watchdog",
        )
        self._recorder_watchdog_thread.start()

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
        self._processor_mode = get_config_value("processor_mode") or "alpha"
        guard_mode = get_config_value("processing_guard_mode") or "recording"
        self._processing_guard_mode = guard_mode if guard_mode in ("recording", "game", "off") else "recording"
        print(f"[capture] Processing pools: P1={p1_workers} workers, P2={p2_workers} workers")
        print(f"[capture] Auto-run: P1={self._auto_p1}, P2={self._auto_p2}")
        print(f"[capture] Processing guard: {self._processing_guard_mode}")
        # initializer pins every worker thread to EcoQoS + below-normal so the
        # heavy torch/OCR/cv2 work runs on E-cores and yields to the game.
        self._p1_executor = ThreadPoolExecutor(
            max_workers=p1_workers, thread_name_prefix="p1-processor",
            initializer=perf.eco_qos_init,
        )
        self._p2_executor = ThreadPoolExecutor(
            max_workers=p2_workers, thread_name_prefix="p2-processor",
            initializer=perf.eco_qos_init,
        )
        self._dispatcher_thread = threading.Thread(
            target=self._dispatcher_loop, daemon=True, name="dispatcher"
        )
        self._dispatcher_thread.start()

        # One-time storage-drive check — warn if recordings live on a spinning HDD
        # (seek-thrash stutter risk if it's the same drive the game streams from).
        try:
            if perf.storage_incurs_seek_penalty(self.clips_dir):
                self._storage_warning = (
                    "Recordings are on a spinning HDD — if it's the same drive the "
                    "game streams from, expect occasional stutter. Move recordings to "
                    "an SSD or a second drive in SYS.CONFIG > STOR.CONFIG."
                )
                print(f"[capture] STORAGE WARNING: {self._storage_warning}")
        except Exception:
            pass

        # Auto-resume unprocessed recordings (after executors are ready)
        self._resume_unprocessed()

        self._broadcast_status()
        return self.get_status()

    def stop(self) -> dict:
        """Stop everything."""
        self._running = False

        if self._recording:
            self._stop_recording()

        with self._recorder_restart_lock:
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

        for thread in [self._ocr_thread, self._dispatcher_thread, self._recorder_watchdog_thread]:
            if thread and thread.is_alive():
                thread.join(timeout=5)

        print("[capture] AutoCapture stopped.")
        self._broadcast_status()
        return self.get_status()

    def get_status(self) -> dict:
        recording_seconds = 0
        if self._recording and self._recording_start:
            recording_seconds = time.time() - self._recording_start
        progress_age = None
        if self._recorder.recording_last_progress_at:
            progress_age = max(
                0.0, time.monotonic() - self._recorder.recording_last_progress_at
            )
        if not self._recording:
            recording_health = "idle"
        elif self._recorder.recording_state == "starting":
            recording_health = "starting"
        elif progress_age is not None and progress_age > 8:
            recording_health = "stalled"
        elif (
            recording_seconds > 4
            and self._recorder.recording_submitted_fps_recent < 10
        ):
            recording_health = "degraded"
        else:
            recording_health = "healthy"

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
            "recording_state": self._recorder.recording_state,
            "recording_backend": self._recorder.recording_backend,
            "recording_health": recording_health,
            "recording_capture_fps": round(self._recorder.recording_capture_fps, 1),
            "recording_submitted_fps": round(self._recorder.recording_submitted_fps, 1),
            "recording_capture_fps_recent": round(
                self._recorder.recording_capture_fps_recent, 1
            ),
            "recording_submitted_fps_recent": round(
                self._recorder.recording_submitted_fps_recent, 1
            ),
            "recording_captured_frames": self._recorder.recording_captured_frames,
            "recording_submitted_frames": self._recorder.recording_submitted_frames,
            "recording_dropped_frames": self._recorder.recording_dropped_frames,
            "recording_progress_age": round(progress_age, 1) if progress_age is not None else None,
            "queue_size": self._process_queue.qsize(),
            "processing_phase": processing_phase,
            "processing_items": items,
            "status_counts": status_counts,
            "resumed_count": self.resumed_count,
            "capture_mode": self._capture_mode,
            "capture_error": self._capture_health_error or self._recorder.last_error,
            "audio_capture_active": self._audio.active,
            "audio_capture_path": self._audio.path,
            "audio_capture_error": self._audio.error,
            "capture_resolution": f"{self._recorder.width}x{self._recorder.height}" if self._recorder.width else None,
            "has_frame": self._latest_frame is not None,
            "window_found": self._recorder.window_name is not None,
            "last_detection": self._last_detection,
            "detection_count": 0,
            "last_result": self._last_process_result,  # protected by _processing_lock at write site
            "auto_p1": self._auto_p1,
            "auto_p2": self._auto_p2,
            "processing_guard_mode": self._processing_guard_mode,
            "processing_guard_active": self._processing_gate_active(),
            "pause_processing_while_game_running": self._processing_guard_mode == "game",
            "processing_paused_for_game": self._heavy_processing_blocked_by_game(),
            "processing_paused_for_recording": self._processing_guard_mode != "off" and self._recording,
            "storage_warning": self._storage_warning,
            "selected_crew_size": self._selected_crew_size,
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

    def _recorder_watchdog_loop(self):
        """Keep game discovery and run finalization independent of Electron."""
        while self._running:
            if self._recording and self._recorder.recording_state == "failed":
                reason = self._recorder.last_error or "Recording backend exited unexpectedly"
                print(f"[capture] HEALTH FAULT: {reason}")
                self._capture_health_error = reason
                self._stop_recording(failure_reason=reason)
                continue

            if (
                self._recording
                and self._recorder.recording_state == "recording"
                and self._recording_start
            ):
                elapsed = time.time() - self._recording_start
                last_progress = self._recorder.recording_last_progress_at
                progress_age = (
                    time.monotonic() - last_progress if last_progress else elapsed
                )
                recent_submit_fps = self._recorder.recording_submitted_fps_recent

                # A healthy 60fps capture reports once per second. Ten seconds
                # without a callback is a hard stall, not normal jitter.
                if elapsed > 12 and progress_age > 10:
                    reason = (
                        f"Capture callback stalled for {progress_age:.1f}s "
                        f"({self._recorder.recording_submitted_frames} frames submitted)"
                    )
                    print(f"[capture] HEALTH FAULT: {reason}")
                    self._capture_health_error = reason
                    self._stop_recording(failure_reason=reason)
                    continue

                # Sustained near-zero encoder throughput is equally unusable,
                # even if WGC callbacks themselves are still arriving.
                if elapsed > 15 and recent_submit_fps < 5:
                    if not self._low_submit_fps_since:
                        self._low_submit_fps_since = time.monotonic()
                    elif time.monotonic() - self._low_submit_fps_since > 15:
                        reason = (
                            "Encoder throughput stayed below 5 real fps for 15s "
                            f"(current {recent_submit_fps:.1f}fps)"
                        )
                        print(f"[capture] HEALTH FAULT: {reason}")
                        self._capture_health_error = reason
                        self._stop_recording(failure_reason=reason)
                        continue
                else:
                    self._low_submit_fps_since = 0.0

            if self._recorder.available and not self._recorder.is_running:
                with self._recorder_restart_lock:
                    if not self._running or self._recorder.is_running:
                        continue

                    if self._recording:
                        print("[capture] Marathon window closed during a run -- finalizing recording")
                        self._stop_recording()

                    self._recorder.stop()
                    with self._frame_lock:
                        self._latest_frame = None
                    self._last_detection = None
                    self._scan_state = "lobby"
                    self._state_changed_at = time.time()

                    if self._running and self._recorder.start():
                        self._capture_mode = "wgc"
                        print("[capture] Recorder watchdog armed for the next Marathon window")
                    else:
                        self._capture_mode = "unavailable"
                    self._broadcast_status()

            time.sleep(2)

        print("[capture] Recorder watchdog stopped.")

    def _frame_relay(self):
        """Relay full preview frames from Rust recorder to our frame store."""
        perf.set_thread_eco_qos()
        last_seq = -1
        while self._running:
            frame, seq = self._recorder.wait_for_frame(last_seq, timeout=1.0)
            if frame and seq != last_seq:
                last_seq = seq
                with self._frame_lock:
                    first_frame = self._latest_frame is None
                    self._latest_frame = frame
                    self._frame_seq += 1
                # Frame availability changes DETECT.EXE from INITIALIZING to a
                # live preview. Push that one-time state transition instead of
                # waiting for an unrelated detection event.
                if first_frame:
                    self._broadcast_status()
        print("[capture] Frame relay stopped.")

    def _get_fresh_frame(self, timeout: float = 2.0) -> bytes | None:
        """Request an on-demand full frame from the recorder and wait for it.

        Used when a detection hit needs a screenshot — full preview frames
        normally arrive on a slow cadence, so we ask for a fresh one instead
        of saving a stale frame. Falls back to the latest cached frame on
        timeout.
        """
        with self._frame_lock:
            start_seq = self._frame_seq
        self._recorder.request_full_frame()
        deadline = time.time() + timeout
        while time.time() < deadline and self._running:
            with self._frame_lock:
                if self._frame_seq != start_seq:
                    return self._latest_frame
            time.sleep(0.05)
        return self.get_latest_frame_jpeg()

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

        Consumes pre-cropped scan regions from the Rust recorder (lobby/deploy/
        endgame, ~18% of the frame's pixels). All readback on the Rust side is
        async double-buffered staging, so detection never stalls the game's GPU
        pipeline — in menus or in game. Full frames only ship on a slow cadence
        for the UI and are requested on demand when a save needs one.
        """
        perf.set_thread_eco_qos()  # live detection rides E-cores, yields to the game
        last_seq = -1
        self._scan_state = 'lobby'  # lobby | deploy | endgame | postgame
        self._state_changed_at = time.time()
        deploy_cycle = 0
        endgame_cycle = 0
        lobby_deploy_probe_cycle = 0
        crew_probe_cycle = 0

        while self._running:
            # ---- Acquire region crops -----------------------------------------
            regions_jpeg, seq = self._recorder.wait_for_regions(last_seq, timeout=1.0)
            if not regions_jpeg or seq == last_seq:
                continue
            last_seq = seq
            regions: dict[str, Image.Image] = {}
            try:
                for name, data in regions_jpeg.items():
                    img = Image.open(io.BytesIO(data))
                    img.load()  # force decode now so downstream ops are cheap
                    regions[name] = img
            except Exception as e:
                print(f"[capture] region decode failed: {e}")
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
                    lobby_result = detect_game_state(regions, scan_mode='lobby')
                    if lobby_result and lobby_result['type'] in (
                        'prepare', 'select_zone', 'ready_up', 'searching',
                    ):
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
                    lobby_result = detect_game_state(regions, scan_mode='lobby')
                    if lobby_result and lobby_result['type'] in (
                        'prepare', 'select_zone', 'ready_up', 'searching',
                    ):
                        print(f"[capture] Lobby re-detected ({lobby_result['type']}) while in endgame — missed RUN_COMPLETE, stopping recording")
                        self._scan_state = 'lobby'
                        self._state_changed_at = time.time()
                        endgame_cycle = 0
                        if self._recording:
                            self._stop_recording()
                        continue
            else:
                endgame_cycle = 0

            # ---- Kill feed scan (during the run only) --------------------------
            # Logs combat timestamps to the .events sidecar so Phase 2 can
            # focus its frame extraction on confirmed fights. Hints only —
            # misses are harmless, and the scan is one ~16ms winocr call per
            # staged tick at below-normal priority.
            if self._recording and self._scan_state == 'endgame':
                self._scan_kill_feed(regions)

            # ---- OCR ---------------------------------------------------------
            # Read the collapsed SOLO/DUOS/TRIOS selector at a low idle cadence.
            # The dedicated crop is small, and this pass never runs in-match.
            if self._scan_state == 'lobby':
                crew_probe_cycle += 1
                if crew_probe_cycle % 3 == 0:
                    crew_size = detect_crew_size(regions.get('crew'))
                    if crew_size and crew_size != self._selected_crew_size:
                        self._selected_crew_size = crew_size
                        self._selected_crew_size_at = time.time()
                        print(f"[capture] Selected crew size: {crew_size}")
                        self._broadcast_status()
            else:
                crew_probe_cycle = 0

            result = detect_game_state(regions, scan_mode=self._scan_state)

            # Marathon's lobby wording changes between builds and can omit the
            # literal SEARCHING state entirely. If the lobby crop has no known
            # signal, probe the deployment region at a low cadence so the map
            # title can still start capture. This adds one small OCR call every
            # ~3 seconds only while idle, and avoids missing a whole run.
            if self._scan_state == 'lobby':
                lobby_deploy_probe_cycle += 1
                if result is None and lobby_deploy_probe_cycle % 3 == 0:
                    result = detect_game_state(regions, scan_mode='deploy')
            else:
                lobby_deploy_probe_cycle = 0

            if self._running:
                self._handle_detection(result)

        print("[capture] OCR loop stopped.")

    def _scan_kill_feed(self, regions: "dict[str, Image.Image]"):
        """OCR the kill feed crop and append new eliminations to the .events
        sidecar (JSONL: {"t": seconds_into_recording, "text": line}). Phase 2
        uses these as confirmed combat timestamps for smart frame extraction."""
        if not self._recording_path:
            return
        try:
            lines = detect_kill_feed(regions.get('killfeed'))
            if not lines:
                return
            now = time.time() - self._recording_start
            new_events = []
            for line in lines:
                norm = ''.join(line.split()).upper()
                last_seen = self._recent_kill_feed.get(norm)
                if last_seen is not None and (now - last_seen) < 15:
                    continue  # same feed entry still on screen
                self._recent_kill_feed[norm] = now
                new_events.append({"t": round(now, 1), "text": line})
            if new_events:
                import json
                with open(self._recording_path + ".events", "a", encoding="utf-8") as f:
                    for event in new_events:
                        f.write(json.dumps(event) + "\n")
                print(f"[capture] Kill feed: {len(new_events)} event(s) at {now:.0f}s")
        except Exception as e:
            print(f"[capture] Kill feed scan failed: {e}")

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

    def _detect_buffered_map_variant(self) -> str | None:
        """Read the newest pre-deploy full frame's contract chip once."""
        candidates = []
        for phase_name in ('deploying', 'run', 'readyup'):
            path = os.path.join(self.recordings_dir, f"readyup_buf_{phase_name}.jpg")
            if os.path.exists(path):
                candidates.append(path)
        if not candidates:
            return None
        newest = max(candidates, key=os.path.getmtime)
        try:
            with Image.open(newest) as img:
                return detect_map_variant(img)
        except Exception as e:
            print(f"[capture] Buffered map variant probe failed: {e}")
            return None

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

    def _handle_detection(self, result: dict | None):
        """Process OCR detection result — act on first match, no debounce.

        Detection runs on region crops, so saves fetch a full frame on demand:
        the latest cached preview frame for static lobby screens (ready_up/
        run/deploying), or a fresh on-demand frame from the recorder for
        one-shot transitions (deploy/endgame/stats) where staleness matters.
        """
        det_type = result['type'] if result else None

        if not det_type:
            return

        # A failed encoder stays failed for the rest of that run. Otherwise
        # recurring in-run HUD detections create a start/fail/restart loop.
        # A confirmed lobby/deployment transition arms the next run.
        if (
            not self._recording
            and det_type in ("prepare", "select_zone", "ready_up")
        ):
            self._recording_failure_latched = None

        # --- State transitions (simple toggle between 3 OCR regions) ---
        prev_state = self._scan_state
        if det_type in ('searching', 'run', 'deploying'):
            self._scan_state = 'deploy'    # Matchmaking started → watch for map name
        elif det_type == 'deploy':
            self._scan_state = 'endgame'   # Map found → watch for RUN_COMPLETE
        elif det_type == 'in_run':
            self._scan_state = 'endgame'   # Late attach → record remainder of active run
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

        # --- LATE ATTACH: begin recording if RunLog launched mid-match -------
        if det_type == 'in_run' and not self._recording:
            if self._recording_failure_latched:
                print(
                    "[capture] Late-attach suppressed for this run after capture failure: "
                    f"{self._recording_failure_latched}"
                )
                return
            print("[capture] Active-run HUD detected after launch -- starting late-attach recording")
            self._start_recording()
            if self._recording_path:
                try:
                    from .main import get_or_create_session
                    with open(self._recording_path + ".session", "w") as f:
                        f.write(str(get_or_create_session()))
                    import json as _json
                    screenshots_dir = os.path.join(
                        os.path.dirname(self._recording_path),
                        "screenshots",
                    )
                    os.makedirs(screenshots_dir, exist_ok=True)
                    with open(os.path.join(screenshots_dir, "metadata.json"), "w") as f:
                        _json.dump({"late_attach": True}, f)
                except Exception as e:
                    print(f"[capture] Failed to write late-attach metadata: {e}")
            return

        # --- READY UP / RUN / DEPLOYING: one screenshot per phase ---
        # Static lobby screens — the latest cached preview frame (≤2s old) is fine.
        if det_type in ('ready_up', 'run', 'deploying'):
            frame_jpeg = self.get_latest_frame_jpeg()
            if frame_jpeg:
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
            map_variant = result.get('map_variant')
            if map_name.upper() == 'DIRE MARSH':
                # Prefer the explicit top-right contract chip captured during
                # ready-up. It is more reliable than assuming that a deploy
                # OCR miss of the word NIGHT means Day.
                map_variant = self._detect_buffered_map_variant() or map_variant
            is_ranked = result.get('is_ranked', False)
            variant_label = f" ({map_variant.upper()})" if map_variant else ""
            print(f"[capture] Detected deployment: {map_name}{variant_label}{' (RANKED)' if is_ranked else ''} -- starting recording")
            self._recording_failure_latched = None
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

                # Save authoritative deployment metadata for the processor.
                # Variant is a separate dimension: map_name remains
                # "Dire Marsh" so the parent map can aggregate both.
                metadata = {
                    "map_name": map_name.title(),
                    "is_ranked": bool(is_ranked),
                }
                if map_variant:
                    metadata["map_variant"] = map_variant
                if (
                    self._selected_crew_size in (1, 2, 3)
                    and time.time() - self._selected_crew_size_at < 1800
                ):
                    metadata["squad_size"] = self._selected_crew_size
                    metadata["crew_size"] = {
                        1: "Solo",
                        2: "Duo",
                        3: "Trio",
                    }[self._selected_crew_size]
                with open(os.path.join(screenshots_dir, "metadata.json"), "w") as f:
                    _json.dump(metadata, f)

                # Shot 1: fresh frame now (may catch contract screen — too early)
                frame_jpeg = self._get_fresh_frame()
                if frame_jpeg:
                    self._save_deploy_shot(screenshots_dir, "deploy_1", frame_jpeg)
                    print(f"[capture] Deploy shot 1/3 saved: {map_name}")

                # Shots 2 & 3: fresh on-demand frames, 2s apart (like stats)
                def _delayed_deploy_shots():
                    time.sleep(2.0)
                    frame2 = self._get_fresh_frame()
                    if frame2:
                        self._save_deploy_shot(screenshots_dir, "deploy_2", frame2)
                        print(f"[capture] Deploy shot 2/3 saved")
                    time.sleep(2.0)
                    frame3 = self._get_fresh_frame()
                    if frame3:
                        self._save_deploy_shot(screenshots_dir, "deploy_3", frame3)
                        print(f"[capture] Deploy shot 3/3 saved")

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

            # The banner is brief and the staged detection frame is a few
            # seconds old — grab a fresh full frame for the screenshot.
            frame_jpeg = self._get_fresh_frame()
            if self._recording_path and frame_jpeg:
                screenshots_dir = os.path.join(os.path.dirname(self._recording_path), "screenshots")
                os.makedirs(screenshots_dir, exist_ok=True)
                with open(os.path.join(screenshots_dir, "endgame.jpg"), "wb") as f:
                    f.write(frame_jpeg)
                print(f"[capture] Endgame screenshot saved")

                # Crop the damage widget (Neural Link Severed / death screen)
                try:
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

                # Shot 1: fresh frame now (banner screen)
                frame_jpeg = self._get_fresh_frame()
                if frame_jpeg:
                    self._save_stats_shot(screenshots_dir, "stats_1", frame_jpeg)
                    print(f"[capture] Stats shot 1/3 saved ({det_type})")

                # Shots 2 & 3: faster timing to catch stats before player clicks to PROGRESS
                def _delayed_stats_shots():
                    # Shot 2: wait ~1s for stats animation to complete
                    time.sleep(1.0)
                    frame2 = self._get_fresh_frame()
                    if frame2:
                        self._save_stats_shot(screenshots_dir, "stats_2", frame2)
                        print(f"[capture] Stats shot 2/3 saved")
                    # Shot 3: wait another ~1.5s
                    time.sleep(1.5)
                    frame3 = self._get_fresh_frame()
                    if frame3:
                        self._save_stats_shot(screenshots_dir, "stats_3", frame3)
                        print(f"[capture] Stats shot 3/3 saved")

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
        """Serialize start transitions across OCR, watchdog, and API threads."""
        with self._recording_lock:
            return self._start_recording_locked()

    def _start_recording_locked(self):
        """Start recording via Rust binary, using settings from config."""
        if self._recording_failure_latched:
            print(
                "[capture] Recording start suppressed until the next lobby/deploy cycle: "
                f"{self._recording_failure_latched}"
            )
            return
        if not self._recorder.is_running:
            print("[capture] Cannot record — Rust recorder not running")
            return

        # Load recording settings from config
        from .api.settings_api import get_config_value
        encoder = get_config_value("encoder") or "hevc"
        bitrate_mbps = get_config_value("bitrate") or 20
        fps = get_config_value("fps") or 30
        resolution = get_config_value("resolution") or "1440p"
        audio_enabled = get_config_value("audio_capture")
        if audio_enabled is None:
            audio_enabled = True
        bitrate = int(bitrate_mbps) * 1_000_000
        # Map resolution preset → target_height. Width is computed Rust-side
        # using the live capture aspect ratio so ultrawide windows stay correct.
        target_height = {"native": None, "1440p": 1440, "1080p": 1080, "720p": 720}.get(resolution)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_tag = f"run_{timestamp}"
        filename = f"{run_tag}.mp4"
        # Record directly into the run's clips folder — no move needed later
        run_folder = os.path.join(self.clips_dir, run_tag)
        os.makedirs(os.path.join(run_folder, "screenshots"), exist_ok=True)
        path = os.path.join(run_folder, filename)

        if self._recorder.start_recording(path, bitrate=bitrate, encoder=encoder, fps=fps, target_height=target_height):
            self._capture_health_error = None
            self._recording_failure_latched = None
            self._low_submit_fps_since = 0.0
            audio_path = path.replace(".mp4", "_audio.wav")
            if audio_enabled:
                self._audio.start(audio_path)
            else:
                self._audio.status.active = False
                self._audio.status.path = None
                self._audio.status.error = "disabled in settings"
            self._recording = True
            self._recording_start = time.time()
            self._recording_path = path
            self._recent_kill_feed = {}
            # A prior run's heavy ffmpeg/ffprobe could still be decoding from a
            # lobby gap. The gate blocks NEW heavy work during a match, but can't
            # stop in-flight work — drop those children to IDLE/EcoQoS so they
            # yield to the game (no suspend: a frozen child would trip the parent
            # subprocess.run timeout and fail the job).
            try:
                n = perf.background_inflight_decoders(os.getpid())
                if n:
                    print(f"[capture] Match started — dropped {n} in-flight ffmpeg/ffprobe to background")
            except Exception:
                pass
            # Kill any in-flight Claude CLI upload from a prior run — its bandwidth
            # contends with the live match's ping, and (unlike ffmpeg) a network
            # upload can't be deprioritized. The killed worker re-queues the run
            # (P1) or re-holds it (P2); both resume after the match.
            try:
                aborted = cli_registry.abort_all()
                if aborted:
                    print(f"[capture] Match started — aborted {aborted} in-flight CLI upload(s) for re-queue")
            except Exception:
                pass
            res_label = f"{resolution}" if target_height else "native"
            print(f"[capture] Recording to: {path} ({encoder.upper()}, {bitrate_mbps}Mbps, {fps}fps, {res_label})")
            if self._audio.active:
                print(f"[audio] Sidecar recording to: {audio_path}")
            elif not audio_enabled:
                print("[audio] Sidecar disabled in settings")
            self._broadcast_status()
        else:
            self._capture_health_error = (
                self._recorder.last_error or "Rust encoder did not acknowledge recording start"
            )
            self._recording_failure_latched = self._capture_health_error
            print(f"[capture] Recording failed to start: {self._capture_health_error}")
            self._broadcast_status()

    def _maybe_restart_recorder_for_fps(self):
        """Bounce the recorder if a setting change deferred a restart while
        recording was active. Safe to call only when self._recording is False."""
        if not self._running:
            return
        if not getattr(self._recorder, "fps_restart_pending", False):
            return
        self._recorder.fps_restart_pending = False
        try:
            print("[capture] Restarting recorder to apply deferred fps change")
            with self._recorder_restart_lock:
                self._recorder.stop()
                self._recorder.start()
        except Exception as e:
            print(f"[capture] Deferred recorder restart failed: {e}")

    def restart_recorder(self):
        """Apply process-level recorder settings through the backend owner."""
        if not self._running:
            return False
        if self._recording or self._recorder.recording:
            self._recorder.fps_restart_pending = True
            return False
        with self._recorder_restart_lock:
            self._recorder.stop()
            return self._recorder.start()

    def _stop_recording(self, failure_reason: str | None = None):
        """Serialize stop/finalize transitions across every backend owner."""
        with self._recording_lock:
            return self._stop_recording_locked(failure_reason=failure_reason)

    def _stop_recording_locked(self, failure_reason: str | None = None):
        """Stop recording and queue the file for processing."""
        filepath = self._recording_path
        endgame_ts = self._endgame_timestamp
        wall_duration = (
            time.time() - self._recording_start if self._recording_start else 0.0
        )

        # Reset the RUN_COMPLETE fast-OCR mode. Rust only auto-clears it at the
        # next encoder start (possibly several runs away), so without this the
        # between-run menus keep shipping a full preview frame every ~0.5s
        # instead of ~2s — 4x the idle encode/base64/IPC work.
        self._recorder.set_ocr_fast(False)
        audio_path = self._audio.stop()
        stop_result = self._recorder.stop_recording(timeout=20.0)
        if stop_result is None:
            failure_reason = failure_reason or (
                self._recorder.last_error
                or "Recorder did not acknowledge MP4 finalization"
            )
            print(f"[capture] Finalization acknowledgement failed: {failure_reason}")
            # The native quit path owns the capture-control handle and attempts
            # one last graceful drain before its five-second kill fallback.
            with self._recorder_restart_lock:
                self._recorder.stop()

        if failure_reason:
            self._recording_failure_latched = failure_reason

        duration = float(
            (stop_result or {}).get("duration") or wall_duration
        )

        self._recording = False
        self._low_submit_fps_since = 0.0
        self._drain_p2_waiting()
        self._recording_start = 0
        self._recording_path = None
        self._scan_state = 'lobby'
        self._endgame_timestamp = None
        self._selected_crew_size = None
        self._selected_crew_size_at = 0

        if not filepath:
            print("[capture] No recording path, skipping.")
            self._maybe_restart_recorder_for_fps()
            return

        # Rust has explicitly acknowledged finalization at this point. Drain a
        # deferred fps-change restart before post-run processing begins.
        self._maybe_restart_recorder_for_fps()

        if not os.path.exists(filepath):
            failure_reason = failure_reason or f"Recording file not found: {filepath}"
            self._capture_health_error = failure_reason
            print(f"[capture] {failure_reason}")
            self._broadcast_status()
            return

        file_size = os.path.getsize(filepath)
        if file_size < 1024 * 1024:  # Less than 1MB = corrupt or empty
            failure_reason = failure_reason or (
                f"Recording too small ({file_size} bytes)"
            )

        if stop_result and not stop_result.get("finalized", True):
            failure_reason = failure_reason or (
                stop_result.get("error") or "Media Foundation failed to finalize the MP4"
            )

        if stop_result and duration >= 10:
            submitted_fps = float(stop_result.get("fps") or 0)
            captured_frames = int(stop_result.get("captured_frames") or 0)
            submitted_frames = int(stop_result.get("frames") or 0)
            capture_fps = captured_frames / duration if duration > 0 else 0
            submission_ratio = (
                submitted_frames / captured_frames if captured_frames > 0 else 0
            )

            # WGC is dirty-region driven: a 30-FPS menu or a user-capped
            # 30-FPS game legitimately supplies ~30 fresh surfaces even when
            # the output timeline is configured for 60. Reject an actual WGC
            # starvation instead of comparing source updates to that requested
            # timeline.
            if capture_fps < 10:
                failure_reason = failure_reason or (
                    f"Windows capture produced only {capture_fps:.1f} fresh fps"
                )
            elif captured_frames >= 10 and submission_ratio < 0.80:
                failure_reason = failure_reason or (
                    f"Encoder accepted only {submission_ratio * 100:.0f}% of captured frames "
                    f"({submitted_fps:.1f} submitted fps)"
                )

        if failure_reason:
            self._capture_health_error = failure_reason
            marker = filepath + ".capture_failed"
            try:
                import json
                with open(marker, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "reason": failure_reason,
                            "duration": duration,
                            "stop_result": stop_result,
                            "file_size": file_size,
                            "created_at": datetime.now().isoformat(),
                        },
                        f,
                        indent=2,
                    )
            except Exception as e:
                print(f"[capture] Could not write failure marker: {e}")
            print(
                f"[capture] Recording rejected by health checks: {failure_reason} "
                f"({file_size / (1024*1024):.1f}MB)"
            )
            self._broadcast_status()
            return

        print(f"[capture] Recording complete: {duration:.0f}s ({file_size / (1024*1024):.1f}MB)")
        if audio_path:
            print(f"[audio] Sidecar complete: {audio_path} ({os.path.getsize(audio_path) / (1024*1024):.1f}MB)")
        elif self._audio.error:
            print(f"[audio] Sidecar unavailable: {self._audio.error}")

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

        # Add to processing queue (this also kicks off thumbnail generation —
        # a second explicit call here would race a duplicate ffmpeg on the
        # same thumb file while the player is still in the lobby)
        self._add_processing_item(filepath, duration)
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

    def set_pause_processing_while_game_running(self, enabled: bool):
        """Backward-compatible mapping for older frontends."""
        return self.set_processing_guard_mode("game" if enabled else "off")

    def set_processing_guard_mode(self, mode: str):
        """Select when heavy analysis yields to Marathon."""
        if mode not in ("recording", "game", "off"):
            mode = "recording"
        self._processing_guard_mode = mode
        if not self._processing_gate_active():
            self._drain_p2_waiting()
        self._broadcast_status()
        return self.get_status()

    def _heavy_processing_blocked_by_game(self) -> bool:
        """True only in full-game mode while Marathon is visible."""
        return self._processing_guard_mode == "game" and self._recorder.window_name is not None

    def _processing_gate_active(self, phase: str = "p2") -> bool:
        """True when new work should be held to protect gameplay.

        Local (alpha) P1 is allowed in menus because it only does CPU work on
        captured screenshots. In claude mode P1 IS network — it uploads frames to
        the Claude API/CLI — so for an online shooter it must be held under the
        game-impact guard like P2, or a prior run's upload contends with the live
        match's ping. P2/media work (video scans, ffmpeg, clips) is always gated.
        """
        if self._processing_guard_mode == "off":
            return False
        if self._recording:
            return True
        return self._heavy_processing_blocked_by_game()

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
            for ext in ('.p1done', '.encoded', '.endgame', '.session', '.events'):
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

    def _generate_recording_assets(self, filepath: str, background: bool = False):
        """Generate thumbnail + sprite sheet for a full-run recording.

        Idempotent: each artifact is skipped if it already exists. Safe to call
        as soon as the heavy-media gate allows it, either during Phase 2
        finalization or from the recording-asset endpoint for older/missing
        assets.
        """
        filepath = os.path.abspath(filepath)

        if background:
            with self._asset_lock:
                if filepath in self._asset_generating:
                    return
                self._asset_generating.add(filepath)

            def _run():
                try:
                    self._generate_recording_assets(filepath)
                finally:
                    with self._asset_lock:
                        self._asset_generating.discard(filepath)

            threading.Thread(target=_run, daemon=True).start()
            return

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
            if not (os.path.exists(keep_thumb) and os.path.getsize(keep_thumb) > 5000):
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
            sprite_meta_path = filepath.replace(".mp4", "_sprite.json")
            if not (os.path.exists(sprite_path) and os.path.getsize(sprite_path) > 5000 and os.path.exists(sprite_meta_path)):
                from .video_processor import _generate_sprite_sheet
                _generate_sprite_sheet(filepath, duration)
        except Exception as e:
            print(f"[assets] Generation failed for {os.path.basename(filepath)}: {e}")

    def _auto_save_recording(self, filepath: str, run_id: int | None):
        """Finalize recording after Phase 2, generate missing assets, and clean markers."""
        filename = os.path.basename(filepath)

        if not os.path.exists(filepath):
            print(f"[auto-save] Recording not found: {filepath}")
            return

        # Generate any missing assets now that we are in the heavy media lane.
        self._generate_recording_assets(filepath)

        # Clean up marker files
        for ext in ('.p1done', '.encoded', '.endgame', '.session', '.events'):
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
                self._drain_p2_waiting()
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
            # Avoid starting analysis work while gameplay could be impacted.
            if self._processing_gate_active("p1"):
                self._process_queue.put(filepath)
                self._process_queue.task_done()
                time.sleep(2.0)
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
                if self._recording:
                    print(f"[p1] Aborted for match — re-queuing {os.path.basename(filepath)}")
                    self._update_processing_item(
                        filepath, "queued", detail="Paused while recording is active",
                    )
                    self._process_queue.put(filepath)
                    return
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

            # P1 can run in menus, so keep it light. Heavy assets are generated
            # after Phase 2 when the heavy media gate allows it.
            try:
                self._generate_thumbnail(filepath, 0)
            except Exception:
                pass

            # Invalidate clips cache so the new recording shows up immediately
            from .api.capture_api import invalidate_clips_cache
            invalidate_clips_cache()

            # Submit Phase 2 (gated by worker limit)
            self._submit_phase2(filepath, run_id)

        except Exception as e:
            if self._recording:
                print(f"[p1] Aborted for match — re-queuing {os.path.basename(filepath)}")
                self._update_processing_item(
                    filepath, "queued", detail="Paused while recording is active",
                )
                self._process_queue.put(filepath)
                return
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
            if self._processing_gate_active("p2"):
                self._p2_waiting.append((filepath, run_id))
                self._update_processing_item(filepath, "queued", run_id=run_id)
                reason = "recording active" if self._recording else "Marathon running"
                print(f"[p2] {reason} - holding Phase 2 for run #{run_id}")
                return
            if self._p2_active < self._p2_max_workers:
                self._p2_active += 1
                self._update_processing_item(filepath, "analyzing_gameplay", run_id=run_id)
                self._p2_executor.submit(self._process_phase2, filepath, run_id)
                print(f"[p2] Submitted Phase 2 for run #{run_id} ({self._p2_active}/{self._p2_max_workers} active)")
            else:
                self._p2_waiting.append((filepath, run_id))
                self._update_processing_item(filepath, "queued", run_id=run_id)
                print(f"[p2] P2 full ({self._p2_active}/{self._p2_max_workers}), run #{run_id} waiting ({len(self._p2_waiting)} in queue)")

    def _drain_p2_waiting(self):
        """Submit waiting Phase 2 jobs when the game-impact gate is clear."""
        if self._processing_gate_active("p2") or not self._auto_p2:
            return
        with self._p2_active_lock:
            while self._p2_waiting and self._p2_active < self._p2_max_workers:
                filepath, run_id = self._p2_waiting.pop(0)
                self._p2_active += 1
                self._update_processing_item(filepath, "analyzing_gameplay", run_id=run_id)
                self._p2_executor.submit(self._process_phase2, filepath, run_id)
                print(f"[p2] Submitting waiting run #{run_id} ({self._p2_active}/{self._p2_max_workers} active)")

    def _p2_finished(self):
        """Called when a P2 job completes. Drains waiting list if slots available."""
        with self._p2_active_lock:
            self._p2_active = max(0, self._p2_active - 1)
        self._drain_p2_waiting()

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
            elif self._recording:
                # Aborted mid-upload to protect the match — re-hold; the held list
                # is drained and re-submitted when recording stops. Re-runs
                # regenerate the deterministically-named clips cleanly.
                print(f"[p2] Aborted for match — re-holding run #{run_id}")
                with self._p2_active_lock:
                    self._p2_held.append((filepath, run_id))
                self._update_processing_item(filepath, "phase1_done", run_id=run_id)
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
            if self._recording:
                print(f"[p2] Aborted for match — re-holding run #{run_id}")
                with self._p2_active_lock:
                    self._p2_held.append((filepath, run_id))
                self._update_processing_item(filepath, "phase1_done", run_id=run_id)
            else:
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
                if (
                    os.path.exists(filepath + ".dismissed")
                    or os.path.exists(filepath + ".capture_failed")
                ):
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

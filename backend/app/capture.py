"""
AutoCapture -- Automatic screen recording triggered by Marathon game state.

Architecture:
  Detection (3fps):  ddagrab -> hwdownload -> JPEG pipe -> OCR button text
  Recording (60fps): ddagrab -> h264_nvenc -> MP4 file (GPU-only, zero game impact)

State machine:
  IDLE  --[READY_UP/RUN/DEPLOYING detected]--->  RECORDING
  RECORDING  --[PREPARE detected]--->  IDLE
     - if recording < 90s: delete (user backed out of lobby)
     - if recording >= 90s: queue for processing

Debounce: require 2 consecutive identical readings before acting.
"""

import os
import queue
import subprocess
import threading
import time
from datetime import datetime

from .detection.ocr import detect_button_text

# Minimum recording duration to keep (seconds).
# Shorter recordings mean the player backed out before the run started.
MIN_RECORDING_SECONDS = 90

# How many consecutive identical OCR readings before triggering a state change.
DEBOUNCE_COUNT = 2


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

        # Threads
        self._detection_thread: threading.Thread | None = None
        self._processor_thread: threading.Thread | None = None

        # FFmpeg processes
        self._detection_proc: subprocess.Popen | None = None
        self._recording_proc: subprocess.Popen | None = None

        # Latest detection frame (JPEG bytes) for the /frame endpoint
        self._latest_frame: bytes | None = None
        self._frame_lock = threading.Lock()

        # Debounce state
        self._last_detection: str | None = None
        self._consecutive_count: int = 0

        # Processing queue for completed recordings
        self._process_queue: queue.Queue = queue.Queue()

    # -- Public API ----------------------------------------------------

    def start(self) -> dict:
        """Start the detection loop and processing thread."""
        if self._running:
            return self.get_status()

        self._running = True
        print("[capture] Starting AutoCapture...")

        # Detection loop: 3fps screen capture -> OCR
        self._detection_thread = threading.Thread(
            target=self._detection_loop, daemon=True, name="detection"
        )
        self._detection_thread.start()

        # Processor loop: handles completed recordings in background
        self._processor_thread = threading.Thread(
            target=self._processor_loop, daemon=True, name="processor"
        )
        self._processor_thread.start()

        return self.get_status()

    def stop(self) -> dict:
        """Stop everything: detection, recording, processing."""
        self._running = False

        # Stop any active recording
        if self._recording:
            self._stop_recording()

        # Kill detection FFmpeg process
        self._kill_proc(self._detection_proc)
        self._detection_proc = None

        # Wait for threads to finish
        for thread in [self._detection_thread, self._processor_thread]:
            if thread and thread.is_alive():
                thread.join(timeout=5)

        print("[capture] AutoCapture stopped.")
        return self.get_status()

    def get_status(self) -> dict:
        """Return current state as a dict (for the REST API)."""
        recording_seconds = 0
        if self._recording and self._recording_start:
            recording_seconds = time.time() - self._recording_start

        return {
            "active": self._running,
            "recording": self._recording,
            "recording_seconds": round(recording_seconds, 1),
            "recording_path": self._recording_path,
            "queue_size": self._process_queue.qsize(),
        }

    def get_latest_frame_jpeg(self) -> bytes | None:
        """Return the latest detection frame as JPEG bytes."""
        with self._frame_lock:
            return self._latest_frame

    # -- Detection loop ------------------------------------------------

    def _detection_loop(self):
        """Run 3fps screen capture via FFmpeg, pipe JPEGs, OCR each frame.

        Uses a separate ddagrab at low fps so detection never touches the
        recording pipeline. The hwdownload filter pulls frames from GPU to
        CPU for OCR processing.
        """
        try:
            cmd = [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i',
                'ddagrab=framerate=4:output_idx=0,hwdownload,format=bgra',
                '-vf', 'fps=3',
                '-f', 'image2pipe', '-c:v', 'mjpeg', '-q:v', '5',
                'pipe:1',
            ]

            self._detection_proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            print("[capture] Detection started: 3fps (ddagrab -> JPEG pipe)")

            # Read JPEG stream: find SOI (ff d8) and EOI (ff d9) markers
            buf = b''
            while self._running:
                chunk = self._detection_proc.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk

                # Extract complete JPEG frames from the stream
                while True:
                    soi = buf.find(b'\xff\xd8')
                    if soi == -1:
                        buf = b''
                        break
                    eoi = buf.find(b'\xff\xd9', soi + 2)
                    if eoi == -1:
                        # Incomplete frame, keep buffer from SOI onward
                        buf = buf[soi:]
                        break

                    jpeg = buf[soi:eoi + 2]
                    buf = buf[eoi + 2:]

                    # Store frame for the /frame endpoint
                    with self._frame_lock:
                        self._latest_frame = jpeg

                    # Run OCR on the button region
                    self._handle_detection(detect_button_text(jpeg))

        except Exception as e:
            print(f"[capture] Detection error: {e}")
        finally:
            print("[capture] Detection loop stopped.")

    def _handle_detection(self, button_text: str | None):
        """Process an OCR result with debounce logic.

        Requires DEBOUNCE_COUNT consecutive identical readings before
        triggering a state change. This prevents flickering from OCR noise.
        """
        # Update debounce counter
        if button_text == self._last_detection:
            self._consecutive_count += 1
        else:
            self._last_detection = button_text
            self._consecutive_count = 1

        # Not enough consecutive readings yet
        if self._consecutive_count < DEBOUNCE_COUNT:
            return

        # Start recording when we see READY_UP, RUN, or DEPLOYING
        if not self._recording and button_text in ('READY_UP', 'RUN', 'DEPLOYING'):
            print(f"[capture] Detected '{button_text}' -- starting recording")
            self._start_recording()

        # Stop recording when we see PREPARE
        elif self._recording and button_text == 'PREPARE':
            print("[capture] Detected 'PREPARE' -- stopping recording")
            self._stop_recording()

    # -- Recording management ------------------------------------------

    def _start_recording(self):
        """Launch FFmpeg to record the screen to an MP4 file.

        Uses GPU-only pipeline: ddagrab captures the screen on GPU,
        h264_nvenc encodes on GPU. Zero game performance impact.
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"run_{timestamp}.mp4"
        filepath = os.path.join(self.recordings_dir, filename)

        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
            '-f', 'lavfi', '-i', 'ddagrab=framerate=60:output_idx=0',
            '-c:v', 'h264_nvenc',
            '-preset', 'p4', '-tune', 'll',
            '-rc', 'vbr', '-cq', '23',
            '-g', '60',  # Keyframe every second
            filepath,
        ]

        self._recording_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        self._recording = True
        self._recording_start = time.time()
        self._recording_path = filepath
        print(f"[capture] Recording to: {filepath}")

    def _stop_recording(self):
        """Stop the recording FFmpeg process and handle the output file.

        Short recordings (< MIN_RECORDING_SECONDS) are deleted because they
        mean the player backed out of the lobby before the run started.
        Longer recordings are queued for processing.
        """
        self._kill_proc(self._recording_proc)
        self._recording_proc = None
        self._recording = False

        duration = time.time() - self._recording_start
        filepath = self._recording_path
        self._recording_start = 0
        self._recording_path = None

        if not filepath or not os.path.exists(filepath):
            print("[capture] Recording file not found, skipping.")
            return

        if duration < MIN_RECORDING_SECONDS:
            # Too short -- player backed out of lobby
            print(f"[capture] Recording too short ({duration:.0f}s < {MIN_RECORDING_SECONDS}s), deleting.")
            try:
                os.remove(filepath)
            except OSError:
                pass
        else:
            # Real run -- queue for processing
            print(f"[capture] Recording complete: {duration:.0f}s -> queued for processing")
            self._process_queue.put(filepath)

    # -- Processing loop -----------------------------------------------

    def _processor_loop(self):
        """Background thread that processes completed recordings.

        Pulls filepaths from the queue and processes them. Currently a
        placeholder -- will call Claude Sonnet for video analysis in the
        next step.
        """
        while self._running:
            try:
                filepath = self._process_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            print(f"[processor] Processing: {filepath}")
            # TODO: Send to Claude Sonnet for run analysis
            self._process_queue.task_done()

        # Drain remaining items on shutdown
        while not self._process_queue.empty():
            try:
                filepath = self._process_queue.get_nowait()
                print(f"[processor] Processing (shutdown): {filepath}")
                self._process_queue.task_done()
            except queue.Empty:
                break

        print("[processor] Processor loop stopped.")

    # -- Helpers -------------------------------------------------------

    @staticmethod
    def _kill_proc(proc: subprocess.Popen | None):
        """Gracefully terminate an FFmpeg subprocess."""
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

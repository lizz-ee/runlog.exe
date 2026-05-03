"""
Low-impact sidecar audio capture for run recordings.

The video recorder stays on the Rust/WGC hot path. This module records system
loopback audio in a separate Python thread and writes a WAV next to the MP4.
If the optional soundcard dependency or a loopback device is unavailable, audio
capture fails soft and video recording continues.
"""

from __future__ import annotations

import os
import threading
import wave
from dataclasses import dataclass

import numpy as np


@dataclass
class AudioSidecarStatus:
    active: bool = False
    path: str | None = None
    error: str | None = None


class AudioSidecarRecorder:
    """Record default speaker loopback audio to a PCM WAV file."""

    def __init__(self, sample_rate: int = 48000, channels: int = 2, chunk_seconds: float = 0.5):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_frames = max(1024, int(sample_rate * chunk_seconds))
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.status = AudioSidecarStatus()

    @property
    def active(self) -> bool:
        return self.status.active

    @property
    def path(self) -> str | None:
        return self.status.path

    @property
    def error(self) -> str | None:
        return self.status.error

    def start(self, wav_path: str) -> bool:
        """Start recording. Returns False if audio cannot be started."""
        with self._lock:
            if self.status.active:
                return True

            self._stop.clear()
            os.makedirs(os.path.dirname(os.path.abspath(wav_path)), exist_ok=True)
            self.status = AudioSidecarStatus(active=True, path=wav_path, error=None)
            self._thread = threading.Thread(
                target=self._record_loop,
                args=(wav_path,),
                daemon=True,
                name="audio-sidecar",
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = 2.0) -> str | None:
        """Stop recording and return the WAV path if a non-empty file exists."""
        with self._lock:
            thread = self._thread
            path = self.status.path
            self._stop.set()

        if thread and thread.is_alive():
            thread.join(timeout=timeout)

        with self._lock:
            self.status.active = False
            self._thread = None

        if path and os.path.exists(path) and os.path.getsize(path) > 44:
            return path
        return None

    def _record_loop(self, wav_path: str) -> None:
        try:
            import soundcard as sc
        except Exception as e:
            self._fail(f"soundcard unavailable: {e}")
            return

        try:
            speaker = sc.default_speaker()
            if speaker is None:
                self._fail("no default speaker loopback device")
                return

            loopback = sc.get_microphone(id=str(speaker.name), include_loopback=True)

            with wave.open(wav_path, "wb") as wav:
                wav.setnchannels(self.channels)
                wav.setsampwidth(2)
                wav.setframerate(self.sample_rate)

                with loopback.recorder(samplerate=self.sample_rate, channels=self.channels) as recorder:
                    while not self._stop.is_set():
                        data = recorder.record(numframes=self.chunk_frames)
                        if data is None or len(data) == 0:
                            continue
                        pcm = self._float_to_pcm16(data)
                        wav.writeframes(pcm)
        except Exception as e:
            self._fail(f"audio capture failed: {e}")

    def _fail(self, message: str) -> None:
        with self._lock:
            self.status.active = False
            self.status.error = message
        print(f"[audio] {message}")

    @staticmethod
    def _float_to_pcm16(data) -> bytes:
        arr = np.asarray(data, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        arr = np.clip(arr, -1.0, 1.0)
        return (arr * 32767.0).astype("<i2", copy=False).tobytes()

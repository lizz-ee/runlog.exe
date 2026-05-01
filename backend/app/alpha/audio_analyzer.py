"""
Audio Analyzer — Detect combat activity from game audio.

Extracts the audio track from a video and analyzes volume/frequency patterns
to find combat windows (gunfire, explosions, hit sounds).

Gracefully handles videos with no audio data (returns empty results).

Layer 2 of the alpha highlight detection pipeline.
"""

import logging
import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AudioSegment:
    """A detected audio activity segment."""
    start_sec: int
    end_sec: int
    intensity: float  # 0.0 - 1.0, relative volume
    is_combat: bool   # True if frequency profile matches gunfire/combat


class AudioAnalyzer:
    """Analyze game audio to detect combat windows."""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate

    def extract_audio(self, video_path: str) -> np.ndarray | None:
        """Extract mono audio from video as numpy float32 array.

        Returns None if video has no audio data.
        """
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-i', os.path.abspath(video_path),
                '-map', '0:a:0',
                '-ac', '1',
                '-ar', str(self.sample_rate),
                '-c:a', 'pcm_s16le',
                tmp_path,
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=120)

            if result.returncode != 0 or not os.path.exists(tmp_path):
                logger.info("No audio track available")
                return None

            file_size = os.path.getsize(tmp_path)
            if file_size < 1000:  # Less than 1KB = empty audio
                logger.info("Audio track is empty (no data)")
                return None

            # Read WAV data without scipy; ffmpeg writes mono pcm_s16le.
            with wave.open(tmp_path, "rb") as wav:
                sr = wav.getframerate()
                sample_width = wav.getsampwidth()
                n_frames = wav.getnframes()
                raw = wav.readframes(n_frames)

            if sample_width != 2:
                logger.info("Unsupported audio sample width: %s bytes", sample_width)
                return None

            audio = np.frombuffer(raw, dtype=np.int16)

            if len(audio) == 0:
                logger.info("Audio track has zero samples")
                return None

            # Convert to float32 normalized
            audio = audio.astype(np.float32) / 32768.0

            duration = len(audio) / sr
            logger.info(f"Audio extracted: {duration:.0f}s, {sr}Hz, {len(audio)} samples")
            return audio

        except subprocess.TimeoutExpired:
            logger.warning("Audio extraction timed out")
            return None
        except Exception as e:
            logger.warning(f"Audio extraction failed: {e}")
            return None
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    def compute_rms(self, audio: np.ndarray, window_sec: float = 1.0) -> np.ndarray:
        """Compute RMS energy in fixed-size windows.

        Returns array of RMS values, one per window (typically 1 per second).
        """
        window = int(self.sample_rate * window_sec)
        n_windows = len(audio) // window
        if n_windows == 0:
            return np.array([])

        # Reshape for vectorized RMS computation
        trimmed = audio[:n_windows * window].reshape(n_windows, window)
        rms = np.sqrt(np.mean(trimmed ** 2, axis=1))
        return rms

    def compute_spectral_energy(self, audio: np.ndarray,
                                 window_sec: float = 1.0) -> np.ndarray:
        """Compute high-frequency energy ratio per window.

        Gunfire and combat sounds have more high-frequency content than
        ambient/dialogue. Returns ratio of high-freq to total energy per window.
        """
        window = int(self.sample_rate * window_sec)
        n_windows = len(audio) // window
        if n_windows == 0:
            return np.array([])

        hf_ratios = np.zeros(n_windows)
        cutoff_bin = int(window * 2000 / self.sample_rate)  # 2kHz cutoff

        for i in range(n_windows):
            chunk = audio[i * window:(i + 1) * window]
            spectrum = np.abs(np.fft.rfft(chunk))
            total = spectrum.sum()
            if total > 0:
                high_freq = spectrum[cutoff_bin:].sum()
                hf_ratios[i] = high_freq / total

        return hf_ratios

    def detect_segments(self, audio: np.ndarray,
                        rms_threshold_std: float = 1.5,
                        gap_sec: int = 5) -> list[AudioSegment]:
        """Detect combat/activity segments from audio.

        A segment is a consecutive run of loud seconds, with gaps
        of up to `gap_sec` merged together.

        Parameters
        ----------
        audio : float32 numpy array (mono)
        rms_threshold_std : how many std devs above mean = "loud"
        gap_sec : merge segments within this many seconds

        Returns
        -------
        list of AudioSegment
        """
        rms = self.compute_rms(audio)
        if len(rms) == 0:
            return []

        # Dynamic threshold: mean + N * std
        threshold = rms.mean() + rms_threshold_std * rms.std()
        loud = rms > threshold

        # Also compute spectral energy for combat classification
        hf_ratios = self.compute_spectral_energy(audio)

        # Find loud second indices
        loud_indices = np.where(loud)[0]
        if len(loud_indices) == 0:
            return []

        # Cluster into segments with gap tolerance
        segments = []
        start = loud_indices[0]
        prev = loud_indices[0]

        for idx in loud_indices[1:]:
            if idx - prev > gap_sec:
                segments.append(self._make_segment(start, prev, rms, hf_ratios))
                start = idx
            prev = idx
        segments.append(self._make_segment(start, prev, rms, hf_ratios))

        logger.info(f"Audio analysis: {len(segments)} activity segments from "
                     f"{len(loud_indices)}/{len(rms)} loud seconds")
        return segments

    def _make_segment(self, start: int, end: int,
                      rms: np.ndarray, hf_ratios: np.ndarray) -> AudioSegment:
        """Create an AudioSegment with intensity and combat classification."""
        seg_rms = rms[start:end + 1]
        intensity = float(seg_rms.mean() / rms.max()) if rms.max() > 0 else 0.0

        # Combat = high frequency ratio above threshold (gunfire/explosions)
        seg_hf = hf_ratios[start:end + 1] if len(hf_ratios) > end else np.array([])
        is_combat = bool(seg_hf.mean() > 0.3) if len(seg_hf) > 0 else False

        return AudioSegment(
            start_sec=int(start),
            end_sec=int(end),
            intensity=round(intensity, 3),
            is_combat=is_combat,
        )

    def analyze_video(self, video_path: str) -> list[AudioSegment]:
        """Full pipeline: extract audio → detect segments.

        Returns empty list if video has no audio.
        """
        audio = self.extract_audio(video_path)
        if audio is None:
            return []
        return self.detect_segments(audio)

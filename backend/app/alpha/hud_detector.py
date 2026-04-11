"""
HUD Detector — Read game HUD elements from video frames to detect highlights.

Crops the bottom-left HUD region (squad list, health bar, kill feed) and
uses template matching + OCR to identify events:
  - Kill feed: "RUNNER ELIM", "COMBATANT ELIM", "FINISHER"
  - Health bar: pixel color analysis (green → red = critical)
  - Squad status: "REVIVING...", "ELIMINATED"
  - Death screen: "NEURAL LINK SEVERED" (full-frame template)
  - Extraction: "MATTER TRANSFER IN" / "//RUN_COMPLETE" (full-frame template)
"""

import logging
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from backend.app.alpha.ocr_pipeline import _ocr_sync

logger = logging.getLogger(__name__)

# HUD crop region: bottom-left (squad + health + kill feed)
HUD_CROP = (0.0, 0.58, 0.57, 1.0)  # (x1%, y1%, x2%, y2%)

# Kill feed crop: center-bottom (RUNNER ELIM / COMBATANT ELIM text)
KILL_FEED_CROP = (0.35, 0.70, 0.57, 0.80)

# Health bar region (just the bar itself)
HEALTH_BAR_CROP = (0.02, 0.88, 0.25, 0.92)

# Event types
EVENT_PVP_KILL = "pvp_kill"
EVENT_PVE_KILL = "pve_kill"
EVENT_DEATH = "death"
EVENT_EXTRACTION = "extraction"
EVENT_CLOSE_CALL = "close_call"
EVENT_REVIVE = "revive"
EVENT_COMBAT = "combat"
EVENT_IDLE = "idle"
EVENT_LOADING = "loading"
EVENT_POSTGAME = "postgame"


class HUDDetector:
    """Detect game events by reading HUD elements from video frames."""

    def __init__(self):
        from backend.app.alpha.templates import TemplateEngine
        self.engine = TemplateEngine()

    def extract_frames(self, video_path: str, fps: int = 1,
                       output_dir: str | None = None) -> list[str]:
        """Extract frames from video at given fps using ffmpeg.

        Returns list of frame file paths.
        """
        video_path = os.path.abspath(video_path)
        if output_dir is None:
            output_dir = os.path.join(
                os.path.dirname(video_path),
                f"_hud_frames_{os.path.basename(video_path).replace('.mp4', '')}"
            )
        os.makedirs(output_dir, exist_ok=True)

        pattern = os.path.join(output_dir, "frame_%04d.jpg")
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-i', video_path,
            '-vf', f'fps={fps}',
            '-q:v', '3', pattern,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=300)
        except subprocess.TimeoutExpired:
            logger.warning("Frame extraction timed out after 5 minutes")
        except Exception as e:
            logger.error(f"Frame extraction failed: {e}")

        frames = sorted(
            [os.path.join(output_dir, f) for f in os.listdir(output_dir)
             if f.startswith("frame_") and f.endswith(".jpg")]
        )
        logger.info(f"Extracted {len(frames)} frames at {fps}fps")
        return frames

    def analyze_frame(self, frame_path: str) -> dict:
        """Analyze a single frame for HUD events.

        Returns dict with detected events and confidence signals.
        """
        frame = cv2.imread(frame_path)
        if frame is None:
            return {"state": EVENT_IDLE}

        h, w = frame.shape[:2]
        result = {
            "state": EVENT_IDLE,
            "kill_feed": None,
            "health_pct": None,
            "health_critical": False,
            "squad_reviving": False,
            "squad_eliminated": False,
        }

        # --- Full-frame checks (death, extraction, loading, postgame) ---
        if self.engine.is_death_screen(frame):
            result["state"] = EVENT_DEATH
            return result

        if self.engine.is_run_complete(frame):
            result["state"] = EVENT_POSTGAME
            return result

        if self.engine.is_exfiltrated_screen(frame):
            result["state"] = EVENT_EXTRACTION
            return result

        if self.engine.is_deploy_screen(frame):
            result["state"] = EVENT_LOADING
            return result

        if self.engine.is_lobby(frame):
            result["state"] = EVENT_LOADING
            return result

        # --- Health bar analysis (pixel colors) ---
        result["health_pct"] = self._read_health_bar(frame)
        result["health_critical"] = (result["health_pct"] is not None
                                     and result["health_pct"] < 30)

        # --- Kill feed OCR (center-bottom region) ---
        kill_text = self._read_kill_feed(frame)
        if kill_text:
            result["kill_feed"] = kill_text
            if "RUNNER" in kill_text.upper():
                result["state"] = EVENT_PVP_KILL
            elif "COMBATANT" in kill_text.upper():
                result["state"] = EVENT_PVE_KILL
            elif "FINISHER" in kill_text.upper():
                # Finisher without explicit type — check context
                result["state"] = EVENT_PVP_KILL  # Usually a runner kill

        # --- Squad status OCR (left panel) ---
        squad_text = self._read_squad_status(frame)
        if squad_text:
            if "REVIVING" in squad_text.upper():
                result["squad_reviving"] = True
                if result["state"] == EVENT_IDLE:
                    result["state"] = EVENT_REVIVE
            if "ELIMINATED" in squad_text.upper():
                result["squad_eliminated"] = True

        # --- Close call detection ---
        if result["health_critical"] and result["state"] in (EVENT_IDLE, EVENT_PVE_KILL):
            result["state"] = EVENT_CLOSE_CALL

        return result

    def _read_health_bar(self, frame: np.ndarray) -> float | None:
        """Read health percentage from the health bar pixel colors.

        The health bar transitions from green (full) → yellow → red (low).
        Returns estimated health percentage (0-100), or None if not detected.
        """
        h, w = frame.shape[:2]
        x1 = int(w * HEALTH_BAR_CROP[0])
        y1 = int(h * HEALTH_BAR_CROP[1])
        x2 = int(w * HEALTH_BAR_CROP[2])
        y2 = int(h * HEALTH_BAR_CROP[3])
        bar = frame[y1:y2, x1:x2]

        if bar.size == 0:
            return None

        # Convert to HSV for better color detection
        hsv = cv2.cvtColor(bar, cv2.COLOR_BGR2HSV)

        # Health bar is bright colored pixels on a dark background
        # Mask out dark pixels (background, empty bar segments)
        bright_mask = hsv[:, :, 2] > 60  # Value > 60

        if bright_mask.sum() < 10:
            return None

        # Count green vs red pixels in the bright region
        hue = hsv[:, :, 0]
        sat = hsv[:, :, 1]
        bright_and_sat = bright_mask & (sat > 40)

        if bright_and_sat.sum() < 5:
            return None

        hues = hue[bright_and_sat]
        # Green hues: 35-85, Red hues: 0-15 or 165-180, Yellow: 15-35
        green_pct = np.sum((hues > 35) & (hues < 85)) / len(hues) * 100
        red_pct = np.sum((hues < 15) | (hues > 165)) / len(hues) * 100

        # Also estimate by how far the bright pixels extend (bar fill)
        col_brightness = bright_and_sat.any(axis=0)
        if col_brightness.sum() == 0:
            return None

        # The bar fills from left to right
        fill_pct = col_brightness.sum() / len(col_brightness) * 100

        # Combine color + fill for estimate
        if red_pct > 50:
            return min(fill_pct, 25)  # Mostly red = low health
        elif green_pct > 50:
            return max(fill_pct, 50)  # Mostly green = healthy
        else:
            return fill_pct  # Mixed = mid health

    def _read_kill_feed(self, frame: np.ndarray) -> str | None:
        """Read kill feed text from the center-bottom HUD region.

        Looks for: "RUNNER ELIM", "COMBATANT ELIM", "FINISHER"
        """
        h, w = frame.shape[:2]
        x1 = int(w * KILL_FEED_CROP[0])
        y1 = int(h * KILL_FEED_CROP[1])
        x2 = int(w * KILL_FEED_CROP[2])
        y2 = int(h * KILL_FEED_CROP[3])
        crop = frame[y1:y2, x1:x2]

        if crop.size == 0:
            return None

        # Check if there's any bright text in this region
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        bright_pixels = np.sum(gray > 150)
        total_pixels = gray.size

        # If less than 1% of pixels are bright, no text present
        if bright_pixels / total_pixels < 0.01:
            return None

        # OCR the region
        try:
            pil_crop = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            # Upscale for better OCR
            scale = max(1, 800 // pil_crop.width)
            if scale > 1:
                pil_crop = pil_crop.resize(
                    (pil_crop.width * scale, pil_crop.height * scale),
                    Image.LANCZOS
                )
            text = _ocr_sync(pil_crop)
            if text and len(text.strip()) > 3:
                return text.strip()
        except Exception as e:
            logger.debug(f"Kill feed OCR failed: {e}")

        return None

    def _read_squad_status(self, frame: np.ndarray) -> str | None:
        """Read squad status text from the left panel.

        Looks for: "REVIVING...", "ELIMINATED"
        """
        h, w = frame.shape[:2]
        # Left panel: 0-25% width, 58-78% height
        x1 = 0
        y1 = int(h * 0.58)
        x2 = int(w * 0.25)
        y2 = int(h * 0.78)
        crop = frame[y1:y2, x1:x2]

        if crop.size == 0:
            return None

        # Check for colored status text (green REVIVING, red ELIMINATED)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

        # Look for bright green (REVIVING) or bright red (ELIMINATED) text
        green_mask = (hsv[:, :, 0] > 35) & (hsv[:, :, 0] < 85) & \
                     (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 150)
        red_mask = ((hsv[:, :, 0] < 15) | (hsv[:, :, 0] > 165)) & \
                   (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 150)

        has_green = green_mask.sum() > 50
        has_red = red_mask.sum() > 50

        if not has_green and not has_red:
            return None

        # OCR the region
        try:
            pil_crop = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
            scale = max(1, 800 // pil_crop.width)
            if scale > 1:
                pil_crop = pil_crop.resize(
                    (pil_crop.width * scale, pil_crop.height * scale),
                    Image.LANCZOS
                )
            text = _ocr_sync(pil_crop)
            if text:
                return text.strip()
        except Exception as e:
            logger.debug(f"Squad status OCR failed: {e}")

        return None

    def scan_video(self, video_path: str, fps: int = 1) -> list[dict]:
        """Scan entire video and return timestamped events.

        Returns list of dicts: [{timestamp: int, ...analysis_fields}]
        """
        frames = self.extract_frames(video_path, fps=fps)
        if not frames:
            return []

        events = []
        for i, frame_path in enumerate(frames):
            timestamp = i  # At 1fps, frame index = seconds
            result = self.analyze_frame(frame_path)
            result["timestamp"] = timestamp
            events.append(result)

            if (i + 1) % 60 == 0:
                logger.info(f"Scanned {i+1}/{len(frames)} frames...")

        # Cleanup frames
        frames_dir = os.path.dirname(frames[0]) if frames else None
        if frames_dir:
            try:
                import shutil
                shutil.rmtree(frames_dir, ignore_errors=True)
            except Exception:
                pass

        logger.info(f"Scan complete: {len(events)} frames, "
                     f"{sum(1 for e in events if e['state'] != EVENT_IDLE)} non-idle")
        return events

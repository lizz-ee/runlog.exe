"""
Highlight Detector — Merge HUD + Audio signals into clip-worthy highlights.

Combines two detection layers:
  Layer 1 (HUD): Frame-by-frame game state from template matching + OCR
  Layer 2 (Audio): Combat windows from volume/frequency analysis

The merger produces timestamped highlights with types and durations,
compatible with the main build's cut_clips() function.
"""

import logging
from dataclasses import dataclass

from backend.app.alpha.audio_analyzer import AudioAnalyzer, AudioSegment
from backend.app.alpha.hud_detector import (
    HUDDetector,
    EVENT_PVP_KILL, EVENT_PVE_KILL, EVENT_DEATH, EVENT_EXTRACTION,
    EVENT_CLOSE_CALL, EVENT_REVIVE, EVENT_COMBAT, EVENT_IDLE,
    EVENT_LOADING, EVENT_POSTGAME,
)

logger = logging.getLogger(__name__)

# Clip duration ranges (seconds)
CLIP_DURATIONS = {
    "pvp_kill": (8, 15),
    "death": (8, 15),
    "revive": (6, 10),
    "close_call": (8, 15),
    "combat": (10, 20),
    "extraction": (10, 15),
    "combat_streak": (12, 25),
}

# Minimum PvE kills in a window to count as a streak
PVE_STREAK_MIN = 3
PVE_STREAK_WINDOW = 15  # seconds


@dataclass
class Highlight:
    """A detected highlight moment."""
    timestamp_seconds: int
    duration_seconds: int
    type: str
    description: str
    confidence: float  # 0.0 - 1.0


class HighlightDetector:
    """Detect highlights from video using HUD + Audio analysis."""

    def __init__(self):
        self.hud = HUDDetector()
        self.audio = AudioAnalyzer()

    def detect(self, video_path: str, stats: dict | None = None,
               audio_path: str | None = None) -> list[dict]:
        """Full detection pipeline: scan video → merge signals → produce highlights.

        Parameters
        ----------
        video_path : path to the video file
        stats : Phase 1 stats dict (used for cross-validation)

        Returns
        -------
        list of highlight dicts compatible with cut_clips()

        After calling detect(), self.last_audio_segments contains the raw
        AudioSegment list for reuse (avoids double extraction).
        """
        # Layer 1: HUD frame scanning
        logger.info("Layer 1: Scanning HUD frames...")
        hud_events = self.hud.scan_video(video_path, fps=1)

        # Layer 2: Audio analysis (gracefully empty if no audio)
        logger.info("Layer 2: Analyzing audio...")
        audio_segments = self.audio.analyze_video(video_path, audio_path=audio_path)
        self.last_audio_segments = audio_segments  # Expose for reuse

        # Merge signals into highlights
        logger.info("Merging HUD + Audio signals...")
        highlights = self._merge_events(hud_events, audio_segments, stats)

        # Sort by priority, then timestamp
        priority = {
            "pvp_kill": 0, "death": 1, "revive": 2, "close_call": 3,
            "extraction": 4, "combat_streak": 5, "combat": 6,
        }
        highlights.sort(key=lambda h: (priority.get(h["type"], 99),
                                        h["timestamp_seconds"]))

        logger.info(f"Detection complete: {len(highlights)} highlights")
        return highlights

    def _merge_events(self, hud_events: list[dict],
                      audio_segments: list[AudioSegment],
                      stats: dict | None) -> list[dict]:
        """Merge HUD events and audio segments into highlights."""
        highlights = []

        # --- Extract mandatory events from HUD ---

        # PvP kills
        pvp_kills = self._find_events(hud_events, EVENT_PVP_KILL)
        for ts in pvp_kills:
            audio_boost = self._audio_active_at(audio_segments, ts)
            highlights.append(self._make_highlight(
                ts, "pvp_kill",
                "Runner elimination detected from kill feed",
                confidence=0.9 if audio_boost else 0.7,
            ))

        # Death
        death_events = self._find_events(hud_events, EVENT_DEATH)
        if death_events:
            # Use the first death screen appearance
            death_ts = death_events[0]
            # Look back for the combat that led to death
            lead_up = self._find_combat_before(hud_events, death_ts, max_lookback=15)
            start_ts = lead_up if lead_up is not None else max(0, death_ts - 10)
            highlights.append(self._make_highlight(
                start_ts, "death",
                "Player eliminated — NEURAL LINK SEVERED",
                confidence=0.95,
                duration=min(death_ts - start_ts + 5, 20),
            ))

        # Extraction
        extraction_events = self._find_events(hud_events, EVENT_EXTRACTION)
        if extraction_events:
            ext_ts = extraction_events[0]
            highlights.append(self._make_highlight(
                max(0, ext_ts - 5), "extraction",
                "Successful extraction",
                confidence=0.95,
                duration=12,
            ))

        # Revives
        revive_events = self._find_events(hud_events, EVENT_REVIVE)
        for ts in revive_events:
            highlights.append(self._make_highlight(
                ts, "revive",
                "Teammate revive",
                confidence=0.7,
                duration=8,
            ))

        # Close calls
        close_calls = self._find_events(hud_events, EVENT_CLOSE_CALL)
        for ts in close_calls:
            # Only clip if not already covered by a death or pvp_kill
            if not self._timestamp_covered(highlights, ts, margin=10):
                highlights.append(self._make_highlight(
                    ts, "close_call",
                    "Critical health during combat",
                    confidence=0.6,
                ))

        # --- PvE combat streaks ---
        pve_streaks = self._find_pve_streaks(hud_events)
        for streak_start, streak_end, kill_count in pve_streaks:
            if not self._timestamp_covered(highlights, streak_start, margin=10):
                highlights.append(self._make_highlight(
                    streak_start, "combat_streak",
                    f"{kill_count} PvE eliminations in rapid succession",
                    confidence=0.6,
                    duration=min(streak_end - streak_start + 5, 25),
                ))

        # --- Audio-only combat (no HUD event but loud combat audio) ---
        if audio_segments:
            for seg in audio_segments:
                if seg.is_combat and seg.end_sec - seg.start_sec >= 5:
                    if not self._timestamp_covered(highlights, seg.start_sec, margin=10):
                        highlights.append(self._make_highlight(
                            seg.start_sec, "combat",
                            "Combat detected from audio",
                            confidence=0.4,
                            duration=min(seg.end_sec - seg.start_sec, 20),
                        ))

        # --- Cross-validate with Phase 1 stats ---
        if stats:
            expected_pvp = stats.get("runner_eliminations") or 0
            found_pvp = sum(1 for h in highlights if h["type"] == "pvp_kill")
            if found_pvp < expected_pvp:
                logger.warning(
                    f"Phase 1 says {expected_pvp} runner kills but only found "
                    f"{found_pvp} in video — may be missing kills"
                )

        # Deduplicate overlapping highlights
        highlights = self._deduplicate(highlights)

        return highlights

    def _find_events(self, hud_events: list[dict], event_type: str) -> list[int]:
        """Find all timestamps where a specific event was detected.

        Merges consecutive frames of the same event into single timestamps.
        """
        timestamps = []
        prev_ts = -10  # Ensure first match is always added

        for event in hud_events:
            if event["state"] == event_type:
                ts = event["timestamp"]
                # Merge events within 5 seconds
                if ts - prev_ts > 5:
                    timestamps.append(ts)
                prev_ts = ts

        return timestamps

    def _find_combat_before(self, hud_events: list[dict],
                            target_ts: int, max_lookback: int = 15) -> int | None:
        """Find the start of combat leading up to a target timestamp."""
        for event in reversed(hud_events):
            ts = event["timestamp"]
            if ts >= target_ts:
                continue
            if ts < target_ts - max_lookback:
                break
            if event["state"] in (EVENT_PVP_KILL, EVENT_PVE_KILL,
                                   EVENT_CLOSE_CALL, EVENT_COMBAT):
                return ts
        return None

    def _find_pve_streaks(self, hud_events: list[dict]) -> list[tuple]:
        """Find rapid PvE kill streaks (3+ kills within PVE_STREAK_WINDOW seconds).

        Returns list of (start_ts, end_ts, kill_count).
        """
        pve_kills = [e["timestamp"] for e in hud_events
                     if e["state"] == EVENT_PVE_KILL]
        if len(pve_kills) < PVE_STREAK_MIN:
            return []

        streaks = []
        i = 0
        while i < len(pve_kills):
            # Count kills within the window
            j = i
            while j < len(pve_kills) and pve_kills[j] - pve_kills[i] <= PVE_STREAK_WINDOW:
                j += 1
            count = j - i
            if count >= PVE_STREAK_MIN:
                streaks.append((pve_kills[i], pve_kills[j - 1], count))
                i = j  # Skip past this streak
            else:
                i += 1

        return streaks

    def _audio_active_at(self, audio_segments: list[AudioSegment],
                         timestamp: int, margin: int = 3) -> bool:
        """Check if any audio segment is active at the given timestamp."""
        for seg in audio_segments:
            if seg.start_sec - margin <= timestamp <= seg.end_sec + margin:
                return True
        return False

    def _timestamp_covered(self, highlights: list[dict],
                           timestamp: int, margin: int = 10) -> bool:
        """Check if a timestamp is already covered by an existing highlight."""
        for h in highlights:
            h_start = h["timestamp_seconds"]
            h_end = h_start + h["duration_seconds"]
            if h_start - margin <= timestamp <= h_end + margin:
                return True
        return False

    def _make_highlight(self, timestamp: int, event_type: str,
                        description: str, confidence: float = 0.5,
                        duration: int | None = None) -> dict:
        """Create a highlight dict compatible with cut_clips()."""
        if duration is None:
            min_dur, max_dur = CLIP_DURATIONS.get(event_type, (8, 15))
            duration = min_dur + (max_dur - min_dur) // 2  # Middle of range

        # Remap combat_streak to "combat" for cut_clips compatibility
        clip_type = "combat" if event_type == "combat_streak" else event_type

        return {
            "timestamp_seconds": max(0, timestamp),
            "duration_seconds": duration,
            "type": clip_type,
            "description": description,
            "confidence": round(confidence, 2),
        }

    def _deduplicate(self, highlights: list[dict]) -> list[dict]:
        """Remove overlapping highlights, keeping higher-priority ones."""
        if not highlights:
            return []

        priority = {
            "pvp_kill": 0, "death": 1, "revive": 2, "close_call": 3,
            "extraction": 4, "combat": 5,
        }
        # Sort by priority (lower = higher priority)
        highlights.sort(key=lambda h: priority.get(h["type"], 99))

        kept = []
        for h in highlights:
            ts = h["timestamp_seconds"]
            # Check if this overlaps with any already-kept highlight
            overlaps = False
            for k in kept:
                k_start = k["timestamp_seconds"]
                k_end = k_start + k["duration_seconds"]
                if k_start - 3 <= ts <= k_end + 3:
                    overlaps = True
                    break
            if not overlaps:
                kept.append(h)

        return kept

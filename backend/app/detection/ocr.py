"""
OCR detection for Marathon game state.

Small scan regions, cropped at the source by the Rust recorder:
  - OCR.HUD (top band)      — persistent timer/location → reliable late attach
  - OCR.DEPLOY (center)  — map name on deployment loading screen → START recording
  - OCR.ENDGAME (upper)  — //RUN_COMPLETE banner → log timestamp for stats extraction
  - OCR.LOBBY (bottom)   — PREPARE/READY_UP buttons → STOP recording / capture loadout

The recorder ships only these crops (~18% of the frame's pixels) over IPC for
detection, so no full-frame decode or crop happens on the hot path here.

Uses Windows.Media.Ocr via winocr (~16ms per call, hardware-accelerated).
EasyOCR is NOT used here — it stays in the alpha stats pipeline only.
"""

import re
import time

from PIL import Image, ImageStat

# -- Windows OCR (winocr) -----------------------------------------------------

try:
    from winocr import recognize_pil_sync as _winocr_sync
    _WINOCR_AVAILABLE = True
except ImportError:
    _WINOCR_AVAILABLE = False
    print("[ocr] WARNING: winocr not available — install it: pip install winocr")

# Minimum crop width before OCR — ensures text is large enough to read reliably.
# At 1080p the lobby crop is ~650px wide; winocr struggles below ~800px.
_MIN_OCR_WIDTH = 800
_OCR_LOG_STATE: dict[str, tuple[str, float]] = {}
_OCR_LOG_CHANGE_INTERVAL = 5.0
_OCR_LOG_HEARTBEAT_INTERVAL = 60.0


def _log_ocr_text(label: str, text: str) -> None:
    """Keep OCR diagnostics useful without writing the same lobby line every second."""
    now = time.monotonic()
    previous = _OCR_LOG_STATE.get(label)
    should_log = (
        previous is None
        or (text != previous[0] and now - previous[1] >= _OCR_LOG_CHANGE_INTERVAL)
        or now - previous[1] >= _OCR_LOG_HEARTBEAT_INTERVAL
    )
    if should_log:
        print(f"[ocr] {label}: {text[:120]!r}")
        _OCR_LOG_STATE[label] = (text, now)


def _ocr_pil(img: Image.Image, label: str = "") -> str:
    """Run Windows OCR on a PIL image. Returns uppercase text. Safe from any thread."""
    if not _WINOCR_AVAILABLE:
        return ""
    try:
        # Upscale small crops so text is large enough for Windows OCR
        w, h = img.size
        if w < _MIN_OCR_WIDTH:
            scale = _MIN_OCR_WIDTH / w
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        result = _winocr_sync(img, "en")
        text = (result.get("text") or "").upper().strip()
        if text and label:
            _log_ocr_text(label, text)
        return text
    except Exception as e:
        print(f"[ocr] Error ({label}): {e}")
        return ""


# -- Scan regions (percentage of screen dimensions) ---------------------------
# Reference only on this side — the actual cropping happens in the Rust
# recorder. MUST stay in sync with OCR_REGIONS in backend/recorder/src/main.rs.

# OCR.DEPLOY — center screen, deployment loading screen (map name + coordinates)
DEPLOY_REGION = (0.35, 0.38, 0.65, 0.65)

# OCR.ENDGAME — upper center, //RUN_COMPLETE banner
ENDGAME_REGION = (0.28, 0.12, 0.72, 0.22)

# OCR.LOBBY — bottom center, PREPARE/READY_UP buttons
LOBBY_REGION = (0.33, 0.55, 0.67, 0.96)

# OCR.CREW — collapsed SOLO/DUOS/TRIOS selector above the RUN button.
CREW_REGION = (0.14, 0.50, 0.88, 0.70)

# OCR.KILLFEED — upper left, "[Player] eliminated [Target]" feed
KILLFEED_REGION = (0.01, 0.15, 0.30, 0.38)

# Known map names for deployment detection
MAP_NAMES = ["PERIMETER", "OUTPOST", "DIRE MARSH", "CRYO ARCHIVE"]


def crew_size_from_text(text: str) -> int | None:
    """Return the unambiguous selected crew size from selector OCR.

    The expanded menu shows all three labels, so multiple matches are
    deliberately ignored. The collapsed selector shows only the active mode.
    """
    normalized = (text or "").upper()
    matches = set()
    if re.search(r"\bS[O0]L[O0]\b", normalized):
        matches.add(1)
    if re.search(r"\bDU[O0]S?\b", normalized):
        matches.add(2)
    if re.search(r"\bTRI[O0]S?\b", normalized):
        matches.add(3)
    return next(iter(matches)) if len(matches) == 1 else None


def detect_crew_size(img: "Image.Image | None") -> int | None:
    """Read SOLO/DUOS/TRIOS from the collapsed pre-run selector."""
    if img is None:
        return None
    try:
        return crew_size_from_text(_ocr_pil(img, "CREW"))
    except Exception as e:
        print(f"[ocr] Crew size error: {e}")
        return None


def detect_map_variant(img: "Image.Image | None") -> str | None:
    """Read the selected Dire Marsh contract variant from a full lobby frame.

    The contract chip is in the top-right and explicitly reads
    ``DIRE MARSH (NIGHT)`` for the night rotation. A plain ``DIRE MARSH`` chip
    is the day rotation. This is intentionally a one-shot pre-deploy probe,
    not part of the recurring hot OCR path.
    """
    if img is None:
        return None
    try:
        w, h = img.size
        contract = img.crop((
            int(w * 0.68),
            0,
            int(w * 0.99),
            int(h * 0.12),
        ))
        text = _ocr_pil(contract, "MAP_VARIANT")
        if "DIRE" not in text or "MARSH" not in text:
            return None
        return "Night" if "NIGHT" in text else "Day"
    except Exception as e:
        print(f"[ocr] Map variant error: {e}")
        return None


def detect_kill_feed(img: "Image.Image | None") -> list[str]:
    """Scan the kill feed crop for elimination lines.

    Returns the raw OCR lines containing an elimination ("X eliminated Y").
    Used during recording to log combat timestamps for Phase 2 — purely
    additive hints, so OCR misses are harmless.
    """
    if img is None:
        return []
    try:
        text = _ocr_pil(img, "")
        if not text or "ELIMINAT" not in text:
            return []
        return [ln.strip() for ln in text.splitlines() if "ELIMINAT" in ln and ln.strip()]
    except Exception as e:
        print(f"[ocr] Kill feed error: {e}")
        return []


def _looks_like_run_complete(banner: Image.Image) -> bool:
    """Detect the RUN_COMPLETE banner visually before trying OCR."""
    mean_r, mean_g, mean_b = ImageStat.Stat(banner.convert("RGB")).mean[:3]
    brightness = (mean_r + mean_g + mean_b) / 3
    return brightness > 150 and mean_g > 180 and mean_g > mean_b * 1.2


def detect_game_state(regions: "dict[str, Image.Image]", scan_mode: str = "lobby") -> dict | None:
    """Scan ONE OCR region based on current state machine mode.

    regions: pre-cropped scan-region images from the recorder, keyed
    'lobby' | 'deploy' | 'endgame'. The deploy crop doubles as the
    postgame/center-screen region.

    scan_mode: 'lobby' | 'deploy' | 'endgame' | 'postgame'

    Returns a detection dict or None.
    """
    try:
        if scan_mode == "deploy":
            img = regions.get("deploy")
            text = _ocr_pil(img, "DEPLOY") if img else ""
            if text:
                for map_name in MAP_NAMES:
                    if map_name in text:
                        is_ranked = "RANKED" in text or "RANK" in text
                        map_variant = None
                        if map_name == "DIRE MARSH":
                            # The night contract/deployment label is explicit
                            # ("DIRE MARSH (NIGHT)"). Plain DIRE MARSH is Day.
                            map_variant = "Night" if "NIGHT" in text else "Day"
                        return {"type": "deploy", "map_name": map_name,
                                "map_variant": map_variant,
                                "is_ranked": is_ranked, "text": text}
            return None

        if scan_mode == "postgame":
            img = regions.get("deploy")
            text = _ocr_pil(img, "POSTGAME") if img else ""
            if text:
                if "EXFILTRAT" in text:
                    return {"type": "exfiltrated", "map_name": None, "text": text}
                if "ELIMINATED" in text or "ELIMINAT" in text:
                    return {"type": "eliminated", "map_name": None, "text": text}
            return None

        if scan_mode == "endgame":
            banner = regions.get("endgame")
            if banner is not None and _looks_like_run_complete(banner):
                return {"type": "endgame", "map_name": None, "text": "VISUAL_RUN_COMPLETE"}

            text = _ocr_pil(banner, "ENDGAME") if banner else ""
            if text and "RUN" in text and "COMPLETE" in text:
                return {"type": "endgame", "map_name": None, "text": text}
            # RUN_COMPLETE banner is brief (~2s) and can be missed at the staged
            # sampling interval. Fall back to checking the center region for
            # ELIMINATED/EXFILTRATED directly.
            center = regions.get("deploy")
            text2 = _ocr_pil(center, "ENDGAME_CENTER") if center else ""
            if text2:
                if "EXFILTRAT" in text2:
                    return {"type": "exfiltrated", "map_name": None, "text": text2}
                if "ELIMINATED" in text2 or "ELIMINAT" in text2:
                    return {"type": "eliminated", "map_name": None, "text": text2}
            return None

        # 'lobby' — scan LOBBY region
        # The persistent top HUD is the authoritative late-attach signal. The
        # old center-screen phrases are transient and can leave an already
        # running match unrecorded for many minutes.
        hud = regions.get("hud")
        hud_text = _ocr_pil(hud, "HUD") if hud else ""
        if hud_text:
            has_run_timer = bool(
                re.search(r"\b(?:[0-2]?\d)\s*[:;]\s*[0-5]\d\b", hud_text)
            )
            has_run_hud_phrase = any(
                phrase in hud_text
                for phrase in (
                    "EXFILS LOADING",
                    "MINUTES REMAIN",
                    "SIGNAL JAMMED",
                    "REINFORCEMENTS INCOMING",
                )
            )
            if has_run_timer or has_run_hud_phrase:
                return {"type": "in_run", "map_name": None, "text": hud_text}

        img = regions.get("lobby")
        text = _ocr_pil(img, "LOBBY") if img else ""
        if text:
            if "EXFILTRAT" in text:
                return {"type": "exfiltrated", "map_name": None, "text": text}
            if "ELIMINATED" in text or "ELIMINAT" in text:
                return {"type": "eliminated", "map_name": None, "text": text}
            # Late attach: RunLog may launch after the short deployment/map
            # title has already disappeared. These phrases are combat-HUD
            # signals, not lobby controls, and let capture begin for the
            # remainder of an already active run.
            if "RUNNER DOWN" in text or "MINUTES REMAIN" in text:
                return {"type": "in_run", "map_name": None, "text": text}
            if "DEPLOYING" in text:
                return {"type": "deploying", "map_name": None, "text": text}
            if "RUN" in text and "COMPLETE" not in text and "RUN TIME" not in text and "RUNNER" not in text:
                return {"type": "run", "map_name": None, "text": text}
            if "READY UP" in text or "READYUP" in text or "READY_UP" in text:
                return {"type": "ready_up", "map_name": None, "text": text}
            if "SELECT ZONE" in text or "SELECT_ZONE" in text or "SELECTZONE" in text:
                return {"type": "select_zone", "map_name": None, "text": text}
            if ("PREPARE" in text or "PREPAAE" in text or "PREPAQE" in text or "PREPAPE" in text) \
                    and "PREPARED" not in text:
                return {"type": "prepare", "map_name": None, "text": text}
            if "SEARCHING" in text:
                return {"type": "searching", "map_name": None, "text": text}

        return None

    except Exception as e:
        print(f"[ocr] Error: {e}")
        return None

"""
REST endpoints for the CaptureEngine (screen capture + clip saving).
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel

from ..capture import CaptureEngine

router = APIRouter()

# ── Module-level singleton ────────────────────────────────────────────
_engine: CaptureEngine | None = None


def _get_engine() -> CaptureEngine:
    """Return the singleton, or raise if not yet started."""
    if _engine is None:
        raise HTTPException(status_code=409, detail="Capture engine has not been started. POST /api/capture/start first.")
    return _engine


# ── Request schemas ───────────────────────────────────────────────────

class ClipRequest(BaseModel):
    seconds_before: float = 20
    seconds_after: float = 5
    event: str = "clip"


# ── Endpoints ─────────────────────────────────────────────────────────

@router.post("/start")
def capture_start():
    """Start the capture engine (creates it on first call)."""
    global _engine
    if _engine is None:
        _engine = CaptureEngine()
    status = _engine.start()
    return JSONResponse(content=status)


@router.post("/stop")
def capture_stop():
    """Stop the capture engine."""
    engine = _get_engine()
    status = engine.stop()
    return JSONResponse(content=status)


@router.get("/status")
def capture_status():
    """Return current capture engine status."""
    engine = _get_engine()
    return JSONResponse(content=engine.get_status())


@router.post("/clip")
def capture_clip(req: ClipRequest):
    """
    Save a clip from the ring buffer.

    Body:
        seconds_before — seconds of history to include (default 20)
        seconds_after  — additional seconds to capture after the call (default 5)
        event          — label for the clip filename (default "clip")
    """
    engine = _get_engine()
    try:
        result = engine.save_clip(
            seconds_before=req.seconds_before,
            seconds_after=req.seconds_after,
            metadata={"event": req.event},
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return JSONResponse(content=result)


@router.get("/frame")
def capture_frame():
    """Return the latest full-resolution frame as JPEG (for OCR / detection)."""
    engine = _get_engine()
    jpeg = engine.get_latest_frame_jpeg()
    if jpeg is None:
        raise HTTPException(status_code=404, detail="No frame available yet")
    return Response(content=jpeg, media_type="image/jpeg")

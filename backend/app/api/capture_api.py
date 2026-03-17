"""
REST endpoints for the AutoCapture engine.

Mounted at /api/capture by the API router.
Provides start/stop/status/frame endpoints for the singleton capture engine.
"""

import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, JSONResponse

from ..capture import AutoCapture

router = APIRouter()

# -- Module-level singleton --------------------------------------------

_engine: AutoCapture | None = None

# Default directories (relative to CWD, created on first start)
RECORDINGS_DIR = os.path.join(os.getcwd(), "recordings")
CLIPS_DIR = os.path.join(os.getcwd(), "clips")


def _get_engine() -> AutoCapture:
    """Return the singleton, or raise 409 if not yet started."""
    if _engine is None:
        raise HTTPException(
            status_code=409,
            detail="Capture engine not started. POST /api/capture/start first.",
        )
    return _engine


# -- Endpoints ---------------------------------------------------------

@router.post("/start")
def capture_start():
    """Create and start the AutoCapture engine (singleton)."""
    global _engine
    if _engine is None:
        _engine = AutoCapture(
            recordings_dir=RECORDINGS_DIR,
            clips_dir=CLIPS_DIR,
        )
    status = _engine.start()
    return JSONResponse(content=status)


@router.post("/stop")
def capture_stop():
    """Stop the capture engine and all recording/detection."""
    engine = _get_engine()
    status = engine.stop()
    return JSONResponse(content=status)


@router.get("/status")
def capture_status():
    """Return current capture engine state."""
    engine = _get_engine()
    return JSONResponse(content=engine.get_status())


@router.get("/frame")
def capture_frame():
    """Return the latest detection frame as JPEG (for debugging/preview)."""
    engine = _get_engine()
    jpeg = engine.get_latest_frame_jpeg()
    if jpeg is None:
        raise HTTPException(status_code=404, detail="No frame available yet.")
    return Response(content=jpeg, media_type="image/jpeg")

"""
REST endpoints for the AutoCapture engine.

Mounted at /api/capture by the API router.
Provides start/stop/status/frame endpoints for the singleton capture engine.
"""

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel

from ..capture import AutoCapture
from ..config import _DATA_DIR

router = APIRouter()

# -- Module-level singleton --------------------------------------------

_engine: AutoCapture | None = None

# All data lives under AppData/marathon-runlog/data/ — same as the DB
RECORDINGS_DIR = os.path.join(_DATA_DIR, "recordings")
CLIPS_DIR = os.path.join(_DATA_DIR, "clips")


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
    if _engine is None:
        return JSONResponse(content={
            "active": False,
            "recording": False,
            "recording_seconds": 0,
            "recording_path": None,
            "queue_size": 0,
            "processing_phase": None,
            "processing_items": [],
            "status_counts": {},
            "resumed_count": 0,
            "capture_mode": "none",
            "last_result": None,
        })
    return JSONResponse(content=_engine.get_status())


@router.get("/frame")
def capture_frame():
    """Return the latest detection frame as JPEG. All overlays are CSS now."""
    engine = _get_engine()
    jpeg = engine.get_latest_frame_jpeg()
    if jpeg is None:
        raise HTTPException(status_code=404, detail="No frame available yet.")
    return Response(content=jpeg, media_type="image/jpeg")


@router.get("/thumbnail/{filename}")
def serve_thumbnail(filename: str):
    """Serve a recording thumbnail image."""
    filepath = os.path.join(RECORDINGS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Thumbnail not found")
    from fastapi.responses import FileResponse
    return FileResponse(filepath, media_type="image/jpeg")


@router.get("/clips")
def list_clips():
    """List all highlight clips with metadata.

    Filename format: clip_YYYYMMDD_HHMMSS_type_N.mp4
    The YYYYMMDD_HHMMSS matches the recording timestamp, which links
    clips to runs via the run's date field.
    """
    import re
    clips = []
    if os.path.exists(CLIPS_DIR):
        # Walk run subfolders: clips/run_YYYYMMDD_HHMMSS/
        for run_folder in sorted(os.listdir(CLIPS_DIR), reverse=True):
            run_folder_path = os.path.join(CLIPS_DIR, run_folder)
            if not os.path.isdir(run_folder_path):
                # Legacy flat clip — handle for backwards compat
                if run_folder.endswith(".mp4") and "_4k" not in run_folder:
                    _add_clip_entry(clips, CLIPS_DIR, run_folder, run_folder=None)
                continue
            for f in sorted(os.listdir(run_folder_path)):
                # Skip 4K versions — app uses 1080p
                if f.endswith(".mp4") and "_4k" not in f:
                    _add_clip_entry(clips, run_folder_path, f, run_folder=run_folder)
    return JSONResponse(content={"clips": clips})


def _add_clip_entry(clips: list, folder: str, filename: str, run_folder: str | None = None):
    """Helper to build a clip metadata entry."""
    import re
    filepath = os.path.join(folder, filename)
    size_mb = os.path.getsize(filepath) / (1024 * 1024)

    ts_match = re.match(r'clip_(\d{8}_\d{6})_', filename)
    run_timestamp = ts_match.group(1) if ts_match else None

    clip_type = "highlight"
    if "close_call" in filename:
        clip_type = "close_call"
    else:
        for t in ("pvp_kill", "combat", "kill", "death", "loot", "extraction", "funny", "highlight"):
            if f"_{t}_" in filename:
                clip_type = t
                break

    thumb_name = filename.replace(".mp4", "_thumb.jpg")
    thumb_exists = os.path.exists(os.path.join(folder, thumb_name))

    # For serving, use run_folder/filename path if in subfolder
    serve_path = f"{run_folder}/{filename}" if run_folder else filename
    thumb_serve = f"{run_folder}/{thumb_name}" if run_folder else thumb_name

    clips.append({
        "filename": serve_path,
        "size_mb": round(size_mb, 1),
        "type": clip_type,
        "run_timestamp": run_timestamp,
        "run_folder": run_folder,
        "created": os.path.getmtime(filepath),
        "thumbnail": thumb_serve if thumb_exists else None,
    })


@router.get("/clips/{filepath:path}")
def serve_clip(filepath: str, request: Request):
    """Serve a clip file with HTTP range request support for browser playback.

    Supports both flat (legacy) and subfolder paths: clips/file.mp4 or clips/run_xxx/file.mp4
    """
    from starlette.responses import StreamingResponse

    full_path = os.path.join(CLIPS_DIR, filepath)
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail="Clip not found")

    file_size = os.path.getsize(full_path)
    range_header = request.headers.get("range")

    if range_header:
        range_spec = range_header.replace("bytes=", "")
        parts = range_spec.split("-")
        start = int(parts[0]) if parts[0] else 0
        end = int(parts[1]) if parts[1] else file_size - 1
        end = min(end, file_size - 1)
        content_length = end - start + 1

        def iterfile():
            with open(full_path, "rb") as f:
                f.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk = f.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            iterfile(),
            status_code=206,
            media_type="video/mp4",
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(content_length),
            },
        )

    from fastapi.responses import FileResponse
    return FileResponse(full_path, media_type="video/mp4")


class RecordingAction(BaseModel):
    filename: str
    run_id: int | None = None


@router.post("/recording/keep")
def keep_recording(body: RecordingAction):
    """Mark a recording to be kept. Moves to saved folder and links to run."""
    filename = body.filename
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")

    filepath = os.path.join(RECORDINGS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Recording not found")

    # Move full recording into the run's clips subfolder
    # Filename format: run_YYYYMMDD_HHMMSS.mp4 -> clips/run_YYYYMMDD_HHMMSS/
    run_tag = filename.replace(".mp4", "")
    run_folder = os.path.join(CLIPS_DIR, run_tag)
    os.makedirs(run_folder, exist_ok=True)
    saved_path = os.path.join(run_folder, filename)

    import shutil
    shutil.move(filepath, saved_path)

    # Also move thumbnail if it exists
    thumb = filename.replace(".mp4", "_thumb.jpg")
    thumb_path = os.path.join(RECORDINGS_DIR, thumb)
    if os.path.exists(thumb_path):
        shutil.move(thumb_path, os.path.join(run_folder, thumb))

    # Store recording path on the run record
    if body.run_id:
        from ..database import SessionLocal
        from ..models import Run
        db = SessionLocal()
        try:
            run = db.query(Run).filter(Run.id == body.run_id).first()
            if run:
                run.recording_path = saved_path
                db.commit()
        finally:
            db.close()

    # Remove from processing queue UI
    if _engine:
        _engine.remove_processing_item(filename)

    return JSONResponse(content={"status": "kept", "path": saved_path})


@router.post("/recording/delete")
def delete_recording(body: RecordingAction):
    """Delete a recording permanently."""
    filename = body.filename
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")

    filepath = os.path.join(RECORDINGS_DIR, filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    # Also remove thumbnail
    thumb = filename.replace(".mp4", "_thumb.jpg")
    thumb_path = os.path.join(RECORDINGS_DIR, thumb)
    if os.path.exists(thumb_path):
        os.remove(thumb_path)

    # Remove from processing queue UI
    if _engine:
        _engine.remove_processing_item(filename)

    return JSONResponse(content={"status": "deleted"})


@router.post("/recording/retry")
def retry_recording(body: RecordingAction):
    """Retry processing a failed recording by removing error markers."""
    filename = body.filename
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")

    filepath = os.path.join(RECORDINGS_DIR, filename)

    # Remove all processing markers so it gets re-queued
    for ext in ('.done', '.p1done', '.encoded', '.endgame'):
        marker = filepath + ext
        if os.path.exists(marker):
            os.remove(marker)

    # Reset status in processing queue
    if _engine:
        _engine.reset_processing_item(filename)

    return JSONResponse(content={"status": "retrying"})


@router.post("/open-folder")
def open_run_folder(body: dict):
    """Open a run's clips folder in the system file explorer."""
    import subprocess
    folder = body.get("folder")
    if folder:
        folder_path = os.path.join(CLIPS_DIR, folder)
    else:
        folder_path = CLIPS_DIR

    if not os.path.isdir(folder_path):
        os.makedirs(folder_path, exist_ok=True)

    # Open in Windows Explorer
    subprocess.Popen(['explorer', folder_path.replace('/', '\\')])
    return JSONResponse(content={"status": "opened", "path": folder_path})

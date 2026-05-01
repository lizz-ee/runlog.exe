"""
REST endpoints for the AutoCapture engine.

Mounted at /api/capture by the API router.
Provides start/stop/status/frame endpoints for the singleton capture engine.
"""

import os
import subprocess

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel

from ..capture import AutoCapture
from ..config import _STORAGE_DIR

router = APIRouter()

# -- Module-level singleton --------------------------------------------

_engine: AutoCapture | None = None

# Large media files (recordings, clips) use the configurable storage path.
# This defaults to AppData but can be set to any directory (e.g. D:\RunLog)
# via the "storage_path" setting in settings.json.
RECORDINGS_DIR = os.path.join(_STORAGE_DIR, "recordings")
CLIPS_DIR = os.path.join(_STORAGE_DIR, "clips")

# TTL cache for clip list — avoids hundreds of filesystem syscalls per request
import time as _time
_clips_cache: dict = {"data": None, "ts": 0}
_CLIPS_CACHE_TTL = 10  # seconds


def invalidate_clips_cache():
    """Call after any clip creation, deletion, or keep operation."""
    _clips_cache["data"] = None
    _clips_cache["ts"] = 0


def _safe_path(base_dir: str, user_path: str) -> str:
    """Resolve user_path under base_dir, rejecting traversal attempts."""
    from pathlib import Path
    base = Path(base_dir).resolve()
    resolved = (base / user_path).resolve()
    if not str(resolved).startswith(str(base) + os.sep) and resolved != base:
        raise HTTPException(status_code=400, detail="Invalid path")
    return str(resolved)


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
    """Create and start the AutoCapture engine (singleton). Restarts recorder if no window found."""
    global _engine
    if _engine is None:
        _engine = AutoCapture(
            recordings_dir=RECORDINGS_DIR,
            clips_dir=CLIPS_DIR,
        )
    status = _engine.start()
    # If recorder is running but has no window, restart it to re-search
    if _engine._running and not _engine._recorder.window_name and _engine._recorder.is_running:
        _engine._recorder.stop()
        _engine._recorder.start()
        if _engine._recorder.window_name:
            print(f"[capture] Recorder re-found window: {_engine._recorder.window_name}")
            status = _engine.get_status()
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
        from ..api.settings_api import get_config_value
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
            "capture_error": None,
            "last_result": None,
            "auto_p1": get_config_value("auto_p1") if get_config_value("auto_p1") is not None else True,
            "auto_p2": get_config_value("auto_p2") if get_config_value("auto_p2") is not None else True,
            "pause_processing_while_game_running": get_config_value("pause_processing_while_game_running") if get_config_value("pause_processing_while_game_running") is not None else True,
            "processing_paused_for_game": False,
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


@router.get("/thumbnail/{filename:path}")
def serve_thumbnail(filename: str):
    """Serve a recording thumbnail image from the run's clips folder."""
    from fastapi.responses import FileResponse
    # Thumbnails live next to the recording: clips/run_xxx/run_xxx_thumb.jpg
    run_tag = os.path.basename(filename).replace("_thumb.jpg", "")
    thumb_path = _safe_path(CLIPS_DIR, os.path.join(run_tag, os.path.basename(filename)))
    if os.path.exists(thumb_path):
        return FileResponse(thumb_path, media_type="image/jpeg")
    # Fallback: direct path in clips dir
    clips_path = _safe_path(CLIPS_DIR, filename)
    if os.path.exists(clips_path):
        return FileResponse(clips_path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Thumbnail not found")


@router.get("/clips")
def list_clips():
    """List all highlight clips with metadata.

    Filename format: clip_YYYYMMDD_HHMMSS_type_N.mp4
    The YYYYMMDD_HHMMSS matches the recording timestamp, which links
    clips to runs via the run's date field.
    """
    # Return cached result if fresh
    if _clips_cache["data"] is not None and (_time.time() - _clips_cache["ts"]) < _CLIPS_CACHE_TTL:
        return JSONResponse(content={"clips": _clips_cache["data"]})

    import re
    clips = []
    if os.path.exists(CLIPS_DIR):
        # Walk run subfolders: clips/run_YYYYMMDD_HHMMSS/
        for run_folder in sorted(os.listdir(CLIPS_DIR), reverse=True):
            run_folder_path = os.path.join(CLIPS_DIR, run_folder)
            if not os.path.isdir(run_folder_path):
                # Legacy flat clip — handle for backwards compat
                if run_folder.startswith("clip_") and run_folder.endswith(".mp4") and "_4k" not in run_folder:
                    _add_clip_entry(clips, CLIPS_DIR, run_folder, run_folder=None)
                continue
            for f in sorted(os.listdir(run_folder_path)):
                # Only list true clips (clip_*.mp4); exclude the full run recording (run_*.mp4) and 4K variants.
                if f.startswith("clip_") and f.endswith(".mp4") and "_4k" not in f:
                    _add_clip_entry(clips, run_folder_path, f, run_folder=run_folder)
    _clips_cache["data"] = clips
    _clips_cache["ts"] = _time.time()
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
        known_types = ("pvp_kill", "combat", "kill", "death", "loot", "extraction", "funny", "highlight", "custom")
        matched = False
        for t in known_types:
            if f"_{t}_" in filename:
                clip_type = t
                matched = True
                break
        # Custom named clips: extract name between timestamp and trailing number
        # e.g., clip_20260320_215004_sick_triple_kill_1.mp4 → "sick triple kill"
        if not matched:
            import re
            name_match = re.match(r'clip_\d{8}_\d{6}_(.+?)_\d+\.mp4', filename.split('/')[-1])
            if name_match:
                clip_type = name_match.group(1).replace('_', ' ')

    thumb_name = filename.replace(".mp4", "_thumb.jpg")
    thumb_exists = os.path.exists(os.path.join(folder, thumb_name))

    sprite_name = filename.replace(".mp4", "_sprite.jpg")
    sprite_exists = os.path.exists(os.path.join(folder, sprite_name))

    # Get sprite grid dimensions from sidecar metadata (no ffprobe needed)
    sprite_cols, sprite_rows, sprite_frames = None, None, None
    if sprite_exists:
        import json as _json
        import math
        sprite_meta_path = filepath.replace(".mp4", "_sprite.json")
        try:
            with open(sprite_meta_path) as mf:
                meta = _json.load(mf)
            sprite_cols = meta["cols"]
            sprite_rows = meta["rows"]
            sprite_frames = meta["frames"]
        except (FileNotFoundError, KeyError, ValueError, _json.JSONDecodeError):
            # Fallback: generate sidecar from ffprobe (one-time migration)
            try:
                probe = subprocess.run(
                    ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', filepath],
                    capture_output=True, text=True, timeout=5
                )
                dur = float(probe.stdout.strip())
                sprite_frames = min(300, max(30, int(dur * 3)))
                sprite_cols = min(10, sprite_frames)
                sprite_rows = math.ceil(sprite_frames / sprite_cols)
                # Write sidecar so we don't ffprobe again
                try:
                    with open(sprite_meta_path, "w") as mf:
                        _json.dump({"cols": sprite_cols, "rows": sprite_rows, "frames": sprite_frames}, mf)
                except Exception:
                    pass
            except Exception:
                pass

    # For serving, use run_folder/filename path if in subfolder
    serve_path = f"{run_folder}/{filename}" if run_folder else filename
    thumb_serve = f"{run_folder}/{thumb_name}" if run_folder else thumb_name
    sprite_serve = f"{run_folder}/{sprite_name}" if run_folder else sprite_name

    clips.append({
        "filename": serve_path,
        "size_mb": round(size_mb, 1),
        "type": clip_type,
        "run_timestamp": run_timestamp,
        "run_folder": run_folder,
        "created": os.path.getmtime(filepath),
        "thumbnail": thumb_serve if thumb_exists else None,
        "sprite": sprite_serve if sprite_exists else None,
        "sprite_cols": sprite_cols,
        "sprite_rows": sprite_rows,
        "sprite_frames": sprite_frames,
    })


@router.get("/clips/{filepath:path}")
def serve_clip(filepath: str, request: Request):
    """Serve a clip file with HTTP range request support for browser playback.

    Supports both flat (legacy) and subfolder paths: clips/file.mp4 or clips/run_xxx/file.mp4
    """
    from starlette.responses import StreamingResponse

    full_path = _safe_path(CLIPS_DIR, filepath)
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
        if start > end or start < 0:
            raise HTTPException(status_code=416, detail="Invalid range")
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
    """Mark a recording to be kept (already in clips folder — just links to run)."""
    filename = body.filename
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")

    run_tag = filename.replace(".mp4", "")
    filepath = os.path.join(CLIPS_DIR, run_tag, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Recording not found")

    # Store recording path on the run record
    if body.run_id:
        from ..database import SessionLocal
        from ..models import Run
        db = SessionLocal()
        try:
            run = db.query(Run).filter(Run.id == body.run_id).first()
            if run:
                run.recording_path = filepath
                db.commit()
        finally:
            db.close()

    # Remove from processing queue UI
    if _engine:
        _engine.remove_processing_item(filename)

    invalidate_clips_cache()
    return JSONResponse(content={"status": "kept", "path": filepath})


@router.post("/recording/delete")
def delete_recording(body: RecordingAction):
    """Delete a recording permanently."""
    filename = body.filename
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")

    import shutil
    run_tag = filename.replace(".mp4", "")
    run_dir = os.path.join(CLIPS_DIR, run_tag)

    # Remove the entire run folder (recording, screenshots, clips, markers)
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir, ignore_errors=True)

    # Remove from processing queue UI
    if _engine:
        _engine.remove_processing_item(filename)

    return JSONResponse(content={"status": "deleted"})


@router.post("/recording/retry")
def retry_recording(body: RecordingAction):
    """Retry a failed recording. Resumes from where it left off (skips Phase 1 if already done)."""
    filename = body.filename
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")
    if _engine:
        success = _engine.retry_processing(filename)
        if success:
            return JSONResponse(content={"status": "retrying"})
    raise HTTPException(status_code=400, detail="Could not retry")


@router.post("/recording/dismiss")
def dismiss_recording(body: RecordingAction):
    """Remove an item from the processing queue without running any processing."""
    filename = body.filename
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")
    if _engine:
        _engine.dismiss_item(filename)
    return JSONResponse(content={"status": "dismissed"})


@router.post("/recording/dismiss-failed")
def dismiss_all_failed():
    """Remove all failed/error items from the processing queue."""
    if _engine:
        _engine.dismiss_all_failed()
    return JSONResponse(content={"status": "dismissed"})


class AutoPhaseUpdate(BaseModel):
    phase: int   # 1 or 2
    enabled: bool


@router.post("/auto-phase")
def set_auto_phase(body: AutoPhaseUpdate):
    """Enable or disable auto-run for Phase 1 or Phase 2."""
    if body.phase not in (1, 2):
        raise HTTPException(status_code=400, detail="phase must be 1 or 2")
    if _engine:
        _engine.set_auto_phase(body.phase, body.enabled)
    return JSONResponse(content={"status": "ok", "phase": body.phase, "enabled": body.enabled})


@router.post("/open-folder")
def open_run_folder(body: dict):
    """Open a run's clips folder in the system file explorer."""
    import subprocess
    folder = body.get("folder")
    if folder:
        folder_path = _safe_path(CLIPS_DIR, folder)
    else:
        folder_path = CLIPS_DIR

    if not os.path.isdir(folder_path):
        os.makedirs(folder_path, exist_ok=True)

    # Open in Windows Explorer
    subprocess.Popen(['explorer', folder_path.replace('/', '\\')])
    return JSONResponse(content={"status": "opened", "path": folder_path})


@router.get("/folder-size/{folder}")
def get_folder_size(folder: str):
    """Get the total size of a run's clips folder in MB."""
    folder_path = _safe_path(CLIPS_DIR, folder)
    if not os.path.isdir(folder_path):
        return JSONResponse(content={"size_mb": 0})
    total = sum(
        os.path.getsize(os.path.join(dirpath, f))
        for dirpath, _, filenames in os.walk(folder_path)
        for f in filenames
    )
    return JSONResponse(content={"size_mb": round(total / (1024 * 1024), 1)})


@router.post("/clip/delete")
def delete_clip(body: dict):
    """Delete a single clip file and its thumbnail."""
    filename = body.get("filename")
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")

    filepath = _safe_path(CLIPS_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Clip not found")

    os.remove(filepath)

    # Also remove thumbnail, sprite, and any related assets
    for suffix in ("_thumb.jpg", "_sprite.jpg"):
        asset_path = filepath.replace(".mp4", suffix)
        if os.path.exists(asset_path):
            os.remove(asset_path)

    invalidate_clips_cache()
    return JSONResponse(content={"status": "deleted", "filename": filename})


@router.post("/recording/delete-kept")
def delete_kept_recording(body: dict):
    """Delete a kept full recording and clear recording_path on the run."""
    run_id = body.get("run_id")
    if not run_id:
        raise HTTPException(status_code=400, detail="run_id required")

    from ..database import SessionLocal
    from ..models import Run
    db = SessionLocal()
    try:
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if not run.recording_path:
            raise HTTPException(status_code=404, detail="No recording to delete")

        recording_path = run.recording_path

        # Delete mp4, thumbnail, and sprite sheet
        if os.path.exists(recording_path):
            os.remove(recording_path)
        for suffix in ("_thumb.jpg", "_sprite.jpg"):
            asset_path = recording_path.replace(".mp4", suffix)
            if os.path.exists(asset_path):
                os.remove(asset_path)

        # Clear recording_path on the run
        run.recording_path = None
        db.commit()
    finally:
        db.close()

    invalidate_clips_cache()
    return JSONResponse(content={"status": "deleted", "run_id": run_id})


class ClipCutRequest(BaseModel):
    source: str
    in_point: float
    out_point: float
    name: str = "custom"


@router.post("/clip/cut")
def cut_custom_clip(body: ClipCutRequest):
    """Create a custom clip from a video using IN/OUT points. Stream copy, no re-encode."""
    import re

    if body.in_point < 0:
        raise HTTPException(status_code=400, detail="IN point must be >= 0")
    if body.out_point <= body.in_point:
        raise HTTPException(status_code=400, detail="OUT point must be after IN point")
    if body.out_point > 86400:
        raise HTTPException(status_code=400, detail="OUT point exceeds maximum (24h)")
    duration = body.out_point - body.in_point
    if duration < 1.0:
        raise HTTPException(status_code=400, detail="Clip must be at least 1 second")

    source_path = _safe_path(CLIPS_DIR, body.source)
    if not os.path.exists(source_path):
        raise HTTPException(status_code=404, detail="Source video not found")

    source_dir = os.path.dirname(source_path)
    source_name = os.path.basename(body.source)

    # Extract run timestamp from source filename or folder name
    ts_match = re.search(r'(\d{8}_\d{6})', source_name)
    if not ts_match:
        folder_name = os.path.basename(source_dir)
        ts_match = re.search(r'(\d{8}_\d{6})', folder_name)
    from datetime import datetime
    tag = ts_match.group(1) if ts_match else datetime.now().strftime('%Y%m%d_%H%M%S')

    # Sanitize name for filename
    safe_name = re.sub(r'[^a-z0-9_]', '', body.name.lower().replace(' ', '_').replace('-', '_'))
    if not safe_name:
        safe_name = "custom"

    # Avoid filename collisions
    idx = 1
    while True:
        filename = f"clip_{tag}_{safe_name}_{idx}.mp4"
        clip_path = os.path.join(source_dir, filename)
        if not os.path.exists(clip_path):
            break
        idx += 1

    # Stream copy cut
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
        '-ss', str(body.in_point),
        '-i', source_path,
        '-t', str(duration),
        '-c:v', 'copy', '-an',
        '-movflags', '+faststart',
        clip_path,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"ffmpeg failed: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="ffmpeg timed out")

    if not os.path.exists(clip_path) or os.path.getsize(clip_path) == 0:
        raise HTTPException(status_code=500, detail="Clip file is empty or missing")

    # Generate thumbnail at 50% of clip
    thumb_path = clip_path.replace(".mp4", "_thumb.jpg")
    mid = duration * 0.5
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
             '-ss', str(mid), '-i', clip_path,
             '-vframes', '1', '-vf', 'scale=384:-1',
             '-q:v', '5', thumb_path],
            capture_output=True, timeout=15,
        )
    except Exception:
        pass

    # Generate sprite sheet
    from ..video_processor import _generate_sprite_sheet
    _generate_sprite_sheet(clip_path, duration)

    # Build serve path
    run_folder = os.path.basename(source_dir)
    serve_path = f"{run_folder}/{filename}"

    size_mb = os.path.getsize(clip_path) / (1024 * 1024)
    print(f"[clip/cut] Custom clip: {filename} ({duration:.1f}s, {size_mb:.1f}MB)")
    invalidate_clips_cache()

    return JSONResponse(content={
        "status": "created",
        "filename": serve_path,
        "duration": round(duration, 1),
        "name": body.name,
    })

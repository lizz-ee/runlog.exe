"""Server-Sent Events endpoint for real-time capture status updates."""

import asyncio
import json
import threading
import time

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

router = APIRouter()

# Global event bus — capture system pushes events here, SSE streams them to clients
_listeners: list[asyncio.Queue] = []
_listeners_lock = threading.Lock()


def broadcast(event_type: str, data: dict):
    """Push an event to all connected SSE clients. Call from any thread."""
    message = {"type": event_type, "data": data, "ts": time.time()}
    stale = []
    with _listeners_lock:
        for q in _listeners:
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                stale.append(q)
        for q in stale:
            try:
                _listeners.remove(q)
            except ValueError:
                pass


async def _event_stream():
    """Generator that yields SSE-formatted events."""
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    with _listeners_lock:
        _listeners.append(q)
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=15.0)
                yield f"event: {event['type']}\ndata: {json.dumps(event['data'])}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive comment to prevent connection timeout
                yield ": keepalive\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        with _listeners_lock:
            try:
                _listeners.remove(q)
            except ValueError:
                pass


@router.get("/events")
async def sse_events():
    """SSE endpoint — streams capture status, detection, and processing events."""
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

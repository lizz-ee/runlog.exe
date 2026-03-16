"""
CaptureEngine — threaded screen capture using PyAV with ddagrab + NVENC.

Captures the desktop at 60 fps via DirectX Desktop Duplication (ddagrab),
encodes to 1920x1080 H.264 via NVIDIA hardware encoder (h264_nvenc), and
stores encoded packets in a ring buffer for instant clip saving.  One
full-resolution BGRA frame per second is kept aside for OCR / detection.
"""

import av
import io
import os
import time
import threading
from collections import deque
from fractions import Fraction
from datetime import datetime

from PIL import Image


class CaptureEngine:
    """Threaded screen capture with ring-buffered H.264 encoding."""

    def __init__(
        self,
        fps: int = 60,
        buffer_seconds: int = 180,
        clips_dir: str | None = None,
    ):
        self.fps = fps
        self.buffer_seconds = buffer_seconds

        # Clips output directory — default to cwd/clips
        if clips_dir is None:
            clips_dir = os.path.join(os.getcwd(), "clips")
        self.clips_dir = os.path.abspath(clips_dir)
        os.makedirs(self.clips_dir, exist_ok=True)

        # Ring buffer for encoded packets
        self._buffer: deque = deque(maxlen=fps * buffer_seconds)
        self._lock = threading.Lock()

        # Latest full-res BGRA frame (for OCR), kept as raw bytes + size
        self._latest_frame: bytes | None = None
        self._latest_frame_size: tuple[int, int] | None = None  # (width, height)

        # Codec extradata needed to initialise the MP4 muxer on save
        self._extradata: bytes | None = None

        # Capture dimensions (populated once capture starts)
        self.capture_width: int = 0
        self.capture_height: int = 0
        self.encode_width: int = 1920
        self.encode_height: int = 1080

        # State
        self._thread: threading.Thread | None = None
        self._running = False
        self._actual_fps: float = 0.0

    # ── public API ────────────────────────────────────────────────────

    def start(self) -> dict:
        """Start the capture thread.  Returns current status dict."""
        if self._running:
            return self.get_status()

        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        return self.get_status()

    def stop(self) -> dict:
        """Signal the capture thread to stop and wait for it."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        return self.get_status()

    def get_status(self) -> dict:
        with self._lock:
            buf_packets = len(self._buffer)
            buf_bytes = sum(len(data) for data, _key in self._buffer)
        return {
            "active": self._running,
            "fps": self._actual_fps,
            "buffer_seconds": self.buffer_seconds,
            "buffer_packets": buf_packets,
            "buffer_mb": round(buf_bytes / (1024 * 1024), 2),
            "width": self.capture_width,
            "height": self.capture_height,
        }

    def get_latest_frame_jpeg(self) -> bytes | None:
        """Return the most recent full-res frame as JPEG bytes, or None."""
        with self._lock:
            raw = self._latest_frame
            size = self._latest_frame_size
        if raw is None or size is None:
            return None
        try:
            import numpy as np
            # raw is BGRA bytes with possible row padding
            w, h = size
            arr = np.frombuffer(raw, dtype=np.uint8)
            # Handle stride: row size might be > w*4
            stride = len(raw) // h
            if stride > w * 4:
                arr = arr.reshape(h, stride)[:, :w*4].reshape(h, w, 4)
            else:
                arr = arr.reshape(h, w, 4)
            # BGRA → RGB
            rgb = arr[:, :, [2, 1, 0]]
            img = Image.fromarray(rgb)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return buf.getvalue()
        except Exception as e:
            print(f"[capture] Frame JPEG error: {e}")
            return None

    def save_clip(
        self,
        seconds_before: float = 20,
        seconds_after: float = 5,
        metadata: dict | None = None,
    ) -> dict:
        """
        Save a clip from the ring buffer.

        *seconds_before*  — how many seconds of history to include.
        *seconds_after*   — keep capturing for this many additional seconds.
        *metadata*        — optional dict written into the filename.

        Returns dict with path, filename, duration, size_mb.
        """
        if not self._running:
            raise RuntimeError("Capture engine is not running")

        # Wait for the "after" portion to accumulate
        if seconds_after > 0:
            time.sleep(seconds_after)

        # Snapshot the buffer under lock
        with self._lock:
            packets = list(self._buffer)
            extradata = self._extradata

        if not packets or extradata is None:
            raise RuntimeError("No packets in buffer")

        # Determine how many packets correspond to the requested window
        total_requested = seconds_before + seconds_after
        max_packets = int(total_requested * self.fps)
        # Take the tail of the buffer (most recent packets)
        clip_packets = packets[-max_packets:] if len(packets) > max_packets else packets

        # Find the first keyframe so the clip starts cleanly.
        # Buffer stores (data_bytes, is_keyframe) tuples.
        start_idx = 0
        for i, (data, is_key) in enumerate(clip_packets):
            if is_key:
                start_idx = i
                break
        clip_packets = clip_packets[start_idx:]

        if not clip_packets:
            raise RuntimeError("No keyframe found in clip range")

        # Build filename
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        event_tag = ""
        if metadata and "event" in metadata:
            event_tag = f"_{metadata['event']}"
        filename = f"clip_{ts}{event_tag}.mp4"
        filepath = os.path.join(self.clips_dir, filename)

        # Mux packets into an MP4 container
        output = av.open(filepath, mode="w")
        out_stream = output.add_stream("h264", rate=self.fps)
        out_stream.width = self.encode_width
        out_stream.height = self.encode_height
        out_stream.codec_context.extradata = extradata

        for idx, (data, _is_key) in enumerate(clip_packets):
            pkt = av.Packet(data)
            pkt.stream = out_stream
            pkt.pts = idx
            pkt.dts = idx
            pkt.time_base = Fraction(1, self.fps)
            output.mux(pkt)

        output.close()

        size_bytes = os.path.getsize(filepath)
        duration = len(clip_packets) / self.fps

        return {
            "path": filepath,
            "filename": filename,
            "duration": round(duration, 2),
            "size_mb": round(size_bytes / (1024 * 1024), 2),
        }

    # ── capture thread ────────────────────────────────────────────────

    def _capture_loop(self) -> None:
        """Main capture loop — runs in a dedicated thread."""
        try:
            self._capture_loop_inner()
        except Exception as exc:
            # Ensure flag is cleared so status reflects reality
            self._running = False
            raise

    def _capture_loop_inner(self) -> None:
        # Open ddagrab input (DirectX Desktop Duplication)
        inp = av.open(
            "desktop",
            format="gdigrab",
            options={
                "framerate": str(self.fps),
                "video_size": "3840x2160",
                "offset_x": "0",
                "offset_y": "0",
            },
        )
        in_stream = inp.streams.video[0]
        self.capture_width = in_stream.width
        self.capture_height = in_stream.height

        # Set up the hardware encoder
        codec = av.CodecContext.create("h264_nvenc", "w")
        codec.width = self.encode_width
        codec.height = self.encode_height
        codec.pix_fmt = "yuv420p"
        codec.time_base = Fraction(1, self.fps)
        codec.framerate = Fraction(self.fps, 1)
        codec.options = {
            "preset": "p4",
            "tune": "ll",
            "cq": "23",
        }
        # Global header flag — required for MP4 muxing with extradata
        codec.flags = codec.flags | 0x00400000
        codec.open()

        last_ocr_time = 0.0
        frame_count = 0
        fps_timer = time.monotonic()

        try:
            for frame in inp.decode(video=0):
                if not self._running:
                    break

                # Keep one full-res BGRA frame per second for OCR
                now = time.monotonic()
                if now - last_ocr_time >= 1.0:
                    last_ocr_time = now
                    bgra_frame = frame.reformat(
                        width=self.capture_width,
                        height=self.capture_height,
                        format="bgra",
                    )
                    with self._lock:
                        self._latest_frame = bytes(bgra_frame.planes[0])
                        self._latest_frame_size = (
                            bgra_frame.width,
                            bgra_frame.height,
                        )

                # Reformat to encode resolution + pixel format
                enc_frame = frame.reformat(
                    width=self.encode_width,
                    height=self.encode_height,
                    format="yuv420p",
                )
                enc_frame.pts = frame_count
                frame_count += 1

                # Encode
                for pkt in codec.encode(enc_frame):
                    # Stash extradata from the codec (needed for muxing)
                    if self._extradata is None and codec.extradata:
                        self._extradata = bytes(codec.extradata)

                    is_key = pkt.is_keyframe
                    data = bytes(pkt)
                    with self._lock:
                        self._buffer.append((data, is_key))

                # Update measured FPS once per second
                elapsed = now - fps_timer
                if elapsed >= 1.0:
                    self._actual_fps = round(frame_count / elapsed, 1)
                    frame_count = 0
                    fps_timer = now

        finally:
            # Flush encoder
            for pkt in codec.encode():
                data = bytes(pkt)
                is_key = pkt.is_keyframe
                with self._lock:
                    self._buffer.append((data, is_key))
            codec.close()
            inp.close()
            self._running = False

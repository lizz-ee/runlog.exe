"""
cli_registry.py — tracks live Claude CLI subprocesses so an in-flight upload can
be aborted the instant a match starts.

In claude/hybrid mode, Phase 1/2 hand frames to the Claude CLI, which uploads
them. The processing gate already blocks *new* work during a match, but a job
already mid-upload when the player deploys keeps streaming and contends with the
game's ping. A network upload can't be deprioritized (it's I/O, not CPU) or
safely suspended (the parent's timeout keeps ticking), so the only correct move
is to kill it and re-queue the run.

Re-queue is safe because Phase 1/2 are idempotent via the `.p1done`/`.encoded`
markers: a P1 killed mid-flight never wrote `.p1done`, so it re-runs cleanly;
a P2 killed mid-flight re-holds and regenerates its (deterministically-named)
clips. The capture engine decides requeue-vs-fail from its own `_recording` flag.
"""

import os
import subprocess
import threading

_lock = threading.Lock()
_live = set()  # live subprocess.Popen handles for Claude CLI calls


def register(proc) -> None:
    """Track a freshly-spawned CLI subprocess."""
    if proc is None:
        return
    with _lock:
        _live.add(proc)


def unregister(proc) -> None:
    """Stop tracking a CLI subprocess (call in finally, success or failure)."""
    with _lock:
        _live.discard(proc)


def abort_all() -> int:
    """Terminate every live CLI subprocess. Returns how many were signalled.

    Called when a match starts. The killed call raises in its worker thread,
    which the capture engine turns into a re-queue (not a permanent failure)
    because `_recording` is set."""
    with _lock:
        procs = list(_live)
    signalled = 0
    for p in procs:
        try:
            if p.poll() is None:
                if os.name == "nt":
                    # The CLI can spawn a worker child. Terminating only the
                    # registered wrapper may orphan that child and leave an
                    # upload running through gameplay.
                    subprocess.run(
                        ["taskkill", "/PID", str(p.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                        check=False,
                    )
                else:
                    p.terminate()
                signalled += 1
        except Exception:
            pass
    return signalled

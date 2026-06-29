# Plan — CLI-path payload shrink + in-flight CLI abort

Investigation + design for the two remaining higher-risk items from the
2026-06-29 capture sweep. **Nothing here is implemented** — this is the
"plan before building" step. Each part ends with a recommendation and the
risks that must be checked on a live deploy.

Context: `processor_mode` ∈ {`alpha` (local, no network), `hybrid` (local-first +
Claude fallback), `claude` (network only)}. Only `claude`/`hybrid` upload.

---

## Part 1 — CLI-path upload payload shrink

### What the API-path fix (shipped, `bdeb96f`) did and didn't cover
`run_api_prompt` now downscales images to 1568px before base64 (`_encode_image_for_api`).
That covers the **API key** path. The **CLI** path is different: the Claude CLI
reads image files **itself** from disk via `--add-dir <dir>` (the prompt lists
paths and says "use your Read tool to view each"). We never base64 them, so we
can't intercept at upload — the lever is *what's on disk*.

### What the CLI reads (two categories)
1. **Extracted video frames** — `extract_key_frames` (`video_processor.py:421`)
   writes `start_*.jpg` / `end_*.jpg` into `frames_dir` at **native** width
   (`_frame_resolution`, `FRAME_RESOLUTION_MAX = 3840`, `video_processor.py:76/97`).
   `FRAME_FPS_END = 5` → the post-match flood ("hundreds of 4K frames") lives here.
   **These files exist only for analysis** — nothing else reads them.
2. **Full-res screenshots** — `deploy/readyup/run/deploying.jpg` (+ `_crop`) saved
   by the recorder, read by `_analyze_with_screenshots` (`video_processor.py:522`).
   **Also displayed in the UI / kept on disk**, so they can't be shrunk in place.

### Recommended approach
**1A (do this — clean, safe, big win):** cap the *extracted frame* resolution at
1568px. The frames are analysis-only, already JPG, and the API downscales past
1568 anyway → **quality-neutral**, and it directly attacks the "hundreds of frames"
flood that dominates CLI upload.
- Change: `FRAME_RESOLUTION_MAX = 3840` → `1600` (or add `min(native, 1568)` in
  `_frame_resolution`). The `scale={res}:-2` filter (`video_processor.py:438,454`)
  already caps width and preserves aspect, so this is essentially a one-constant edit.
- With the recording default now 1440p (2560px), this drops extracted frames
  2560→1568 wide ≈ **2.6× fewer pixels** per frame, on top of fewer-bytes JPG.
- Risk to check: the end-frame pass reads the PROGRESS/LOADOUT REPORT tabs at
  `fps=5`. 1568px is plenty for tab text, but **confirm Phase-1 stat accuracy on a
  real run** before trusting it (it's the one place detail matters). The deploy/
  spawn-coord reading uses the full-res *screenshots*, not these frames, so coords
  are unaffected.

**1B (optional, more work):** shrink the handful of full-res screenshots for the
CLI by writing 1568px copies into a temp dir and pointing `--add-dir` + the prompt
at those. Low payoff (screenshots are few vs the frame flood) and adds temp-file
plumbing — **defer** unless 1A proves insufficient.

**1C (real — replace, don't delete):** `run_api_prompt(video_path=…)` is the
**Phase-2 narrative API path** (`video_processor.py:1528` and `2276`), used CLI-first
/ API-fallback (`analyze_video_phase2:1538`). It base64-encodes the **entire mp4
inline** (`ai_client.py:367-372`) — hundreds of MB to ~GB on the wire for a
multi-minute run, even at 1440p — and it's slow/expensive regardless of ping.
- Fix: **replace whole-video upload with sampled frames** — reuse `extract_key_frames`
  (or a sparse Phase-2 sample) + the already-downscaled `_encode_image_for_api(images=…)`,
  mirroring how the CLI Phase-2 path samples frames instead of sending the file.
  This also makes the API and CLI Phase-2 paths consistent. Effort S–M.
- Note: Phase-2 normally runs post-game (gated), so the in-*match* exposure is the
  in-flight case (Part 2); but the GB payload hurts cost/latency on every API-mode run.

### Verdict
**1A is SHIPPED** (`FRAME_RESOLUTION_MAX = 1568`) — the 80% of the CLI-path win for
one constant. Validate Phase-1 stat accuracy on one real run. 1B/1C remain.

---

## Part 2 — In-flight CLI abort (the residual network P0)

### Why deprioritization (the ffmpeg trick) won't work here
For in-flight ffmpeg we drop the child to IDLE+EcoQoS (shipped, `1f50918`) — CPU
contention solved, the decode still finishes. A CLI **upload** is **I/O/network**-
bound, not CPU — lowering its priority does nothing for bandwidth/ping. And we
can't *suspend* it: the parent `subprocess.run/communicate(timeout=…)` clock keeps
ticking and would kill it anyway (and a frozen TCP upload risks a server-side
timeout). **The only correct move is: abort it and re-queue the run.**

### Why a clean abort is feasible here
The pipeline is already built for idempotent re-runs:
- `_process_phase1` skips if `<file>.p1done` exists (`capture.py:1298-1301`); a P1
  killed mid-flight never wrote `.p1done` → it re-runs cleanly.
- `.encoded` guards re-encode (`capture.py:904`); markers are cleaned on
  finalize/dismiss (`capture.py:1205,1112`).
- Re-queue = `self._process_queue.put(filepath)` (`capture.py:916,1229,1252`); the
  dispatcher re-gates it (`capture.py:1262-1280`).
So "kill + put back on the queue" is safe **for P1**. P2 needs a check (below).

### Design
1. **Subprocess registry** (new, thread-safe) — a set of live CLI `Popen` handles.
   `run_cli_prompt` (`ai_client.py:258`) and `_run_claude_cli` (`video_processor.py`)
   register on spawn, unregister in `finally`. Tag each with `(run_id, phase)`.
2. **Abort hook** — in `_start_recording` (right where `1f50918` backgrounds
   ffmpeg, `capture.py:~792`), call `abort_inflight_cli()`: `terminate()` then
   `kill()` every registered CLI, and set an "aborted-for-match" flag/return so the
   worker distinguishes abort from a real failure.
3. **Re-queue on abort** — the P1/P2 task wraps the CLI call; on the aborted result
   it **re-queues** `filepath` (don't write `.p1done`, don't mark `error`) so it
   resumes **after** the match, when the gate reopens. Scope to `claude`/`hybrid`.
4. **Gate already covers new work** — `_processing_gate_active` (with the shipped
   `claude`-P1 gate) blocks *new* dispatch during a match; this only handles the
   one job already in flight when the match started.

### Risks to resolve before/while building
- **P2 partial outputs.** A P2 killed mid-clip-generation may leave partial
  clips/JSON. Confirm P2 re-run **overwrites** cleanly (clip filenames are
  deterministic — `clip_<tag>_<type>_<i>.mp4`, so likely yes) or add a cleanup on
  re-entry. P1 is clean (atomic JSON + `.p1done` only on success).
- **Abort vs genuine failure.** Must not mark an aborted run as permanently failed
  (`phase1_failed`, `capture.py:1028`). Thread an explicit "aborted" signal, not a
  generic exception.
- **Registry hygiene.** Unregister in `finally` even on exception; guard against a
  PID/handle reused after exit (operate on the `Popen` object, not a bare PID).
- **Hybrid nuance.** Hybrid P1 is local-first; only abort it once it has actually
  escalated to a CLI call (i.e. only registered Popens get aborted — naturally
  handled by the registry).
- **Effort:** M. Touches `ai_client.py` (registry + register/unregister),
  `video_processor.py` (`_run_claude_cli` register), `capture.py` (abort hook +
  task-level re-queue-on-abort). All Windows-testable only on a live run.

### Verdict
Worth doing for `claude`/`hybrid` users on online play (it's the real residual
ping risk), but it's a **multi-file change on the live processing path** — build
behind the registry abstraction, land it in one focused PR, and validate with a
real "process a backlog, then deploy" sequence before trusting the re-queue.

---

## Suggested order
1. ~~**1A** (frame-res cap)~~ — **SHIPPED** (`FRAME_RESOLUTION_MAX = 1568`); validate stat accuracy on one run.
2. **1C** (replace the Phase-2 whole-mp4 API upload with sampled frames) — kills a GB-scale payload.
3. **Part 2** (in-flight CLI abort) — the meatier one; do it as its own change with the
   backlog→deploy validation.
4. **1B** (screenshot copies) — only if 1A isn't enough.

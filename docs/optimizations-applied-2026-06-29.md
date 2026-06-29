# Optimizations applied — 2026-06-29

Implementation log for the changes made off the back of the capture-architecture
sweep. Companion to:
- `audit-2026-06-29-capture-architecture-sweep.md` (main 41-agent audit)
- `audit-2026-06-29-followup-addendum.md` (recovered R4/R18/R19 + audio/disk/network tenants)

All changes are on `main`. Each was verified to compile (`cargo check`, `py_compile`).
**Nothing here has been validated on real hardware yet** — see "Needs live testing".

---

## Shipped

### 1. Recording defaults: 4K60 @ 50 Mbps → 1440p30 @ 20 Mbps
- **Files:** `backend/app/api/settings_api.py` (`DEFAULTS`, the authoritative source),
  `backend/app/capture.py` (`_start_recording` fallbacks kept in sync).
- **Why:** The single biggest game-shared GPU cost is the per-frame MediaFoundation
  BGRA→NV12 convert/scale, which runs on the shared 3D/compute engine (not the encode
  ASIC) and scales with resolution × fps. 1440p30 cuts that ~4.5× vs native 4K60, and
  also cuts NVENC load, live disk write, and all post-run decode/sprite/analyst work.
- **Note:** The audit's "flip `main.rs:572 unwrap_or(60)`" was the *wrong* location — the
  effective defaults live in `settings_api.py:DEFAULTS` (`get_config_value` falls back to
  it). The Rust `unwrap_or` is a never-hit fallback.
- **Reversible:** Fully — SYS.CONFIG → REC.CONFIG (encoder/bitrate/fps/resolution).

### 2. Coalesce the per-frame encode-error `emit()`  *(quick-win #1, highest-confidence)*
- **File:** `backend/recorder/src/main.rs` (new `encode_errors` field; encode match arms).
- **Why:** When the encoder is persistently failing, the old code called `emit()` (locks +
  flushes stdout) on **every** frame from inside the WGC capture callback — a 30–60/sec
  stdout storm on the capture hot path. Now only the first error of a failure run is sent
  to Python, with a throttled stderr heartbeat every 300 frames.

### 3. `ocr_fast` reset on stop  *(recovered R19 — confirmed 4× idle-IPC waste)*
- **File:** `backend/app/capture.py` (`_stop_recording`).
- **Why:** `set_ocr_fast(True)` at RUN_COMPLETE was never reset; Rust only auto-clears it at
  the next encoder start. Between runs the recorder shipped a full preview frame every
  ~0.5s instead of ~2s — exactly 4× the idle encode/base64/IPC. One line: `set_ocr_fast(False)`.

### 4. Background QoS (E-core / EcoQoS) for processing  *(Task: CPU affinity)*
- **Files:** new `backend/app/perf.py`; `backend/app/capture.py` (executor `initializer=`,
  live OCR + frame-relay threads).
- **Why:** Nothing pinned background work off the game's P-cores. `perf.set_thread_eco_qos()`
  marks the live OCR/relay threads and every P1/P2 pool thread as EcoQoS + below-normal, so
  the heavy torch/OCR/cv2 work rides E-cores and yields to the game. Below-normal is
  self-regulating: full speed when the game is closed, steps aside when it's running. Safe
  no-op on non-hybrid CPUs / non-Windows.
- `perf.BG_CREATIONFLAGS` and `apply_eco_qos_to_pid()` are provided for ffmpeg children but
  **not yet wired** (see Deferred).

### 5. claude-mode P1 network gate + `window_name` lifecycle fix  *(addendum P0)*
- **Files:** `backend/app/capture.py` (`_processing_gate_active`, cached `_processor_mode`),
  `backend/app/rust_recorder.py` (`stop()` resets `window_name`).
- **Why:** P1 was *never* gated by the game window ("P1 is light, it uses screenshots") — true
  for alpha, **false in claude mode where P1 is network uploads** that bleed across the deploy
  boundary and contend with the live match's ping. Now claude-mode P1 is held under the same
  game-impact guard as P2. **Scoped to pure `claude`** — default `alpha` and local-first
  `hybrid` are untouched (zero behavior change for the default user). Reversible via the
  `pause_processing_while_game_running` guard.
- The `window_name` reset makes that guard honest: a stopped recorder no longer leaves a
  stale window name that would keep heavy processing blocked after the game closed.

### 6. Misc correctness
- Renamed `set_high_priority` → `configure_process_priority` (it only ever set NORMAL +
  disabled throttling) and added a real `ABOVE_NORMAL` bump on the WGC capture/pump thread.
- Raised OCR/preview JPEG quality 85 → 95 (cheaper-than-shared-memory path to better winocr
  accuracy on small HUD text; override via `RUNLOG_OCR_QUALITY`).
- Fixed the stale "H.264" comment in `video_processor.py` (recorder defaults to HEVC).

### 7. New tool — PresentMon/ETW frame-time harness  *(the measurement gate)*
- **Files:** `backend/tools/frametime_harness.py`, `backend/tools/README.md`.
- **Why:** The audit's recurring caveat was that "zero game-frame impact" is asserted, not
  measured. This drives Intel PresentMon to report present-mode (Independent Flip vs Composed)
  and frame-time percentiles, with a guided A/B `compare` mode to prove a change moved — or
  didn't move — Marathon's frame pacing. Observation-only; touches no app process.

### 8. Audio privacy — Marathon-only loopback  *(addendum tenant; UNTESTED here)*
- **Files:** new `backend/app/wasapi_loopback.py`; `backend/app/audio_sidecar.py`.
- **Why:** The sidecar used `soundcard`'s default-speaker loopback, which records **all** system
  audio (Discord, music, notifications) and permanently muxes it into every clip — a real
  privacy/quality bug, not just perf. New `wasapi_loopback.py` does Windows per-process loopback
  (`ActivateAudioInterfaceAsync` + `AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK` via ctypes)
  keyed to Marathon's PID, so only the game's audio is captured.
- **Fail-soft:** all COM init happens before the WAV is opened; on *any* failure (older Windows,
  no device, init error) it falls back to the previous whole-system loopback — recording never
  regresses. The addendum's "move audio into the Rust recorder" alternative was **not** taken:
  `TODO.md` documents the `windows-capture` audio path blocks, and process loopback in the Python
  sidecar gets the privacy win without that risk.
- **Validated here:** struct ABI sizes/offsets (WAVEFORMATEX=18, PROPVARIANT=24), GUID parsing,
  the COM completion-handler vtable, process enumeration. **NOT validated:** the actual capture
  (needs Marathon running + an audio device) — confirm a clip's audio is game-only on your box.

---

### 9. In-flight decoder backgrounding + HDD storage warning  *(in-flight P0 + disk tenant)*
- **Files:** `backend/app/perf.py` (`background_inflight_decoders`, `set_pid_background`,
  `_iter_child_pids`, `storage_incurs_seek_penalty`); `backend/app/capture.py`
  (`_start_recording` hook, `_storage_warning` + `get_status`).
- **In-flight:** when a match starts, any in-flight ffmpeg/ffprobe children (a prior run's
  decode that overlapped from a lobby gap) are dropped to **IDLE priority + EcoQoS** so they
  yield to the game. Deliberately **not** suspended — a frozen child would let the parent
  `subprocess.run(timeout=…)` clock fire and fail the job. New heavy work is already
  gate-blocked during a match, so this one hook covers the whole overlap case without
  touching the ~13 ffmpeg spawn sites.
- **Disk:** `storage_incurs_seek_penalty()` (IOCTL_STORAGE_QUERY_PROPERTY) flags recordings on
  a spinning HDD at startup → logs a warning + `status.storage_warning` for the UI. The
  classic same-spindle-as-the-game stutter cause. *(Probe returned `None`/inconclusive on the
  dev box — validate on a real HDD; it never false-warns.)*

### 10. Bounded recorder worker channel  *(R19 half 2 — memory safety)*
- **File:** `backend/recorder/src/main.rs`.
- **Why:** The OCR/encode worker used an unbounded `mpsc` channel; a stalled Python reader would
  back up the OS pipe, block the worker on flush, and grow the queue without limit. Now a bounded
  `sync_channel(16)` + `try_send` sheds stale preview/region jobs (drop-oldest) — never grows
  unbounded, never blocks the capture callback. 16 is never near full in normal operation (the
  worker drains in ms); drops only happen under a reader stall, where a missed periodic OCR tick
  is harmless.

---

## Deferred (designed, not shipped — higher risk / needs your live-deploy testing)

Per the "minimal live fixes" rule, these were intentionally **not** scattered onto the live
path blind:

- **True in-flight *abort*** of a running **claude CLI upload** on match-start (the in-flight
  ffmpeg case is now handled by priority-lowering, #9). Network uploads can't just be
  deprioritized — they need SIGTERM + idempotent re-queue (the `.p1done`/`.encoded` markers
  make re-queue safe). The gate already prevents *new* claude work during a match.
- **ffmpeg-child below-normal priority at spawn** — wire `perf.BG_CREATIONFLAGS` into the ~13
  ffmpeg spawn sites. Mostly redundant now for game-impact (the overlap case is covered by #9);
  only affects post-game processing priority.
- **Recorder write I/O priority on detected HDD** (`PROCESS_MODE_BACKGROUND_BEGIN` / low
  I/O-priority byte-stream) — the write-side companion to the #9 HDD *warning*.
- **R4 — OCR-light in-run detection** (move kill-feed OCR to Phase 2; gate endgame/center
  winocr behind the cheap ImageStat check). Watch the ~3s→~15s worst-case RUN_COMPLETE
  detection-latency caveat; tune `ocr.py:91-95` thresholds first.
- **Audio (optional future):** process-specific loopback is now shipped (#8 above). Still open:
  moving audio into the Rust recorder for sample-accurate A/V sync + Python-thread removal
  (blocked on the `windows-capture` audio path — confirm the original disable reason first).
- **Upload payload shrink** (downscale frames to ~1280–1920px long edge; retire the
  base64-whole-video API path) — real bandwidth/ping win in claude mode, but intertwined with
  the CLI-agent extraction path (`video_processor.py:1411-1428`); needs investigation + live test.

---

## Needs live testing
1. **Run the harness** (`frametime_harness.py compare`) baseline vs watching vs recording vs
   recording+overlay — this is how you confirm the defaults change and QoS actually help and
   that the overlay's flip-mode demotion is/are real.
2. **Confirm 1440p30 @ 20 Mbps** clip quality is acceptable for highlights (trivially bumped
   back in SYS.CONFIG if not).
3. **Rebuild the recorder binary** is required for the Rust changes (#2, #6) to take effect —
   `cargo build --release` (electron-builder bundles `target/release/runlog-recorder.exe`).
4. **claude-mode users:** verify stats still generate after the game closes (the gate defers
   claude P1 while the game window is open by design).

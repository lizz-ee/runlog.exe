<!-- Generated 2026-06-29 by follow-up workflow wf_feec1f6a-ab1: recovered the 3 lost recs (R4/R18/R19) + audited the 3 uncovered in-match tenants (audio, disk I/O, network). Companion to audit-2026-06-29-capture-architecture-sweep.md -->

# ADDENDUM â€” runlog.exe Capture-Architecture Audit

## PART A â€” Recovered recommendations (R4 / R18 / R19)

All three recovered and re-verified against source. None dropped; two revised down from their original framing.

### R4 â€” Make in-run state detection OCR-light (move kill-feed OCR to post-run; gate endgame/center winocr behind the cheap visual check)
- **Problem:** During active combat the staged ~3s tick fires ~3 winocr calls (~16ms each): kill-feed, the endgame banner, and an ENDGAME_CENTER fallback that runs every tick even though the visual `_looks_like_run_complete` ImageStat check already short-circuits when a banner is present (capture.py:429-430, ocr.py:133/136/143).
- **Proposal:** Delete the live `_scan_kill_feed`; OCR the kill-feed region from the full-res frames Phase 2 already extracts (better fidelity). In-run, run only the near-free ImageStat check each tick; gate the banner winocr behind it and relocate ENDGAME_CENTER to the existing every-5th-cycle cadence. Steady-state in-combat OCR ~3 â†’ ~0 winocr/tick.
- **Verified impact:** Premise confirmed exactly; code does none of the three optimizations today. **But** this runs on the BELOW_NORMAL Python worker at a 3s cadence, so absolute savings are ~32-48ms bursty per 3s (~1-1.6% of one core) â€” real but small. The value is killing micro-contention with the CPU-saturated game core, **not** "the bulk of in-game CPU" as originally claimed. Kill-feedâ†’Phase-2 move is clean and improves accuracy.
- **Caveat:** Gating the confirming banner OCR behind the brightness/green heuristic (ocr.py:91-95) means a RUN_COMPLETE whose colors fall outside thresholds isn't confirmed until the 5th-cycle fallback â€” worst-case detection latency ~3s â†’ ~15s. The fallback mitigates but does not eliminate this; tune thresholds before shipping.
- **Effort:** M Â· **Priority:** P1 Â· **Verdict:** REVISE (keep, but sell it as contention/accuracy, not CPU; validate the latency caveat).

### R18 â€” Make screenshot/frame_now readback async + reuse a persistent staging texture
- **Problem:** `read_frame_raw â†’ frame.buffer()` does CreateTexture2D + CopyResource + Map synchronously and allocates a fresh ~33MB full-res staging texture per call on the capture/message-pump thread (main.rs:417-429; windows-capture 1.5.0 frame.rs:195-249). `_get_fresh_frame` fires at deploy/endgame/stats transitions during recording.
- **Proposal:** Route screenshots/frame_now through the existing double-buffered staging path (or a dedicated persistent full-res staging texture), reading the prior-tick completed copy; reuse the texture across calls instead of per-call allocation.
- **Verified impact:** Premise confirmed; async double-buffered StagingPool already exists (main.rs:206-373) but is deliberately **not** applied to one-shot reads (screenshot main.rs:545, frame_now main.rs:558). Impact is **LOW** â€” the project intentionally confines `read_frame_raw` to loading/stats/endgame screens (comment main.rs:414-416) where the GPU is light, so the stall almost never overlaps live combat. Only thin edges land near gameplay (deploy_3 ~4s post-deploy capture.py:660; endgame frame_now at RUN_COMPLETE capture.py:680). The durable win is the per-call texture-allocation reuse (small cleanup), not stall removal.
- **Effort:** M Â· **Priority:** P3 Â· **Verdict:** REVISE (weak â€” keep only the cheap texture-reuse cleanup; the async re-route is M effort for marginal real-world benefit. Defer unless touched anyway).

### R19 â€” Bound/coalesce the worker job channel + reset `ocr_fast` on `_stop_recording`
- **Problem:** (1) `queue_job` uses an unbounded mpsc channel (main.rs:849, 714-718) with no drop-oldest/coalesce â€” a stalled Python reader fills the OS pipe, blocks the worker on flush (emit, main.rs:140-151), and the queue grows unbounded. (2) `set_ocr_fast(True)` at RUN_COMPLETE (capture.py:675) is never reset by Python on stop; Rust clears it only at the next encoder start (main.rs:610), so between runs it ships a full-frame JPEG every ~0.5s instead of ~2s.
- **Proposal:** Bounded `sync_channel` (or `Mutex<Option<latest>>` for Frames jobs) with drop-oldest/coalesce so a stalled reader sheds stale preview/region jobs; keep `SaveScreenshot` on a reliable separate path. Add `self._recorder.set_ocr_fast(False)` to `_stop_recording`.
- **Verified impact:** Both claims confirmed. With `FULL_FRAME_EVERY_MENU_TICKS=4` (main.rs:45), the stuck `ocr_fast` forces `want_full` every tick = full-frame JPEG every ~0.5s vs ~2s = **exactly the claimed 4Ã—** encode/base64/IPC, persisting through all between-run menus until the next deploy. The `ocr_fast` fix is a trivial 1-line, zero-downside win (low stakes â€” between runs, not combat). The channel bound is a genuine memory-safety guard against unbounded growth.
- **Effort:** S Â· **Priority:** P2 Â· **Verdict:** KEEP (strongest of the three; do both, the 1-liner immediately).

---

## PART B â€” Uncovered in-match tenants

Ordered by real hot-path risk: **network first**, then disk-I/O, then audio.

### 1. Network â€” THE real in-match contention vector (`runsDuringMatch: conditional`, confirmed `gameImpact: yes`)
Egress is only via `ai_client` (Claude CLI subprocess or anthropic SDK); kill-feed OCR, frame relay, SSE, screenshot saves are all local. The problem is the **game-impact gate is submission-time only**:
- `_processing_gate_active` / `_heavy_processing_blocked_by_game` (capture.py ~1029-1044) are checked only at dispatch. Once a prompt is handed to `ai_client`, the upload is never re-checked or interrupted. **Concrete sequence:** match A ends â†’ P1 for A dispatches in lobby (allowed) â†’ its parallel CLI calls + 20-frame Call-2 batches start uploading â†’ player deploys into match B â†’ `_recording=True` blocks only *new* submissions; **A's in-flight 4K uploads stream throughout live match B.**
- P1 is deliberately ungated against an open game window ("P1 is light, it uses screenshots") â€” **false in claude/hybrid mode**, where P1 *is* network (`_analyze_with_screenshots`, video_processor.py ~522-797). So prior-run uploads run freely during lobby/matchmaking and bleed across the deploy boundary.
- No bandwidth cap anywhere; `MAX_P1_WORKERS=4`, each spawning a 3-worker pool â†’ many concurrent CLI subprocesses streaming 4K JPEGs at uncapped parallel speed.
- Worst payloads: Phase-2 CLI analyst uploads hundreds of 4K frames across a run; the API fallback (`run_api_prompt(video_path=)`, ai_client.py ~367-373) base64-encodes the **entire** mp4 inline (~3GB RAM+wire for a 10-min 4K run). The API path is normally a fallback and P2 is window-gated, but an in-flight continuation can still overlap.
- `recorder.window_name` is set once on 'ready' and never cleared (rust_recorder.py ~257), so the guard is sticky (over-blocks after game close) **and** has an under-block hole before first 'ready'.

**Real game impact:** uncapped parallel uplink contends with matchmaking/queue ping and in-match traffic â€” the only confirmed `gameImpact: yes` tenant. **Mitigations:** treat all network as heavy â€” gate claude/hybrid P1 like P2 (**P0**); make the gate cover in-flight work via a `should_pause` callable at every network boundary, abort+re-queue on recording-start (**P0**); throttle to concurrency 1 (or 0 for network modes) while Marathon is open (**P1**); fix `window_name` lifecycle with a window-lost event + live-process fallback (**P2**); downscale frames (cap long edge ~1280-1920px) and retire the base64-whole-video path (**P2**).

### 2. Disk-I/O â€” drive-dependent; the classic same-spindle stutter (`runsDuringMatch: yes`)
Continuous in-match writers: HEVC stream (~3.75 MB/s at default 30 Mbps, written directly into the run folder, no I/O-priority handling â€” main.rs:594), audio WAV (~192 KB/s, a second independent handle), tiny kill-feed `.events` (open/append/close every ~3s), and bursty transition-only screenshots. Heavy DB + ffmpeg work is correctly gated out of the match (`_processing_gate_active` while `_recording`; SQLite WAL + synchronous=NORMAL).
- **SSD/NVMe:** total ~4 MB/s vs >500 MB/s / >100k IOPS budget = <1%; sequential writes barely perturb random game reads. **Effectively zero impact.**
- **HDD (7200rpm, ~80-150 random IOPS):** the bytes aren't the problem â€” **seek interleave** is. Write-back flushes yank the head to the recording region (~10-15ms/seek), blocking the game's random asset reads â†’ texture/streaming hitches. Two+ growing files (video+audio+events) widen seek spread. Default storage is `%APPDATA%` = C: = often the same physical drive as the game, and STOR.CONFIG never warns about same-drive placement (only validates the dir is creatable).
- **CPU-priority calls exist but none touch I/O priority** â€” MF SinkWriter threads write at default Normal I/O, competing on equal footing with game reads.

**Real game impact:** none on SSD; real stutter on HDD shared with the game. **Mitigations:** detect & warn when `storage_path` shares a physical disk with the game, plus UI guidance (**P1**, highest-leverage/lowest-risk); offer relocation to a second drive at onboarding via existing `/migrate-storage` (**P2**); lower recorder write I/O priority on HDD via `PROCESS_MODE_BACKGROUND_BEGIN`/END or a self-opened `IoPriorityHintLow` byte-stream, gated to detected-HDD (**P2**, must validate no encoder frame-drops); buffer audio WAV + in-memory kill-feed `.events` flushed at stop to cut HDD seek thrash (**P3**).

### 3. Audio â€” runs the whole match, but low game cost (`runsDuringMatch: yes`, `gameImpact: maybe/no`)
Audio is **not** in the Rust encoder (`AudioSettingsBuilder::default().disabled(true)`, main.rs:599). It's a separate Python `audio-sidecar` daemon thread doing WASAPI default-speaker loopback via `soundcard`, writing PCM16 WAV in 0.5s chunks for the full match (capture.py:768-770 â†’ 805), muxed into the MP4 at Phase 2.
- **CPU:** near-zero (OS mixes audio; `record()` releases the GIL) â€” but `soundcard`'s poll loop wakes ~100Ã—/s, churning the single GIL against the OCR loop. Whole process is BELOW_NORMAL so it can't preempt the game.
- **Other issues (quality/privacy, not hitches):** no A/V sync alignment (variable 100-500ms startup offset + uncorrected WGC-vs-WASAPI drift over a 20-min match â€” video_processor.py:368-416, no `-itsoffset`); **privacy regression** â€” default-speaker loopback records *all* system audio (Discord, music, notifications) and muxes it permanently into the MP4, unlike the carefully window-scoped video; buffer-overflow/dropout risk under load; lazy device enumeration at the exact match-start moment.

**Real game impact:** low â€” GIL micro-contention at worst. Bigger issues are A/V sync and privacy. **Mitigations:** move audio into the Rust recorder (flip `disabled(false)`) â€” deletes the Python thread + mux pass and gives sample-accurate sync for free; confirm why it was disabled first (**P2**); pair with process-specific loopback (`AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK` keyed to Marathon's PID) to match the video's privacy stance (**P2**); if staying in Python, ring-buffer raw frames in-match and convert/write post-match + pre-warm device enumeration on window-detect (**P3**); surface the `audio_capture` toggle in SYS.CONFIG (**P3**).

---

## Net new action items (deduped, prioritized)

- **P0 â€” Cover in-flight network work in the game gate.** Re-check the gate at every network boundary (`should_pause` callable into `_analyze_with_screenshots` / Call-2 / Phase-2 loops); abort+re-queue (or kill tracked subprocesses) on recording-start. Closes the only confirmed in-match contention vector.
- **P0 â€” Gate claude/hybrid Phase 1 as network/heavy.** Stop returning `False` for `p1` when `processor_mode` is claude/hybrid; gate on the game-window guard too. Keep the fast ungated path for alpha (local) mode only.
- **P1 â€” Warn on same-physical-drive storage_path** in STOR.CONFIG + status payload, with HDD-stutter guidance. Highest-leverage disk fix.
- **P1 â€” Throttle P1/P2 concurrency to 1 (0 for network modes) while Marathon is open;** add an upload rate cap.
- **P1 â€” R4:** Move kill-feed OCR to Phase 2 (full-res) and gate the endgame/center winocr behind the ImageStat check; validate the ~3sâ†’~15s worst-case latency caveat / tune ocr.py:91-95 thresholds before shipping.
- **P2 â€” R19:** Reset `ocr_fast(False)` in `_stop_recording` (trivial 1-liner, do now) **and** bound/coalesce the worker job channel with drop-oldest, keeping `SaveScreenshot` reliable.
- **P2 â€” Fix `recorder.window_name` lifecycle:** emit window-lost/closed, reset to `None`, add live-process fallback. Removes sticky over-block + pre-'ready' under-block hole.
- **P2 â€” Move audio into the Rust recorder** (enable MF audio) for sample-accurate sync + thread removal; pair with **process-specific loopback** for privacy parity with the window-scoped video. Confirm original disable reason first.
- **P2 â€” Lower recorder write I/O priority on detected HDD** (BACKGROUND_BEGIN/END or `IoPriorityHintLow` byte-stream); validate no encoder frame-drops. Offer second-drive relocation at onboarding.
- **P2 â€” Shrink upload payloads:** downscale frames to ~1280-1920px long edge, hard-cap Call-2 frame count, retire the base64-whole-video Phase-2 API path.
- **P3 â€” R18:** Keep only the per-call staging-texture reuse cleanup; defer the async one-shot re-route (marginal real-world benefit).
- **P3 â€” Cheaper second-stream writes:** buffer audio WAV into larger flushes and hold kill-feed `.events` in memory, flush at stop (HDD seek-thrash reduction).
- **P3 â€” Stamp `RecordingStarted` with a QPC/monotonic timestamp** and apply `-itsoffset` at mux (only if the Rust-audio move is rejected).

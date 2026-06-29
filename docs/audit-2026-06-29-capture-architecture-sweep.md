<!-- Generated 2026-06-29 by a 41-agent architecture+research sweep (workflow wf_eff5a22a-15f). Adversarially verified. 4 agents failed structured-output: 1 research briefing (8/9) + 3 recommendation verdicts (R4/R18/R19) lost. -->

# runlog.exe â€” Capture Architecture & Optimization Sweep

## 1. Executive Summary

**The hot path is already best-in-class â€” preserve it.** runlog's live capture/encode loop reflects deliberate, correct zero-impact engineering, and both the internal audit and external research agree it needs no fundamental redesign:

- **Zero-copy GPU â†’ hardware encoder.** WGC frame surfaces are handed straight to MediaFoundation's hardware encoder via `send_frame` (`main.rs:641`), with `ColorFormat::Bgra8` matched to the encoder's registered input (`main.rs:990` â†” `encoder.rs:527`) â€” no intermediate CPU copy on the encode path.
- **Native rate-capping** through `MinimumUpdateIntervalSettings` (`main.rs:846, 988`) â€” the cap lives in WGC itself, not a software throttle.
- **Async, double-buffered OCR staging** that maps the *prior* tick's completed copy (`main.rs:206-373`), so readback never stalls the capture callback.
- **All JPEG/base64/IPC work offloaded to a `BELOW_NORMAL` worker** (`main.rs:792-808`), with **EcoQoS explicitly disabled** for the recorder (`main.rs:778-786`).
- **Post-run heavy media gated while the game window exists** (`capture.py:1029-1044`).

Research confirms the two big "why not do it like X" questions are already answered correctly: an **OBS-style injected Present hook is rightly rejected** (ban risk against Marathon's kernel anti-cheat), and **MediaFoundation already drives the same NVENC/QSV/AMF ASIC** that makes ShadowPlay "free." There is no encode redesign to chase.

**Where the real game-frame costs actually live.** The audit surfaced the genuine leaks, and verification narrowed them. In priority order:

1. **Heavy post-run jobs aren't preempted** when a new match starts â€” the gate is check-on-submit, never in-flight (significant only in claude/cloud mode or under a backlog).
2. **No CPU affinity / E-core isolation anywhere** â€” the single biggest unused "OBS/ShadowPlay-style" structural lever for keeping background work off the game's P-cores.
3. **The default is 4K @ 60fps**, maximizing the one truly game-shared GPU cost (the MF BGRAâ†’NV12 convert+scale shader pass) and all downstream decode.
4. **An always-on transparent overlay** that continuously recomposites and can demote the game off independent-flip.
5. **A per-frame encode-error `emit()`** (`main.rs:652`) that, when the encoder is already failing, becomes a 60-emit/sec capture-thread storm.

**Headline opportunities** (detailed below): flip the framerate default (the cheapest, highest-leverage single change), add real CPU affinity for background tenants, preempt in-flight jobs, and stand up a PresentMon/ETW harness so "zero game-frame impact" can be *measured* rather than asserted. Everything else is correctness polish and post-run efficiency.

> **Honesty note carried from verification:** several originally-P0/P1 items were downgraded after code review (some claims were false or config-dependent). Priorities below reflect the *revised* verdicts, not the original proposals.

---

## 2. How the Best Do It

| Technique | What it gives you | What runlog does today | The gap |
|---|---|---|---|
| **OBS game-capture hook** (injected Present/IDXGISwapChain hook) | Captures the game's own backbuffer pre-composition; lowest-overhead capture | **WGC window capture** (`WithoutCursor`/`WithoutBorder`, `main.rs:983-992`) â€” *deliberately* no injection | None worth closing â€” an injected hook is a **ban/detection risk** against anti-cheat (EAC/BattlEye/Vanguard-class). Correctly rejected; keep WGC. |
| **ShadowPlay / NVENC** | "Free" encode on dedicated ASIC; never touches the 3D engine | **MediaFoundation HW encode** drives the same NVENC/QSV/AMF ASIC via `SetHardwareAccelerationEnabled(true)` | Encode itself is already on the ASIC. Two soft gaps: no **assertion** that a HW MFT (not SW fallback) was actually selected; and the BGRAâ†’**NV12 convert+scale runs on the shared 3D/compute engine**, not the ASIC â€” so resolution/fps reduction *is* a real in-game GPU lever. |
| **Medal instant-replay** | Always-on RAM ring buffer; saves the last N seconds retroactively | Records the **full match** deployâ†’postgame, then cuts clips retroactively from the complete file using kill-feed `.events` timestamps | **Not a gap** â€” runlog already achieves retroactive clipping by a simpler route. A RAM ring buffer solves a problem runlog doesn't have. **Considered & rejected.** |
| **WGC (Microsoft baseline)** | Compositor-based capture; safe, no injection; borderless-friendly | Exactly this, with native rate-cap + async readback | Best-practice items not yet adopted: **adapter pinning** on hybrid GPUs, **free-threaded pool depth 2-3** to decouple captureâ†”encode, **CopySubresourceRegion** crops, **DirtyRegion ReportOnly** (Win11 24H2). All marginal-to-modest; none are redesigns. |

---

## 3. Prioritized Recommendations

Effort: **S** small / **M** medium / **L** large. "Game frame impact" = does it touch the live match hot path.

### P0 â€” Game frame time first, high confidence

#### â˜… Biggest single lever â€” Default capture+encode framerate 60 â†’ 30fps
*(New; surfaced by the completeness pass. Strictly cheaper and higher-leverage than R5.)*
- **Problem:** Default is 60fps. Every per-frame in-game cost â€” the MF BGRAâ†’NV12 convert+scale (shared 3D/compute engine), NVENC encode, per-frame staging, *and* all post-run decode/sprite/analyst work â€” scales with framerate.
- **Proposal:** Flip the default `fps` from `unwrap_or(60)` to 30 (`main.rs:572-580`; clamp 1-240 and the `RUNLOG_CAPTURE_FPS`/`MinimumUpdateInterval` cap at `main.rs:841-846` are already wired). One-line default change, zero new code. Keep 60 as opt-in.
- **Impact:** Halves the single genuinely game-shared GPU cost (the convert pass) plus encode + post-run decode simultaneously. Combined with R5 (1440p), **4K60 â†’ 1440p30 â‰ˆ 4.5Ã— cut** in the in-game-shared GPU cost. 30fps is defensible for an OCR + clip-review tool (same product caveat as R5).
- **Effort:** S Â· **Risk:** Product decision (lower clip smoothness); trivially reversible.

#### R1 â€” Preempt (suspend or requeue) in-flight P1/P2 the instant a run starts
- **Problem:** The gate only blocks *new* submissions (`capture.py:1029-1044, 1230-1235, 1333-1349`); a job already executing runs straight through the live match. *Verified, but scope-corrected:* worst-case (4K HEVC software decode + up to 3 Claude CLI children per job) only occurs in **claude/cloud mode or an alpha fallback**, and/or under a **backlog** of queued runs. The **default alpha path does no decode** (`skip_frame_extract`, stream-copy clips), and **P2 is capped at 1 worker** â€” so the "up to 4 ffmpeg pipelines" framing does not apply to the default config.
- **Proposal:** Track active subprocess handles; on `self._recording` â†’ true, **`psutil.suspend()` local ffmpeg decode** (clean pause/resume) but **`SIGTERM` + requeue the Claude CLI children** (suspending mid-HTTP-request drops the connection and fails the 180s future timeout, `video_processor.py:683`). Existing `.p1done`/`.encoded` markers make requeue idempotent. Keep the screenshot fast path running (no decode).
- **Cheaper near-equivalent (do this first):** since the heavy path is already gated to non-default modes, simply **lower `MAX_P1_WORKERS`** (`capture.py:45`) and/or **defer sprite-sheet decode while `_recording`** captures most of the benefit at far lower complexity.
- **Impact:** Real safety win for claude-mode/backlog users; marginal in steady-state default alpha.
- **Effort:** M Â· **Risk:** Low (resumable design already exists). Â· **Partially mitigated today** by the submit-time gate.

#### NEW â€” CPU affinity / E-core isolation + EcoQoS for background tenants
*(Surfaced by the completeness pass; arguably higher-impact than R1's suspend machinery.)*
- **Problem:** The only scheduling code is `set_high_priority` (`main.rs:756-785`) = NORMAL class + *disable* power throttling. **There is no core affinity anywhere**, and the heavy Python ffmpeg/torch/OCR workers have no priority, affinity, or QoS. On hybrid P/E-core CPUs this is the highest-value "zero-impact like ShadowPlay" structural lever left unused.
- **Proposal:** Pin all background processing (P1/P2 ffmpeg, torch inference, OCR) to **E-cores and/or apply EcoQoS**, leaving P-cores for the game. Separately, reconsider disabling power throttling *process-wide* on the recorder â€” it's the wrong hammer for the idle/OCR portions on laptops (battery/heat).
- **Impact:** Structurally removes background CPU contention from the game's cores without suspend/gate complexity.
- **Effort:** M Â· **Risk:** Affinity API correctness; verify on non-hybrid CPUs it's a safe no-op.

#### NEW (meta) â€” Add a PresentMon/ETW frame-time harness
- **Problem:** Research repeatedly says "verify via Intel PresentMon" (R3/R6/R12) and verdicts repeatedly downgrade claims as **unverified on real hardware**. There is no instrumentation to ground-truth which changes actually move the game's frame times.
- **Proposal:** Add a PresentMon/ETW capture around a recording session; log the game's present mode (independent-flip vs composed-flip) and frame-time percentiles with/without overlay, with/without recording.
- **Impact:** The enabling change â€” you cannot credibly claim "zero game-frame impact like OBS" without it. Gates the credibility of every other in-game claim.
- **Effort:** M Â· **Risk:** None (measurement only).

### P1 â€” Real but bounded

#### R5 â€” Default capture/encode resolution 4K â†’ 1440p
- **Problem:** Default is native 4K. The encoder is fed uncompressed BGRA8, so MF runs a **per-frame BGRAâ†’NV12 convert (+scale) on the shared 3D/compute engine** for every recorded frame. *Correction the original verdict under-claimed:* this convert is a MediaFoundation VideoProcessor **shader pass on the game's engine, not the dedicated encode ASIC** â€” so res (and fps) reduction is the *one real in-game-GPU lever.*
- **Proposal:** Flip the default preset (`capture.py:750/757`) to `target_height=1440`; the downscale path is already fully wired (`main.rs:586-598`). Keep native opt-in. **OCR crops must still be taken from the native pre-scale surface** so text stays legible.
- **Impact (corrected â€” drop the false claims):** ~2.25Ã— less per-frame convert/scale + NVENC source bandwidth and proportionally cheaper post-run decode/sprite passes. **Does *not*** reduce the OCR staging copy (that copies the native surface) and **does *not* shrink files at fixed 30 Mbps bitrate** â€” lower the default bitrate too if file size matters.
- **Effort:** S Â· **Risk:** Lower clip resolution (product decision); verify aspect/PAR. *Citation fix: encode path is all in `main.rs`, there is no `encoder.rs` in runlog.*

#### R16 â€” Gate Phase 1 ffmpeg *decode* behind the window-open guard
- **Problem:** `_processing_gate_active('p1')` returns False unless `_recording`, so P1 runs while Marathon sits in lobby/menus. The **claude-mode / no-screenshot / FPS-escalation sub-paths** still run ungated 4K ffmpeg extraction (`video_processor.py:2061-2070, 2104-2120`).
- **Proposal:** Extend `_heavy_processing_blocked_by_game` to those decode sub-paths only. **Do *not* "gate the first torch import"** â€” that contradicts the carve-out, because the alpha *fast path itself* imports torch/easyocr and runs CPU inference. For the alpha inference cost, the right lever is **Background-QoS / E-core pinning of P1 workers** (see the affinity rec), *not* hard-deferral (which would starve claude-mode users of stats until they fully quit the game).
- **Impact:** Removes lobby/menu 4K-decode spikes for the minority sub-paths; nil for default alpha (already light).
- **Effort:** S Â· **Risk:** Defers stats in heavy sub-paths until game closes. Â· **Partially done** (fast path already exempt via `skip_frame_extract`).

### P2 â€” Correctness, robustness, and post-run efficiency

#### R2 â€” Stop calling `emit()` from the WGC capture callback (single IPC-writer thread)
- **Problem (downgraded P0â†’P2):** `emit()` locks global stdout and flushes (`main.rs:140-152`) and is called from inside `on_frame_arrived`. *But verification corrected the trigger:* the stdout drain thread is **not** the winocr thread (those are separate, `rust_recorder.py:_read_events` vs `capture.py:361 _ocr_loop`), the pipe buffer is **~4KB** not 64KB, and **in healthy steady-state recording the capture callback emits nothing**. The real hazard is GIL starvation of the drain thread, and it's narrow.
- **Highest-value sub-fix (pull out as a quick win):** **coalesce/suppress the per-frame encode-error `emit()` at `main.rs:652`** â€” when the encoder is already failing it fires 60Ã—/sec on the capture thread. One-spot fix.
- **Proposal:** Route Ready/Start/Stop/Error onto a **dedicated tiny control channel** (not the existing mpsc, which would queue control events behind large `OcrJob` pixel payloads and risk reordering); one writer owns stdout. Clean architecture, but small real-world frame-drop payoff.
- **Effort:** S Â· **Risk:** Minimal; preserve start/stop vs status ordering.

#### R3 â€” HUD overlay: repaint-on-change only
- **Problem (downgraded P0â†’P2):** The transparent `WS_EX_LAYERED` always-on-top overlay with `backgroundThrottling:false` runs a continuous 1.2s CSS pulse for the entire run (`main.js` inlined overlay HTML), forcing a fresh composite every frame.
- **Honest reframe:** killing the pulse does **not** restore independent-flip â€” the game drops to composed-flip the instant a topmost layered window is shown over it (at WATCHING/detection, before recording). The only true iflip fix is *not drawing over the game*, which conflicts with the REC affordance (a product decision, not a free perf win).
- **Proposal:** Replace the pulse with a **static REC dot** (kills continuous unthrottled renders â€” best value, meaningful for laptop battery/heat/long sessions); **size the window to content** (drop the 500px width over a ~250px bar, trivial polish). The event-driven `SetWinEventHook` topmost re-assert is **low value** (the existing 10s timer is cheap and robust) â€” only do it if you keep a slow backstop and accept native-FFI cost.
- **Effort:** M Â· **Risk:** Confirm static dot still reads as "recording." Â· **Lazy creation already done**; main window already keeps `backgroundThrottling` on deliberately. *Verify any flip-model claim with PresentMon.*

#### R9 â€” Decouple encode from the capture callback (free-threaded pool depth 2-3)
- **Problem (downgraded P1â†’P2):** `send_frame` blocks the single pump thread on a condvar until MF pulls the sample (`encoder.rs:971-977`), pool depth is 1 (`graphics_capture_api.rs:204`), all on one pump thread. *Correction:* the **OCR readback is already fully decoupled** â€” only the *video encode* is still synchronous; and a slow WGC handler drops the *recording's* frames, it does **not** stall DWM or the game.
- **Proposal:** `CreateFreeThreaded` pool (count 2-3); push AddRef'd surfaces to a dedicated encode thread via a bounded drop-oldest queue.
- **Impact (reframed):** Prevents dropped frames during **transient** encoder/disk hitches â€” not a steady-state win (capture is rate-capped and NVENC keeps up).
- **Effort:** **L** (re-rated up) Â· **Risk:** **M/H** â€” needs a crate fork; an owned-texture ring to survive surface recycling likely **sacrifices the current zero-copy path**; requires `ID3D11Multithread.Enter`. Real use-after-recycle corruption risk.

#### R17 â€” Post-run efficiency overhaul (hwaccel decode, 1080p proxy, keyframe sprites, I/O priority, mid-job guard)
- **Problem:** No `-hwaccel` / `-threads` anywhere; default codec is **HEVC** (not the stale "H.264" comment at `video_processor.py:1640`), so 4K software HEVC decode is genuinely expensive. ffmpeg children get CPU priority but **no I/O priority**. The P2 guard is dispatch-time only (`capture.py:1374-1428`) â€” a Marathon relaunch does not suspend an in-flight P2.
- **Corrections:** There is **no full-run sprite sheet** (sprites run per â‰¤25s clip, `video_processor.py:1676`). The only true whole-file decode is the **Phase 2 analyst base pass** (`fps=0.25/1`, no `-ss`); P1 end-window uses `-ss` *before* `-i` input-seek; FPS-escalation uses windowed seeks and is fallback-only. So drop the "triple full decode / 4Ã— re-decode" framing.
- **Proposal:** Apply `-hwaccel` (d3d11va/cuda/qsv) + a **single reusable 1080p proxy** for the Phase 2 base pass; keyframe-sampled sprites (`-skip_frame nokey`); **IDLE/I-O priority** on heavy ffmpeg children; cooperative game-guard **re-check inside `_process_phase2`**. **Pick proxy *or* per-pass hwaccel** â€” they're partially redundant (the proxy is itself a full decode+encode pass); don't bill both as additive "several-fold."
- **Caveat:** the heavy Phase 2 decode is emitted via an **LLM-agent prompt** (`video_processor.py:1411-1428`), so hwaccel/proxy there means prompt/restructuring work, not a one-line flag.
- **Effort:** L Â· **Risk:** GPU decode varies by codec/driver (keep CPU fallback); cooperative suspend must resume cleanly.

#### R6 â€” Assert the hardware MFT was actually selected (diagnostic only)
- **Problem (heavily narrowed):** The WinRT `MediaTranscoder` path only *requests* HW accel; it cannot pin an MFT, set rate-control, GOP, or B-frames. *But* the B-frame/low-latency rationale is mostly a **no-op** on real hardware (NVENC defaults to 0 B-frames and doesn't expose the knob; encode latency is irrelevant for a disk recorder whose OCR reads pre-encode pixels).
- **Keep only the cheap kernel (P2/P3):** a standalone startup `MFTEnumEx(MFT_CATEGORY_VIDEO_ENCODER, MFT_ENUM_FLAG_HARDWARE)` probe that logs the HW encoder's friendly name and **warns/degrades if only the stock SW "H264/HEVC Encoder MFT" exists** (SW fallback *does* steal game cores). The full CODECAPI/rate-control/GOP work collapses into the L/XL `IMFSinkWriter` rewrite (not worth it).
- **Effort:** S (probe only) Â· **Risk:** None.

#### R15 â€” Cache one winocr `OcrEngine` + a persistent event loop
- **Problem:** winocr rebuilds an `OcrEngine` **and** a fresh asyncio loop on **every** OCR call (`winocr.py:13,36-37`); Phase 2 makes hundreds of calls per combat-heavy run. *Correction:* the "fresh `ThreadPoolExecutor` per call" claim is **wrong** â€” that branch only runs when a loop is already running, which the Phase 2 sync path is not. The avoidable waste is the **engine** (the loop object is already reused in the `run_until_complete` branch).
- **Proposal:** Create one `OcrEngine` + one persistent loop per process and reuse them. The "decode only needed crops" half is a **marginal nicety**, not a lever.
- **Impact (reframed):** A few seconds on long runs; Phase 2 bottleneck is ffmpeg/cv2/audio, and it runs in the background after the game closes (not user-facing).
- **Effort:** S Â· **Risk:** Marshal all OCR calls onto the one loop thread (WinRT/COM apartment).

### P3 â€” Marginal micro-opts and hygiene (do if cheap)

| Rec | What | Why downgraded |
|---|---|---|
| **R13** | Rename misleading `set_high_priority` (it only sets NORMAL + disables throttling, `main.rs:751-788`) and bump the **capture/pump thread to `ABOVE_NORMAL`** | Rename is a certain correctness win; the bump is **CPU-scheduling insurance only** (does nothing for GPU/NVENC saturation, where `send_frame` blocks on the GPU). **Quick win.** |
| **R10** | Ship OCR crops as raw bitmaps over shared memory | OCR fires at ~2Hz (menus) / ~0.33Hz (recording) on 4 tiny crops off the capture thread â€” JPEG/base64 is **noise**. **Cheap alt first:** bump `RUNLOG_OCR_QUALITY` or send **lossless PNG crops** (one line) to capture any accuracy benefit. The slashed-zero-hack rationale is unsupported by `ocr.py`. |
| **R7** | `CopySubresourceRegion` per-region crops instead of full 33MB `CopyResource` (`main.rs:368`) | A ~1-2ms copy every ~3s on a dedicated async copy engine. Union box is only ~1.8Ã—, not 5Ã—; needs per-region for ~4Ã—. ocr_fast/want_full ticks gain nothing. Adds real complexity to a tuned hot path for negligible gain â€” **defensible to drop entirely**. |
| **R8** | Pin capture device to the GPU rendering Marathon | No-op on single-GPU and normal dGPU-display desktops; **ambiguous/negative on Optimus laptops** (could *add* an iGPUâ†’dGPU copy). Real fix only on rare multi-dGPU. **Drop the `IMFDXGIDeviceManager` step** â€” doesn't exist in this crate's WinRT path; pinning the capture device makes the encoder follow automatically. |
| **R11** | Skip full-frame preview during recording; make it pull-only | Eliminates one ~2-4ms memcpy every ~6s. **Critical:** gate the existing **async** `want_full` extraction on a client-visible flag â€” do **not** reroute preview through `frame_now`, which is a synchronous `frame.buffer()` **GPU stall** (the exact thing the async staging pool avoids). |
| **R14** | Event-driven wakeups + kill the redundant double status fetch | **Keep the Electron fix** (`App.tsx` already receives the status JSON in the IPC payload but throws it away and re-GETs `/api/capture/status` â€” consume `data.message` instead; near-zero risk). **Drop/defer** the Python `Condition`/`Queue` refactor â€” its GIL-contention rationale is wrong and it adds missed-wakeup races. |
| **R12** | Detect FSE/black-frame and guide user to borderless; keep WGC, reject present-hook | Reframe from "perf P1" to **reliability/diagnostic guard**: the present-hook rejection is **already the status quo**, and Win11 Fullscreen Optimizations auto-demote FSE to a capturable flip path. Verify whether Marathon even exposes true exclusive fullscreen before building FSE-specific detection; otherwise keep only a generic black/stale-frame guard. |
| **R20** | Cargo profile (`codegen-units=1`, `panic="abort"`, `strip`, `target-cpu=x86-64-v3`) + pin CPU-only torch/easyocr wheels | Build/dependency hygiene, **not a perf win** â€” the only vectorizable loop runs every 0.5-3s on a background thread. **Drop** the "commit Cargo.lock / build in CI" line (Cargo.lock is already tracked; line 66 is a bundle filter; **no CI exists**) and the VRAM-contention fear (Windows PyPI serves CPU torch by default). Keep flags + CPU pin for binary size and reproducibility. |

---

## 4. Biggest Single Lever + Quick-Wins Shortlist

### â˜… Biggest single lever
**Flip the default framerate 60 â†’ 30fps (`main.rs:572-580`).** One line, zero new code, the mechanism is already wired and clamped. It is the *only* change that halves **every** per-frame in-game cost at once â€” the shared-engine NV12 convert+scale, NVENC encode, per-frame staging, and all post-run decode/sprite/analyst work. **Pair it with R5 (1440p)** for a combined **4K60 â†’ 1440p30 â‰ˆ 4.5Ã— reduction** in the one genuinely game-shared GPU cost. For an OCR + clip-review tool, both are defensible product defaults with full opt-in to native/60.

### Quick-wins shortlist (cheap, high-confidence)
1. **Coalesce the per-frame encode-error `emit()` (`main.rs:652`)** â€” kills a real 60-emit/sec capture-thread storm when the encoder is failing. One spot. *(from R2)*
2. **Framerate default 30** and **resolution default 1440p** â€” two one-line default flips. *(lever + R5)*
3. **Lower default bitrate** (especially alongside fps/res cuts) â€” independently cuts live disk write + post-run decode. Resolution alone won't shrink files at fixed 30 Mbps.
4. **Defer sprite-sheet decode while `_recording`** and/or **lower `MAX_P1_WORKERS`** â€” captures most of R1's benefit at a fraction of the effort.
5. **Bump `RUNLOG_OCR_QUALITY` or send lossless PNG crops** â€” one line; captures essentially all of R10's accuracy upside without the shared-memory ring.
6. **Rename `set_high_priority` + add the `ABOVE_NORMAL` capture-thread bump** *(R13)* â€” a certain correctness/clarity win.
7. **Consume `data.message` in `App.tsx` instead of re-GETting `/api/capture/status`** *(R14)* â€” deletes a run-long duplicate HTTP+JSON+React cycle.
8. **Fix the stale "H.264" comment at `video_processor.py:1640`** â€” the recorder defaults to HEVC.

### Considered & rejected (don't build)
- **RAM ring-buffer instant-replay** â€” runlog already cuts clips retroactively from the full-match file via kill-feed `.events`; a ring buffer solves a problem it doesn't have, and the current WinRT `MediaTranscoder` exposes no encoded `IMFSample`/keyframe control (it'd be a from-scratch raw-MF build).
- **CFR-header vs VFR-timestamp reconciliation** â€” the VFR-safe path (PTS-based `-ss`/`fps=` seeking) is already fully implemented; forcing constant-cadence duplication would only inflate file size.

---

## 5. Honest Caveats / Needs Real-Hardware Measurement

- **Almost every in-game-frame claim is unverified on real hardware.** Research said "verify via PresentMon" for R3, R6, and R12, and verdicts repeatedly flagged the gap. **Stand up the PresentMon/ETW harness (P0-meta) before crediting any frame-time gain**, especially overlay flip-mode and resolution/fps deltas.
- **Independent-flip vs composed-flip is a fundamental tradeoff, not a free win.** Any topmost layered overlay over a borderless game demotes it to composed-flip the moment it's shown. R3 reduces *how much* the overlay recomposites; it does **not** restore independent-flip. Surfacing REC state without drawing over the game is a product decision.
- **Several headline impacts are config-dependent.** R1's worst case (4K HEVC decode + 12 CLI children) only exists in **claude/cloud mode or under a backlog**; the **default alpha path is already light**. R16 and R17 likewise mostly bite non-default modes. Measure your actual `processor_mode` before investing.
- **Hybrid/Optimus laptops behave differently** from the dev's single-GPU desktop. R8 (adapter pinning) can be neutral or *negative* on Optimus; CPU affinity to E-cores needs validation as a safe no-op on non-hybrid CPUs.
- **R9's decoupling likely costs the zero-copy path.** Surviving surface recycling needs an owned-texture ring (an extra full-frame copy/frame) and `ID3D11Multithread` protection â€” net user-visible gain on a tolerant run-review tool may not justify the corruption risk.

### Subsystems this sweep did *not* cover (flagged for a follow-up pass)
- **Live-match audio capture.** The Rust encoder disables audio, yet Phase 2 muxes a `_audio.wav` sidecar â€” *something* runs a WASAPI/loopback capture **during the live match** (21 audio sites in `video_processor.py`). That in-match tenant was never audited.
- **Live disk-write contention.** R17 adds I/O priority only to *post-run* ffmpeg. The live ~30 Mbps HEVC `StorageFile` write â€” possibly on the same drive as the game's asset streaming â€” has no I/O-priority handling.
- **Network contention in claude/cloud mode.** CLI subprocesses make network calls; for an online competitive shooter, in-match upload can affect ping. R1 accounts for their CPU, not network/latency.
- **Process-gap to confirm:** recommendation IDs **R4, R18, R19** are absent from both the verified and dropped lists (the sequence jumps R3â†’R5 and R17â†’R20). Confirm these weren't silently lost without a recorded rationale.

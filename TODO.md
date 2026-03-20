# runlog.exe — TODO

## Completed Features

### Auto-Capture System (Done)
- [x] Rust capture engine (`runlog-recorder.exe`) — zero-copy GPU pipeline, WGC + MediaFoundation H.264
- [x] WGC (Windows Graphics Capture) — privacy-safe, game-window-only, works when alt-tabbed
- [x] 60fps recording at native 4K via hardware encoder (no CPU frame copies)
- [x] OCR-based game state detection — three regions: OCR.DEPLOY (map name → start), OCR.ENDGAME (RUN_COMPLETE → timestamp), OCR.LOBBY (PREPARE → stop, READY_UP → screenshot, SEARCHING → visual)
- [x] No debounce — act on first OCR match (prevents missed detections on fast screen transitions)
- [x] Ready-up screenshot capture (full-screen + loadout crop) for shell/loadout identification
- [x] Deploy screenshot capture for map name and spawn coordinates
- [x] Marathon.exe process detection (recording-manager in Electron)
- [x] System tray notifications for capture events
- [x] Auto-resume unprocessed recordings on startup
- [x] No minimum recording threshold — every DEPLOY-triggered recording is processed

### Video Processing Pipeline (Done)
- [x] Two-phase analysis (Phase 1: fast stats, Phase 2: async narrative + clips)
- [x] Frame extraction — start (90s @ 0.5fps) and end (30s @ 5fps) windows
- [x] Claude Sonnet integration for frame analysis + video analysis
- [x] Spawn coordinate extraction from deployment loading screen
- [x] Iterative spawn search — forward in 45s chunks, no cap, searches entire video
- [x] Iterative stats search — backward in 30s chunks through entire video
- [x] Adaptive fps escalation — 5 → 10 → 15 → 20 → 30fps if Sonnet needs more frames
- [x] Fuzzy spawn point matching (Euclidean distance threshold)
- [x] Grade system (S through F)
- [x] AI narrative summaries (second-person run reports)
- [x] Highlight clip cutting (stream copy, no re-encoding)
- [x] Clip thumbnails auto-generated
- [x] Processing queue with real-time status tracking
- [x] Legacy single-pass fallback pipeline

### Interactive Maps (Done)
- [x] Perimeter map with spawn heatmap
- [x] Dire Marsh map with spawn heatmap
- [x] Outpost map with spawn heatmap
- [x] Draggable spawn markers with coordinate persistence
- [x] Per-spawn tooltips (survival %, streak, loot, weapon/shell favorites, killed-by)
- [x] Spawn sorting (name, survival, loot, streak)
- [x] Per-map stat cards (favorites, economy, combat, time)

### Data Quality (Done)
- [x] Auto-link spawn points to runs (coordinate matching from loading screen)
- [x] Runner/shell auto-creation from video analysis
- [x] Session grouping
- [x] Weapon tracking (primary/secondary per run)
- [x] Damage contributor tracking (who killed you, with what)
- [x] Player gamertag detection

### UI (Done)
- [x] Dashboard with hero stats, favorites, economy, combat, time breakdown
- [x] Run History with pagination, filters (outcome, map), expandable details
- [x] Run Reports with grades, narratives, highlight galleries, inline video player
- [x] Live Capture Monitor with engine status, detection feed, processing queue
- [x] Shells page — cyberpunk HUD cards, sorted by performance, all selectable
- [x] Squad page — top 7 squad mates, per-mate stats, VS overall survival diff
- [x] System tray integration
- [x] Auto-backup (7 rolling SQLite snapshots)
- [x] Settings page (API key config with test/save, setup guide)
- [x] Cyberpunk splash screen with boot sequence
- [x] Consistent cyberpunk aesthetic (// separators, dot notation, RUNLOG.EXE branding)

---

## Remaining TODOs

### Maps
- [ ] Get Cryo Archive map image (currently marked REDACTED)
- [ ] Add Cryo Archive spawn point data as games are played

### Stats & Charts
- [ ] Trends/charts on dashboard (survival rate over time, loot over time)
- [ ] Per-map trends (performance on each map over time)
- [ ] Weapon performance scoring — combined survival rate + K/D + loot per weapon, best/worst weapon per shell and per map

### Processing Queue
- [x] Completed items disappear on app restart — now restores .done recordings to queue with SAVE/DISCARD buttons

### UI Enhancements
- [x] Pipeline pill-shaped segments (Marathon HUD style) — PipelineProgress component with geometric shapes, color-coded stages, animated active state
- [x] Remove "RUN #" from processing queue items — internal detail, not user-facing
- [ ] Export data (CSV/JSON) for runs, stats, spawn data

### Live Page — Processing Stage Visibility
The processing queue currently shows a single status label per item (e.g. "ANALYZING STATS"). With 10 stages across two phases, users need better visibility into where each item is in the pipeline.

**Plan:**
- [x] Add a horizontal stage progress bar to each processing item card — PipelineProgress component with grouped stages, color-coded, animated
- ~~Show elapsed time per item~~ — removed, didn't work well in practice
- [x] Add sub-status text under active stage — detail text now renders left of pipeline shapes
- [x] Show what Phase 1 found vs missed — ✓/✗ MAP, STATS, LOADOUT indicators shown after Phase 1 completes
- [x] Error messages — failed items now show error detail text below "FAILED" label (with hover for full text)

### Live Page — Queue Overview Header
The QUEUE status card currently jams all active stage counts into one text line ("2 ANALYZING STATS | 1 SAVING | 3 QUEUED") which overflows and is hard to scan.

**Status:** Redesigned — pill-based summary with TOTAL/DONE/FAILED counts. Pipeline overview with stage nodes below.
- [x] Replace the single QUEUE card with pipeline overview strip
- [x] Add total items count + completed/failed summary
- ~~Keep ENGINE, RECORDING, DURATION as separate cards~~ — not needed
- ~~Clicking a stage node to filter queue~~ — not needed

### Capture Improvements
- [x] Unified OCR scan region — three regions: DEPLOY, ENDGAME, LOBBY
- [x] Debug overlay on detection feed — shows OCR scan boxes with colored scanlines
- [x] Instant queue appearance — recording shows in processing queue immediately
- [x] OCR Detection System — DEPLOY (map name → start), ENDGAME (RUN_COMPLETE → timestamp), LOBBY (READY_UP → screenshot, PREPARE → stop, SEARCHING → visual)
- [x] Per-run screenshot storage — readyup.jpg, readyup_loadout.jpg, deploy.jpg per run
- [x] Shell detection via facial geometry + reference images (high thinking Sonnet)
- [x] Loadout crop for item tier/value extraction
- [x] No debounce — removed to prevent missed detections
- [x] No minimum recording threshold — removed since DEPLOY trigger is reliable
- [x] Rust capture engine — zero-copy GPU recording, replaced Python WGC+NVENC
- [x] Removed ddagrab fallback (privacy concern — captured full display)
- [x] OCR state machine — LOBBY → DEPLOY → ENDGAME → LOBBY, one region at a time for ~300ms detection
- [x] EasyOCR on CPU — prevents GPU contention with game rendering + video encoding
- [x] Background OCR thread — frame processing off capture callback, eliminates recording stutter
- [x] Anti-throttling stack — process priority, GPU priority REALTIME, power throttle opt-out, powerSaveBlocker
- [x] Recording overlay — always-on-top HUD, Marathon aesthetic, configurable position
- [x] Rolling 3-shot readyup buffer — captures READY UP, RUN, DEPLOYING phases
- [x] OCR frame screenshots — guaranteed correct content vs take_screenshot() timing issues
- [x] New detection states — SELECT_ZONE, RUN, DEPLOYING, ELIMINATED, EXFILTRATED
- [x] Window finder fix — match by title "marathon" (exact), exclude "runlog" windows
- [x] Endgame screenshots sent to Phase 1 Call 2 for killed_by accuracy
- [x] 4K end frames in iterative 20-frame batches
- [x] Readyup screenshots per phase — slot 1=READY_UP, slot 2=RUN, slot 3=DEPLOYING. One per phase, overwrites within same phase (keeps latest)
- [x] State machine timeout recovery — deploy state resets after 90s (backed out), endgame resets + stops recording after 30min (crash/disconnect)
- [ ] Death screen detection for mid-match death location tracking
- [ ] Custom clip trimming UI (adjust start/end of auto-generated clips)

### Detection Feed Aesthetic
- ~~Boot sequence animation~~ — overkill, app already has boot sequence on startup
- [ ] More Marathon data-ticker elements — random symbols, technical readouts, ambient data decoration
- [ ] Reference Marathon art style (TRANSLINK VECT-Φ9, MATRIX BREACH DETECTED, etc.)

### Overlay
- [x] Move overlay update to App.tsx — polling + overlay + toasts now run globally from App.tsx via Zustand store
- ~~Boot sequence style for overlay initialization~~ — not needed

### SYS.CONFIG Settings
- [ ] Video encoder selection UI — HEVC (smaller) vs H.264 (compatible). Currently hardcoded to HEVC for testing
- [ ] Recording bitrate slider
- [ ] Recording FPS — 30 vs 60
- [ ] OCR polling rate
- [ ] Overlay opacity/size options — position/corner/nudge/toggle done, opacity and size still hardcoded (260x30)

### Processing Queue Bugs
- [x] "FAILED" false positive — Fixed: `_update_processing_item()` was missing `p1_failed` parameter, causing TypeError → caught by except → set to "error" instead of "done"
- [x] Marker file cleanup — `.encoded`, `.p1done`, `.done`, `.endgame` markers now cleaned up on SAVE and DISCARD

### Processing Pipeline
- [x] Separate concurrency limits for Phase 1 vs Phase 2 — P1 pool (4 workers, fast), P2 pool (2 workers, heavy). Phase 1 completes and submits to P2 pool, freeing P1 workers immediately.

### Phase 2 Prompt Quality
- [ ] Highlights prompt tuning — tighter criteria, better timestamp accuracy, better clip type selection
- [ ] Story/summary prompt tuning — more accurate narratives, review against actual gameplay

### Processing Metrics (Backend)
- [ ] Log per-phase timing to database (frame extraction, P1 analysis, compression, P2 analysis, clip cutting)
- [ ] Track token usage from Anthropic API responses (input_tokens, output_tokens, cost estimate)
- [ ] Store metrics per-run in a processing_metrics table (run_id, phase, duration_seconds, tokens_in, tokens_out)
- [ ] CLI calls don't report tokens — only track for API-based analysis

### Video & Clips
- [x] KEEP button should store the full recording path on the run record
- [x] Debrief page — "FULL RUN" card in highlights grid for kept recordings, plays inline in the video player
- [x] Delete clips from Run Reports — X button on hover, cyberpunk confirmation dialog ("SYS.WARN // PERMANENT.ACTION")
- [x] DELETE button should clean up 4K recording, thumbnail, and marker files — clips folder preserved for Run Reports

### Data Quality
- [x] Sonnet should return `null` (not 0) for stats it couldn't find — prompt + schema change
- [x] Frontend/stats should skip nulls in calculations — nulls treated as 0 in sums (correct behavior: unknown = don't count)
- [ ] Shell detection accuracy — Vandal/Thief confusion persists despite facial geometry descriptions and high thinking. May need per-shell training examples or different approach

### Data
- [ ] Death heatmap (map game coordinates to map image, mark death locations)

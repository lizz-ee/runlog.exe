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
- [ ] Completed items disappear on app restart — need to persist queue state or auto-save/discard recordings

### UI Enhancements
- [ ] Pipeline pill-shaped segments (Marathon HUD style) — replace dots with connected pill groups per phase, labels inside
- [ ] Sidebar badge counts — unviewed run reports, processing items awaiting KEEP/DELETE on Live page
- [ ] Remove "RUN #" from processing queue items — internal detail, not user-facing
- [ ] Export data (CSV/JSON) for runs, stats, spawn data

### Live Page — Processing Stage Visibility
The processing queue currently shows a single status label per item (e.g. "ANALYZING STATS"). With 10 stages across two phases, users need better visibility into where each item is in the pipeline.

**Plan:**
- [ ] Add a horizontal stage progress bar to each processing item card
  - Visual pipeline: dots/segments for each stage, connected by lines
  - Completed stages = green, active stage = pulsing yellow, upcoming = dim/muted
  - Stages grouped into Phase 1 (FRAMES → STATS → SAVE → ✓) and Phase 2 (COMPRESS → GAMEPLAY → CLIPS → ✓)
  - Phase 1 and Phase 2 visually separated (gap or divider)
- [ ] Show elapsed time per item (timer starts when item leaves `queued`)
- [ ] Add sub-status text under active stage (e.g. "Retry: searching forward +45s", "Escalating to 15fps")
  - Backend: add optional `status_detail` string field to processing items
  - Update `_update_processing_item()` to accept detail text
  - Sprinkle `on_phase` calls with detail strings at retry/escalation points in video_processor.py
- [ ] Show what Phase 1 found vs missed (spawn coords ✓, stats tab ✓, loadout ✗)
  - Backend: expose `loading_screen_found`, `stats_tab_found`, `loadout_tab_found` flags in status
  - Frontend: show as small check/x indicators when phase1_done
- [ ] Error messages — attach error reason text to failed items instead of just "FAILED"

### Live Page — Queue Overview Header
The QUEUE status card currently jams all active stage counts into one text line ("2 ANALYZING STATS | 1 SAVING | 3 QUEUED") which overflows and is hard to scan.

**Plan:**
- [ ] Replace the single QUEUE card with a wider pipeline overview strip (span full width or 2-3 cols)
  - Horizontal flow of stage nodes: QUEUED → FRAMES → STATS → SAVE → P1 ✓ → COMPRESS → GAMEPLAY → CLIPS → DONE
  - Each node shows its count (number badge) — 0 = dim, >0 = lit up with color
  - Active stages pulse/glow, completed stages solid green, queued dim
  - Items visually "flow" left to right through the pipeline
- [ ] Keep ENGINE, RECORDING, DURATION as separate cards (top row)
- [ ] Add total items count + completed/failed summary (e.g. "7 total // 4 done // 1 error")
- [ ] Clicking a stage node could scroll to / filter the queue list below to items in that stage

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
- [ ] Readyup screenshots per phase — one from READY UP, one from RUN, one from DEPLOYING (instead of rolling buffer)
- [ ] Death screen detection for mid-match death location tracking
- [ ] Custom clip trimming UI (adjust start/end of auto-generated clips)

### Detection Feed Aesthetic
- [ ] Boot sequence animation — Marathon-style [WAKE] terminal when engine initializes (SEN checks, dotted leader lines, NN REVIEW COMPLETE)
- [ ] More Marathon data-ticker elements — random symbols, technical readouts, ambient data decoration
- [ ] Reference Marathon art style (TRANSLINK VECT-Φ9, MATRIX BREACH DETECTED, etc.)

### Overlay
- [ ] Move overlay update to App.tsx — currently in Live.tsx, stops updating on other pages
- [ ] Boot sequence style for overlay initialization

### SYS.CONFIG Settings
- [ ] Video encoder selection — HEVC (smaller) vs H.264 (compatible)
- [ ] Recording bitrate slider
- [ ] Recording FPS — 30 vs 60
- [ ] OCR polling rate
- [ ] Overlay opacity/size options

### Processing Queue Bugs
- [ ] "FAILED" false positive — Processing queue shows FAILED but run actually completed both phases and appears in Run Reports. DB check for summary was added but still not catching it. Need to debug with logs to find the actual failure path.
- [ ] Marker file cleanup — `.encoded`, `.p1done`, `.done`, `.endgame` marker files accumulate in recordings folder and never get cleaned up. Should be deleted after successful processing or on app startup.

### Processing Pipeline
- [ ] Separate concurrency limits for Phase 1 vs Phase 2 — Phase 1 (stats extraction) is fast now, shouldn't be bottlenecked by Phase 2 (video narrative). Allow unlimited Phase 1 concurrent, cap Phase 2 (gameplay video analysis) at 2 concurrent.

### Phase 2 Prompt Quality
- [ ] Highlights prompt tuning — tighter criteria, better timestamp accuracy, better clip type selection
- [ ] Story/summary prompt tuning — more accurate narratives, review against actual gameplay

### Processing Metrics (Backend)
- [ ] Log per-phase timing to database (frame extraction, P1 analysis, compression, P2 analysis, clip cutting)
- [ ] Track token usage from Anthropic API responses (input_tokens, output_tokens, cost estimate)
- [ ] Store metrics per-run in a processing_metrics table (run_id, phase, duration_seconds, tokens_in, tokens_out)
- [ ] CLI calls don't report tokens — only track for API-based analysis

### Video & Clips
- [ ] KEEP button should store the full recording path on the run record
- [ ] Debrief page — add "Watch Full Run" link for kept recordings (opens in system player since 4K won't play in-app)
- [ ] DELETE button should clean up both 4K and 1080p clip files

### Data Quality
- [x] Sonnet should return `null` (not 0) for stats it couldn't find — prompt + schema change
- [ ] Frontend/stats should skip nulls in calculations (don't count "unknown" as 0 kills)
- [ ] Shell detection accuracy — Vandal/Thief confusion persists despite facial geometry descriptions and high thinking. May need per-shell training examples or different approach

### Data
- [ ] Death heatmap (map game coordinates to map image, mark death locations)

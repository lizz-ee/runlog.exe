# runlog.exe — TODO

## Completed Features

### Auto-Capture System (Done)
- [x] Rust capture engine (`runlog-recorder.exe`) — zero-copy GPU pipeline, WGC + MediaFoundation H.264
- [x] WGC (Windows Graphics Capture) — privacy-safe, game-window-only, works when alt-tabbed
- [x] 60fps recording at native 4K via hardware encoder (no CPU frame copies)
- [x] OCR-based game state detection — three regions: OCR.DEPLOY (map name → start), OCR.ENDGAME (RUN_COMPLETE → timestamp), OCR.LOBBY (PREPARE → stop, READY_UP → screenshot, SEARCHING → visual)
- [x] No debounce — act on first OCR match (prevents missed detections on fast screen transitions)
- [x] Ready-up screenshot capture (full-screen + loadout crop) for shell/loadout identification
- [x] Deploy screenshot capture — 3-shot burst (500ms intervals) for map name and spawn coordinates, full + crop versions
- [x] Marathon.exe process detection (recording-manager in Electron)
- [x] System tray notifications for capture events
- [x] Auto-resume unprocessed recordings on startup
- [x] No minimum recording threshold — every DEPLOY-triggered recording is processed
- [x] Overlay HUD — lazy show (only when Marathon detected), always-on-top, draggable, 30fps throttle
- [x] Stale frame cleared when Marathon closes (detection feed shows AWAITING SIGNAL)
- [x] Backend stale process kill on startup (kills old Python backend on port 8000)

### Video Processing Pipeline (Done)
- [x] Two-phase analysis — Phase 1: split prompts (Call 1 screenshots + Call 2 end frames), Phase 2: narrative + clips
- [x] Phase 1 Call 1: screenshots → map, coordinates, shell, loadout value, player level, vault value, squad, weapons
- [x] Phase 1 Call 2: end frames → stats, kills, deaths, revives, loot, duration, weapons, killed_by, damage_contributors
- [x] Phase 2: video → grade (survival-first grading), summary, highlights → clips + sprite sheets
- [x] Spawn coordinate extraction from deploy crop screenshots
- [x] Iterative spawn search — forward in 45s chunks, no cap, searches entire video
- [x] Iterative stats search — backward in 30s chunks through entire video
- [x] Adaptive fps escalation — 5 → 10 → 15 → 20 → 30fps if Sonnet needs more frames
- [x] Fuzzy spawn point matching (Euclidean distance threshold)
- [x] Grade system (S through F) — survival-first, weighted: 35% survival, 25% runner kills, 15% loot, 10% revives, 5% PvE
- [x] AI narrative summaries (second-person run reports)
- [x] Mandatory highlight clips: every PVP kill, death, extraction — plus all notable combat moments
- [x] Clip thumbnails auto-generated (endgame screenshot for full recordings)
- [x] Sprite sheet generation for hover scrub (3fps, min 30 frames, cap 300)
- [x] Processing queue with real-time status tracking
- [x] Pipeline dots with P2 failure coloring + RETRY button
- [x] Phase 2 re-marks run as unviewed after grade + summary + clips all ready
- [x] Phase 2 CLI JSON extraction hardened (backwards scan, repeat-JSON prompt)

### TRANSMISSIONS Page (Done — merged Run Records + Run Reports)
- [x] Unified page combining stats + highlights + debrief
- [x] Grade badges with rarity colors (S=gold, A=purple, B=blue, C=green, D/F=grey)
- [x] Filters: ALL/EXFIL/KIA outcome, grade S/A/B/C/D/F, ALL ZONES map, favorites hexagon
- [x] Expanded view: DATE, CHANGE SHELL, SQUAD, PRIMARY/SECONDARY, INVENTORY (start→end delta), KILLED BY with damage_contributors or EXTRACTED//CLEAN
- [x] Pill-shaped clip cards with sprite sheet hover scrub + scrub bar with green cursor
- [x] ClipTimeline video player: seekbar, draggable IN/OUT markers, loop toggle, CREATE CLIP with naming
- [x] Custom clip creation via ffmpeg stream copy + auto thumbnail + sprite generation
- [x] Clips appear immediately after creation (local state refresh)
- [x] Delete removes mp4 + thumb + sprite, closes player if playing, refreshes UI
- [x] Favorite system: hexagon toggle (green), filter button, is_favorite DB column + API
- [x] Unviewed rows: cyan grid overlay + tinted background
- [x] Pagination: 21 per page
- [x] All pages auto-refresh on Phase 1 + Phase 2 completion

### TERMINAL Page (Done — was OVERVIEW/Dashboard)
- [x] Header shows LVL//:N: from latest run's player_level
- [x] VAULT.VALUE trend chart (area chart, all runs with vault_value)
- [x] Recent runs (7) using shared RunRow component from TRANSMISSIONS
- [x] Hero stats, favorites, economy, combat, time by map

### NEURAL.LINK (Done)
- [x] Shells: 7 shell cards sorted by weighted score (10% base + 35% survival + 25% runner kills + 5% PvE + 10% revives + 15% loot)
- [x] Squad/Runners: top 7 squad mates, gamertag normalization (strip #tag), self-exclusion (most common gamertag)
- [x] Glitch effect (animate-rgb-split) on selected shell/runner name only
- [x] Long gamertag font scaling

### UPLINK (Done)
- [x] Session code: :NNA: or RECALL//:NNA: when no new runs this launch
- [x] Session debrief stats, AI briefing with skeleton loading
- [x] 3 trend charts: survival, loot, runner eliminations
- [x] CRT terminal chat with streaming
- [x] Auto-refresh on Phase 1 + Phase 2

### Interactive Maps (Done)
- [x] Perimeter, Dire Marsh, Outpost maps with spawn heatmaps
- [x] Draggable spawn markers with coordinate persistence
- [x] Per-spawn tooltips, spawn sorting, per-map stat cards
- [x] Auto-refresh on Phase 1 + Phase 2

### DETECT.EXE (Done)
- [x] Detection feed with CRT vignette (radial gradient + scanlines + boxShadow)
- [x] Pipeline dots: P1/P2 phase coloring, P2 failure turns dots red
- [x] RETRY button for Phase 2 failures, SAVE/DISCARD with file size for successes
- [x] Processing queue with thumbnails (endgame screenshot)

### SYS.CONFIG (Done)
- [x] Recording: encoder HEVC/H.264, bitrate, fps
- [x] Processing: P1/P2 worker count sliders
- [x] Overlay: position, opacity, size
- [x] Auth: API Key vs Claude CLI, dual model selectors

### Sidebar (Done)
- [x] SYSTEM: TERMINAL, TRANSMISSIONS, NEURAL.LINK
- [x] MAPS: Perimeter, Dire Marsh, Outpost, Cryo Archive (redacted)
- [x] LIVE: UPLINK, DETECT.EXE
- [x] SYS.CONFIG, unviewed badge on TRANSMISSIONS

### Database Fields (Done)
- [x] is_favorite, starting_loadout_value, player_level, vault_value
- [x] killed_by_weapon, damage_contributors (JSON)
- [x] All migrations auto-applied on startup

---

## Remaining TODOs

### Maps
- [ ] Get Cryo Archive map image (currently marked REDACTED)
- [ ] Add Cryo Archive spawn point data as games are played

### Stats & Charts
- [ ] Weapon performance scoring — combined survival rate + K/D + loot per weapon, best/worst weapon per shell and per map

### UI Enhancements
- [ ] Export data (CSV/JSON) for runs, stats, spawn data

### Capture Improvements
- [ ] Death screen detection for mid-match death location tracking

### Processing Metrics
- [ ] Add token usage tracking from API responses (input_tokens, output_tokens, cost estimate)

### Editor Enhancements
- [ ] Timeline markers — show AI-generated highlight clips as marked segments on the video timeline

### Run Report Card Export (Future)
- [ ] Export button on run row
- [ ] Generates styled image card with Marathon cyberpunk aesthetic
- [ ] Card contents: grade, map, shell, kills, outcome, loot, narrative snippet, RUNLOG.EXE branding
- [ ] Dark background, Discord-friendly aspect ratio

### Data
- [ ] Death heatmap (map game coordinates to map image, mark death locations)

---

## Audit TODOs (completed)

### Architecture
- [x] Replace polling (setInterval 2s) with Server-Sent Events for capture status — SSE endpoint at /api/sse/events with polling fallback
- [x] Add spawn heatmap caching with TTL invalidation — 10s TTL, invalidated on spawn/run mutations

### Infrastructure
- [ ] Code signing for Windows builds (requires certificate purchase) — electron-builder config scaffolded, needs cert
- [x] Enable `noUnusedLocals`/`noUnusedParameters` in tsconfig.json and fix all resulting lint errors
- [x] Add ARIA labels to TitleBar buttons, spawn map markers, and overlay controls for accessibility
- [x] Add auto-update support via electron-updater — scaffolded, uncomment in main.js when releases are configured

### Code quality
- [x] Extract shared Python utilities for K/D ratio calculation — calc_kd() in backend/app/utils.py
- [x] Replace remaining bare `except Exception: pass` blocks in video_processor.py — all 10 now log
- [x] Replace silent `.catch(() => {})` in frontend components — 22 catches now log errors
- [x] Reduce `any` type usage in frontend — proper interfaces added to types.ts

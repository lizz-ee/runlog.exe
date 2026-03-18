# runlog.exe — TODO

## Completed Features

### Auto-Capture System (Done)
- [x] WGC (Windows Graphics Capture) — privacy-safe, game-window-only recording
- [x] NVENC GPU encoding at 60fps
- [x] ddagrab fallback if WGC unavailable
- [x] OCR-based game state detection (SEARCHING, READY UP, PREPARE, DEPLOYING)
- [x] Debounced state machine (2 consecutive matches required)
- [x] Marathon.exe process detection (recording-manager in Electron)
- [x] System tray notifications for capture events
- [x] Auto-resume unprocessed recordings on startup
- [x] Min 90s recording threshold (discards short recordings)

### Video Processing Pipeline (Done)
- [x] Two-phase analysis (Phase 1: fast stats, Phase 2: async narrative + clips)
- [x] Frame extraction — start (120s @ 1fps) and end (30s @ 4fps) windows
- [x] Claude Sonnet integration for frame analysis + video analysis
- [x] Spawn coordinate extraction from blue loading screen
- [x] Fuzzy spawn point matching (Euclidean distance threshold)
- [x] Grade system (S through F)
- [x] AI narrative summaries (second-person run reports)
- [x] Highlight clip cutting (stream copy, no re-encoding)
- [x] Clip thumbnails auto-generated
- [x] Processing queue with real-time status tracking
- [x] Retry logic (expand frame windows if loading/stats screens not found)
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
- [x] Shells page (per-shell stats with combat, economy, and info breakdowns)
- [x] System tray integration
- [x] Auto-backup (7 rolling SQLite snapshots)

---

## Remaining TODOs

### Maps
- [ ] Get Cryo Archive map image (currently marked REDACTED)
- [ ] Add Cryo Archive spawn point data as games are played

### Stats & Charts
- [ ] Trends/charts on dashboard (survival rate over time, loot over time)
- [ ] Weapon stats page (K/D per weapon, win rate per weapon)
- [ ] Per-map trends (performance on each map over time)

### UI Enhancements
- [ ] Run detail view as dedicated page (currently inline expand only)
- [ ] Export data (CSV/JSON) for runs, stats, spawn data
- [ ] Loadout management UI (save/name loadouts, link to runs)
- [ ] Session view page (group runs by play session, session-level stats)

### Capture Improvements
- [ ] Detect "READY UP" pre-match screen to log loadout going IN to a run
- [ ] Death screen detection for mid-match death location tracking
- [ ] Custom clip trimming UI (adjust start/end of auto-generated clips)

### Data
- [ ] Weapon database seeding (auto-populate from Marathon_Complete_Database.xlsx)
- [ ] Item/loot image recognition (currently text-only extraction)
- [ ] Death heatmap (where on the map you die, not just where you spawn)

### Quality of Life
- [ ] Settings page (API key config, capture preferences, data directory)
- [ ] Onboarding flow for first-time setup
- [ ] Squad stats page (performance with specific squad mates)
- [ ] LAUNCH.bat script for easy startup without Electron build

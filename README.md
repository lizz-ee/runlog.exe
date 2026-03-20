# runlog.exe

A local-first desktop app for **Marathon** (Bungie, 2026). Play your runs, stats appear automatically.

---

## What Is This?

runlog.exe is a desktop companion app that **automatically records and analyzes** your Marathon extraction runs. No manual data entry, no accounts. Just play — runlog.exe captures your gameplay, extracts your stats with AI, grades your performance, generates highlight clips, and builds a comprehensive stats dashboard over time.

**Powered by Claude Vision** — runlog.exe records your Marathon gameplay using a dedicated Rust capture engine (WGC + MediaFoundation H.264, zero-copy GPU pipeline), then sends key frames to Claude's vision API to extract structured match data, write narrative run reports, and identify highlight moments.

---

## How It Works

```
1. Launch runlog.exe — it sits in your system tray
2. Launch Marathon — runlog.exe detects it and starts watching
3. Play normally — recording begins automatically when matchmaking starts
4. Finish your run — recording stops when you return to the lobby
5. Stats extracted automatically (kills, deaths, loot, map, spawn, loadout)
6. Narrative report + highlight clips generated asynchronously
7. Dashboard, maps, and run history update automatically
```

---

## Core Features

### Automatic Game Capture
- **Zero-interaction recording** — detects Marathon window, records from matchmaking to lobby
- **Rust capture engine** (`runlog-recorder.exe`) — dedicated binary for recording, zero-copy GPU pipeline
- **Windows Graphics Capture (WGC)** — captures only the game window (privacy-safe, never records desktop, works when alt-tabbed)
- **MediaFoundation encoding** — 60fps recording at native 4K, hardware-accelerated (HEVC or H.264, configurable)
- **OCR-based state detection** — three scan regions detect deployment screen (start recording), RUN_COMPLETE (log stats timestamp), and lobby buttons (stop recording)
- **Per-phase screenshot capture** — one screenshot each from READY UP, RUN, and DEPLOYING phases for shell/loadout identification
- **State machine timeout recovery** — auto-recovers if deploy screen missed (90s) or game crashes mid-run (30min)

### Two-Phase AI Analysis
- **Phase 1 (Fast, High Thinking):** Uses OCR screenshots (deploy, readyup, loadout crop) + end-of-run frames. Claude Sonnet with high thinking extracts stats (kills, deaths, loot, map, weapons, spawn coordinates, survival status), identifies shell by facial geometry, reads loadout values and item tiers
- **Screenshot pipeline:** Deploy screenshot for map/coordinates, readyup screenshot for shell/loadout identification, cropped loadout for detailed item tier analysis
- **Iterative spawn search:** If deployment loading screen not found in first 90s, searches forward in 45s chunks
- **Iterative stats search:** If stats tab not found, searches backwards through the video in 30s chunks
- **Adaptive fps:** If Sonnet sees stats tabs but frames flip too fast, escalates extraction fps (5 → 10 → 15 → 20 → 30fps cap) until readable
- **Phase 2 (Async, Medium Thinking):** Compresses full video, sends to Claude for narrative analysis — letter grade (S through F), 2-4 paragraph run report written in second person, and timestamped highlight moments
- **Auto-resume:** Unprocessed recordings from previous sessions are automatically queued on startup

### Highlight Clips
- **Auto-generated** from Phase 2 analysis at highlight timestamps
- **Types:** Kill, Death, Extraction, Loot, Close Call, Funny
- **Stream copy** — instant cuts from original 4K footage, no re-encoding
- **Keep or delete** from the Live monitor
- **Delete individual clips** from Run Reports with confirmation dialog
- **Full run playback** — kept recordings appear as inline video cards in Run Reports

### Interactive Maps
- **4 maps:** Perimeter, Dire Marsh, Outpost, Cryo Archive
- **Draggable spawn markers** on map images with per-spawn stats
- **Spawn tooltips:** Survival %, win streak, avg loot, best/worst loot, favorite weapon/shell, killed-by tracking
- **Coordinates:** Extracted from the deployment loading screen via Claude Vision, fuzzy-matched to existing spawn points
- **Sortable:** By name, survival rate, loot value, win streak
- **Reference spawn data** — ships with pre-mapped spawn points, new users see all locations immediately
- **New spawn discovery** — auto-detected spawns named `VCTR//X:Y` (coordinate reference), staged in bracket area for user to position and rename
- **Double-click to rename** any spawn point, bracket shrinks as spawns are named

### Run History & Archive
- Chronological log of all extraction runs with pagination
- Filter by outcome (Exfiltrated / KIA) and map
- Expandable rows showing full combat, loot, and squad details

### Run Reports
- **Letter grades** (S through F) with color coding
- **AI-generated narrative summaries** — story-style run reports
- **Highlight gallery** — thumbnail grid of all clips for each run with inline video player
- Paginated grid view (21 per page)

### Stats Dashboard
- **Hero stats:** Total runs, survival rate, K/D ratio, total play time
- **Favorites:** Most-used shell, weapon, map, squad mate
- **Economy:** Total loot extracted, average per run, best and worst runs
- **Combat:** PVE kills, runner kills, deaths, crew revives
- **Time by map:** Breakdown of play time across all maps
- **Recent runs:** Last 7 runs with expandable details

### Shells Page
- **Cyberpunk HUD cards** — shell artwork with corner brackets, scan line animations, glow effects, survival micro-bars
- **Ranked by performance** — sorted best to worst by run count, all shells selectable (unused shells show zeroed stats)
- **Hero stats:** Runs, survival rate, K/D, avg loot, total time per shell
- **Combat detail:** PVE kills, runner kills, deaths, revives
- **Economy:** Total loot, avg loot per run, exfil vs KIA count
- **Info:** Favorite weapon, avg run time

### Squad Page
- **Top 7 squad mates** ranked by runs together (rule of 7)
- **Cyberpunk HUD cards** — gamertag, run count, survival rate, animated scan lines, corner brackets
- **VS Overall** — shows how your survival rate changes with each squad mate
- **Per-mate breakdowns:** Operations (runs, exfil/KIA, time), Combat (PVE/PVP kills, deaths, revives), Economy (loot, avg loot)

### SYS.CONFIG Settings
- **Recording config** — encoder (HEVC/H.264), bitrate (10-100 Mbps), framerate (30/60 FPS)
- **Processing config** — P1 worker count (1-8), P2 worker count (1-4)
- **HUD overlay** — enable/disable, size (SM/MD/LG), opacity, draggable position preview
- **Authentication** — dual mode: API Key or Claude CLI (uses your Claude subscription, no API tokens)
- **Model selection** — Sonnet (accuracy) or Haiku (cost)
- **Auto-detect Claude CLI** — shows install status and path

### Live Capture Monitor
- **Engine status cards:** Engine state, recording state, duration, queue size
- **Detection feed:** Live frame from WGC capture for debugging
- **Processing queue:** Real-time view of all videos being processed with pipeline progress (geometric shapes, color-coded stages)
- **P1 detection flags** — shows what Phase 1 found vs missed (MAP/STATS/LOADOUT indicators)
- **Error detail** — failed items show actual error reason, not just "FAILED"
- **Sub-status text** — shows current processing detail (e.g., "Retry: searching forward +45s")
- **Thumbnails and metadata** for each recording
- **Keep/Delete** actions for processed recordings — marker files cleaned up automatically
- **Queue persistence** — completed items survive app restart, show SAVE/DISCARD on relaunch
- **Separate P1/P2 concurrency** — Phase 1 (fast stats, 4 workers) and Phase 2 (narrative, 2 workers) run independently
- **Auto-resume toast** for recordings carried over from previous sessions

### Session Tracking
- Group runs into play sessions
- Session start/end timestamps with notes

---

## Tech Stack

| Layer | Tech |
|---|---|
| Desktop | Electron 28 |
| Frontend | React 19 + TypeScript + Vite |
| Styling | Tailwind CSS (Marathon neon lime theme) |
| State | Zustand |
| Animation | Framer Motion |
| Charts | Recharts |
| Backend | Python FastAPI + Uvicorn |
| Database | SQLite (local-first, auto-backup) |
| AI / Vision | Anthropic Claude API (Sonnet/Haiku) or Claude CLI |
| Capture | Rust binary (WGC + MediaFoundation HEVC/H.264, zero-copy GPU) |
| OCR | EasyOCR (GPU-accelerated) |
| Video | FFmpeg (muxing, compression, clip cutting) |
| Images | Pillow, OpenCV |

---

## Data Models

### Runner (Shell)
A Marathon character class.
- `id`, `name`, `icon`, `notes`, `created_at`

### Weapon
A weapon in Marathon.
- `id`, `name`, `weapon_type` (primary/secondary), `notes`, `created_at`

### Run
A single extraction run / match.
- `id`, `runner_id`, `loadout_id`, `map_name`, `date`, `session_id`, `spawn_point_id`
- `survived` (boolean — did you extract?)
- `kills`, `combatant_eliminations`, `runner_eliminations`, `deaths`, `assists`, `crew_revives`
- `loot_extracted` (JSON), `loot_value_total`
- `duration_seconds`
- `squad_size`, `squad_members` (JSON)
- `primary_weapon`, `secondary_weapon`
- `killed_by`, `killed_by_damage`
- `player_gamertag`
- `grade` (S/A/B/C/D/F), `summary` (AI narrative)
- `screenshot_path`, `notes`, `created_at`

### Session
A group of runs played in one sitting.
- `id`, `started_at`, `ended_at`, `notes`

### SpawnPoint
A map location where you deployed.
- `id`, `run_id`, `map_name`, `spawn_location`
- `x`, `y` (percentage on map image)
- `game_coord_x`, `game_coord_y` (from loading screen, fuzzy-matched)
- `screenshot_path`, `notes`, `created_at`
- Ships with reference spawn data — new installs get all known locations pre-populated

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Electron Desktop App                       │
│                                                              │
│  ┌─────────────────────┐  ┌───────────────────────────────┐  │
│  │   Electron Main     │  │      React Frontend (Vite)    │  │
│  │                     │  │                               │  │
│  │  backend-manager    │  │  Dashboard    Run History     │  │
│  │  (spawns Python)    │  │  Maps         Debrief         │  │
│  │                     │  │  Shells       Squad           │  │
│  │  recording-manager  │  │  Live Monitor Settings        │  │
│  │  (monitors Marathon)│  │                               │  │
│  │                     │  │  Zustand store + Axios API    │  │
│  │  System tray        │  │                               │  │
│  │  Window state       │  │                               │  │
│  └─────────┬───────────┘  └───────────────┬───────────────┘  │
│            │ IPC                           │ HTTP             │
│  ┌─────────▼─────────────────────────────────────────────┐   │
│  │              FastAPI Backend (Python)                  │   │
│  │                                                       │   │
│  │  ┌─────────────────────────────────────────────────┐  │   │
│  │  │         Auto-Capture Engine                     │  │   │
│  │  │                                                 │  │   │
│  │  │  Rust binary (runlog-recorder.exe)              │  │   │
│  │  │    WGC ──► MediaFoundation H.264 (GPU, 60fps)  │  │   │
│  │  │    OCR frames (2fps) ──► Python EasyOCR        │  │   │
│  │  │                                                 │  │   │
│  │  │  State detection ──► Start/Stop                │  │   │
│  │  │  (DEPLOY → record, PREPARE → stop)             │  │   │
│  │  └─────────────────────────────┬───────────────────┘  │   │
│  │                                │                      │   │
│  │  ┌─────────────────────────────▼───────────────────┐  │   │
│  │  │         Video Processing Pipeline               │  │   │
│  │  │                                                 │  │   │
│  │  │  Phase 1: Key frames ──► Claude Sonnet          │  │   │
│  │  │    → Stats, spawn coords, weapons, survival     │  │   │
│  │  │    → Saved to DB                                 │  │   │
│  │  │                                                 │  │   │
│  │  │  Phase 2: Compressed video ──► Claude Sonnet    │  │   │
│  │  │    → Grade, narrative summary, highlights       │  │   │
│  │  │    → Clip cutting (stream copy, no re-encode)   │  │   │
│  │  │    → Updated in DB                               │  │   │
│  │  └─────────────────────────────────────────────────┘  │   │
│  │                                                       │   │
│  │  /api/runs       (CRUD)        /api/capture (engine)  │   │
│  │  /api/runners    (CRUD)        /api/spawns  (heatmap) │   │
│  │  /api/weapons    (CRUD)        /api/screenshot (parse)│   │
│  │  /api/sessions   (CRUD)        /api/stats   (aggs)    │   │
│  │  /api/squad      (stats)       /api/settings (config) │   │
│  │                                                       │   │
│  │  SQLite ─── %APPDATA%/runlog/marathon/data/runlog.db  │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## API Endpoints

### Auto-Capture Engine
- `POST /api/capture/start` — Start the capture engine
- `POST /api/capture/stop` — Stop the capture engine
- `GET /api/capture/status` — Engine status (active, recording, queue, processing phases)
- `GET /api/capture/frame` — Latest detection frame as JPEG
- `GET /api/capture/thumbnail/{filename}` — Recording thumbnail
- `GET /api/capture/clips` — List all highlight clips
- `GET /api/capture/clips/{filename}` — Serve clip (HTTP range requests)
- `POST /api/capture/recording/keep` — Save a recording
- `POST /api/capture/recording/delete` — Delete a recording
- `POST /api/capture/recording/retry` — Retry a failed recording
- `POST /api/capture/clip/delete` — Delete an individual clip

### Spawn Points
- `POST /api/spawns/parse` — Upload spawn screenshot, get location via Claude Vision
- `POST /api/spawns` — Create spawn point
- `GET /api/spawns` — List spawns (filter by map)
- `GET /api/spawns/heatmap` — Spawn frequency analysis with per-spawn stats
- `PUT /api/spawns/update-coords` — Update x,y by map + location name
- `PUT /api/spawns/update-coords-by-id` — Update x,y by spawn ID
- `PUT /api/spawns/rename` — Rename a spawn point

### Runs
- `GET /api/runs` — List runs (paginated, filter by map/survived/runner)
- `GET /api/runs/recent` — Last 10 runs
- `POST /api/runs` — Create a run
- `GET /api/runs/{id}` — Get run details
- `PUT /api/runs/{id}` — Update a run

### Runners
- `GET /api/runners` — List runners
- `POST /api/runners` — Add a runner
- `GET /api/runners/{id}` — Get runner details
- `PUT /api/runners/{id}` — Update a runner
- `DELETE /api/runners/{id}` — Delete a runner

### Weapons
- `GET /api/weapons` — List weapons
- `POST /api/weapons` — Create a weapon
- `DELETE /api/weapons/{id}` — Delete a weapon

### Sessions
- `GET /api/sessions` — List sessions
- `POST /api/sessions` — Create a session
- `PUT /api/sessions/{id}/end` — End a session

### Stats
- `GET /api/stats/overview` — Global stats (survival rate, K/D, favorites, time breakdown)
- `GET /api/stats/by-map` — Stats per map
- `GET /api/stats/by-runner` — Stats per runner
- `GET /api/stats/trends` — Daily aggregated trends

### Squad
- `GET /api/squad/stats` — Top squad mates with per-mate stats (runs, survival, combat, loot)

### Settings
- `GET /api/settings` — Current settings (API key, CLI status, recording config, processing config)
- `POST /api/settings/api-key` — Save API key
- `POST /api/settings/api-key/test` — Test API key validity
- `DELETE /api/settings/api-key` — Remove saved API key
- `POST /api/settings/config` — Update any config value (encoder, bitrate, fps, workers, model, auth mode)
- `GET /api/settings/cli-status` — Check Claude CLI installation and auth status

---

## Screenshots the App Parses

### Automatic (OCR Screenshots + Video Capture)
runlog.exe captures screenshots at key moments and records the full run as video:
- **Ready-up screenshot** (`readyup.jpg`): Full-screen capture of the loadout screen — shell, equipped items, contract, crew size
- **Loadout crop** (`readyup_loadout.jpg`): Zoomed crop of the loadout grid — item tiers (gray/green/blue/purple/gold from price tag color), values, shell portrait
- **Deploy screenshot** (`deploy.jpg`): Deployment loading screen — map name, spawn coordinates
- **End-of-run frames** (last 60s at 5fps): Stats tab (kills, deaths, loot), survival status, weapons used, killed-by info
- **Full video recording** (4K 60fps): Used for Phase 2 narrative analysis and highlight clip generation

---

## Getting Started

### Prerequisites
- Windows 10/11
- Python 3.12+
- Node.js 18+
- FFmpeg (on PATH)
- Rust toolchain (for building runlog-recorder.exe, or use pre-built binary)

### Setup
```bash
# Backend
cd backend
pip install -r requirements.txt

# Build Rust recorder
cd recorder
cargo build --release
cd ..

# Frontend
cd frontend
npm install
```

### Authentication
Two options:
1. **API Key** — Configure in-app via SYS.CONFIG. Key is tested before saving, stored locally in `%APPDATA%/runlog/settings.json`
2. **Claude CLI** — Install Claude Code CLI (`npm install -g @anthropic-ai/claude-code`), run `claude login`. Uses your Claude subscription — no API tokens required. Auto-detected by the app.

### Development
```bash
# Terminal 1 — Backend
cd backend
RUNLOG_DEV=1 python run.py

# Terminal 2 — Frontend + Electron
cd frontend
npm run electron:dev
```

### Build
```bash
cd frontend
npm run dist
# Output in ../release/
```

---

## Local-First Philosophy

- All data stored locally: `%APPDATA%/runlog/marathon/data/` (DB, recordings, clips)
- Global settings at `%APPDATA%/runlog/settings.json`
- Multi-game ready folder structure (`runlog/<game>/data/`)
- Automatic database backups on startup (keeps last 7)
- Screenshots and recordings saved locally
- No accounts, no cloud sync, no telemetry
- Claude API key or Claude CLI subscription — your choice
- Works offline for everything except AI-powered analysis
- Ships with reference spawn point data — new users see all known locations immediately

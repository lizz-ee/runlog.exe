# runlog.exe

A local-first desktop companion for **Marathon** (Bungie, 2026). Play your runs, stats appear automatically.

**Powered by Claude** — records your gameplay with a zero-copy GPU capture engine, extracts stats with AI vision, generates highlight clips, grades your performance, and builds a comprehensive dashboard over time. No manual data entry, no accounts, no cloud.

---

## How It Works

```
1. Launch runlog.exe — sits in your system tray
2. Launch Marathon — detected automatically via Windows Graphics Capture
3. Play normally — recording starts when you deploy, stops when you return to lobby
4. Stats extracted automatically (kills, deaths, loot, map, spawn, shell, loadout)
5. Narrative report + highlight clips generated asynchronously
6. Dashboard, maps, and run history update automatically
```

---

## TERMINAL

Your command center. Career stats at a glance — total runs, survival rate, K/D, total play time. Favorites show your most-used shell, weapon, map, and squad mate. Economy tracks total loot, average per run, best and worst. Recent runs feed in the center, vault value chart tracking your wealth over time.

![TERMINAL — Dashboard](docs/screenshots/terminal.png)

---

## RUN.LOG

Complete history of every run. Each row shows shell, map, spawn, PvE and PvP kills, deaths, revives, loot gained or lost, duration, and letter grade (S through F). Filters stack — narrow by outcome, grade, map, ranked mode, and favorites.

![RUN.LOG — Run History](docs/screenshots/run_log.png)

Expand any run for the full breakdown — squad, weapons, inventory value change, killed-by with full damage contributors, and auto-generated highlight clips with sprite sheet hover scrub. Built-in video player with custom clip editor — set IN/OUT markers, name your clip, instant stream copy from the original 4K footage. AI debrief narrative at the bottom grades and recaps the run.

![RUN.LOG — Expanded Run](docs/screenshots/run_log_expanded.png)

---

## NEURAL.LINK

Two sections, **Shells** and **Runners**, both ranked by weighted performance score.

**Shells** — all 7 Marathon character classes. Per-shell stats: runs, survival rate, K/D, avg loot, combat breakdown, economy.

**Runners** — your top 7 squad mates. Per-mate stats show how your survival rate and loot change when you play together.

![NEURAL.LINK — Shells + Squad](docs/screenshots/neural_link.png)

---

## MAPS

Each map has its own page with interactive spawn markers, per-map stats (runs, survival rate, K/D, total time), a scrollable spawn point list, and map-wide breakdowns for favorites, economy, combat, and time. Spawn coordinates are extracted from the deployment loading screen and matched to map locations — every run's stats automatically accumulate at the spawn point you deployed from.

![PERIMETER — Spawn Map](docs/screenshots/perimeter.png)

Hover any spawn marker for per-spawn stats — survival rate, win streak, loot averages, kill counts, favorite weapon and shell. Also shows your top enemy from runs at that spawn.

![DIRE MARSH — Per-Spawn Stats](docs/screenshots/dire_marsh.png)

New spawns are detected automatically and staged in the top-left bracket as uncharted markers. Drag them onto the map, rename them, and save. Future runs with matching coordinates will automatically log to that spawn.

![OUTPOST — Uncharted Spawn Staging](docs/screenshots/outpost.png)

---

## UPLINK

AI tactical advisor and session tracker. Every time you launch the app and play, a new session is created. UPLINK generates a briefing for each session — how many runs, survival rate, trends vs your career baseline, and alerts when you're performing above or below average. Charts track survival rate, loot, and runner eliminations across sessions. Terminal-style chat interface — ask UPLINK anything about your stats and it queries your database directly.

![UPLINK — AI Tactical Advisor](docs/screenshots/uplink.png)

---

## DETECT.EXE

Live capture monitor. This is how auto-recording works — OCR scans the game feed to detect deployment (start recording) and lobby return (stop recording). Shows the game window with scan regions visualized, engine status, and recording state.

Below that, the processing pipeline. Every recording moves through Phase 0 (queue), Phase 1 (frame extraction + stat analysis), and Phase 2 (narrative + highlight clips). Each recording in the queue shows its pipeline progress and current status.

![DETECT.EXE — Live Capture](docs/screenshots/detect_exe.png)

---

## Under the Hood

### Capture Engine
- **Rust binary** (`runlog-recorder.exe`) — Windows Graphics Capture API, zero-copy GPU pipeline
- **MediaFoundation encoding** — 60fps at native 4K, HEVC or H.264 (configurable)
- **Privacy-safe** — captures only the Marathon window, never the desktop
- **OCR state machine** — three scan regions detect deployment (start), RUN_COMPLETE (timestamp), and lobby (stop)
- **Per-phase screenshots** — READY UP, RUN, DEPLOYING phases captured for shell/loadout identification

### Two-Phase AI Analysis
- **Phase 1 (Stats, ~60s):** Three parallel Claude calls extract map, shell (facial geometry matching), spawn coordinates, plus a sequential call for kills, deaths, loot, weapons, damage contributors from end-of-run screenshots
- **Phase 2 (Narrative, ~10min):** Chain-of-thought video analysis — scene inventory, event identification, then grade + summary + highlight timestamps. Clips cut via stream copy from original 4K footage

### Highlight Clips
- Auto-generated from Phase 2 — every PvP kill, death, revive, and extraction clipped
- Chain-of-thought prompting reduces hallucinated clips
- Custom clip editor with IN/OUT markers on any video
- Stream copy from original footage — no re-encoding, instant cuts
- Sprite sheets for hover scrub preview on every clip

---

## Tech Stack

| Layer | Tech |
|---|---|
| Desktop | Electron |
| Frontend | React + TypeScript + Vite |
| Styling | Tailwind CSS |
| State | Zustand |
| Charts | Recharts |
| Backend | Python FastAPI |
| Database | SQLite (local-first, auto-backup) |
| AI | Claude API (Sonnet/Haiku) or Claude CLI |
| Capture | Rust (WGC + MediaFoundation HEVC/H.264) |
| OCR | EasyOCR |
| Video | FFmpeg |

---

## Getting Started

### Prerequisites
- Windows 10/11
- Python 3.12+
- Node.js 18+
- FFmpeg on PATH
- Rust toolchain (for building recorder) or pre-built binary

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
Two options — configure in SYS.CONFIG:
1. **API Key** — Paste your Anthropic API key, tested before saving
2. **Claude CLI** — Install Claude Code (`npm install -g @anthropic-ai/claude-code`), run `claude login`. Uses your Claude subscription, no API tokens needed.

### Development
```bash
# Terminal 1
cd backend && RUNLOG_DEV=1 python run.py

# Terminal 2
cd frontend && npm run electron:dev
```

### Build
```bash
cd frontend && npm run dist
# Output in ../release/
```

---

## Local-First

- All data stored locally: `%APPDATA%/runlog/marathon/data/`
- No accounts, no cloud sync, no telemetry
- Automatic database backups on startup (keeps last 7)
- Works offline for everything except AI analysis
- Your API key stays on your machine

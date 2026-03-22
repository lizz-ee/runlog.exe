# runlog.exe

A local-first desktop companion for **Marathon** (Bungie, 2026). Play your runs, stats appear automatically.

**Powered by Claude** — records your gameplay with a zero-copy GPU capture engine, extracts stats with AI vision, generates highlight clips, grades your performance, and builds a comprehensive dashboard over time. No manual data entry, no accounts, no cloud.

---

## How It Works

```
1. Launch runlog.exe — sits in your system tray
2. Launch Marathon — detected automatically via Windows Graphics Capture
3. Play normally — recording starts when you deploy, stops when you return to lobby
4. Stats extracted in ~60s (kills, deaths, loot, map, spawn, shell, loadout)
5. Narrative report + highlight clips generated asynchronously
6. Dashboard, maps, and run history update in real-time
```

---

## TERMINAL

The dashboard. Career stats at a glance — total runs, survival rate, K/D, total play time. Favorites column shows your most-used shell, weapon, map, and squad mate. Economy tracks total loot, average per run, best and worst. Recent runs at the bottom, vault value chart tracking your wealth over time.

![TERMINAL — Dashboard](docs/screenshots/terminal.png)

---

## RUN.LOG

Every run, chronologically. Filter by outcome, grade, map, ranked mode, or favorites. Each row shows shell, map, summary snippet, PvE/PvP kills, deaths, revives, loot delta, duration, and letter grade. Expand any row for full details — squad, weapons, inventory value change, killed-by with damage contributors, AI debrief narrative, and highlight clips with sprite sheet hover scrub. Custom clip editor with draggable IN/OUT markers built into every video.

![RUN.LOG — Run History](docs/screenshots/run_log.png)

Expand any run for the full breakdown — date, squad, weapons, inventory delta, survival status, highlight clips with sprite sheet hover scrub, full video player with custom clip editor (IN/OUT markers, loop, create clip), and the AI-generated debrief narrative.

![RUN.LOG — Expanded Run](docs/screenshots/run_log_expanded.png)

---

## NEURAL.LINK

Two sections: **Shells** and **Runners**.

**Shells** — all 7 Marathon character classes with performance cards and weighted scoring. Per-shell stats: runs, survival rate, K/D, avg loot, combat breakdown, economy.

**Runners** — your top 7 squad mates ranked by weighted score. Per-mate stats show how your survival rate and loot change when you play together. Marathon-themed art on each card.

![NEURAL.LINK — Shells + Squad](docs/screenshots/neural_link.png)

---

## MAPS

Interactive spawn heatmaps for each map. Draggable markers show per-spawn stats — survival rate, win streak, avg loot, best/worst loot, favorite weapon and shell at that spawn, and who killed you there. Spawn coordinates extracted from the deployment loading screen via Claude Vision, fuzzy-matched to known locations. New spawns auto-detected and staged for positioning.

![PERIMETER — Spawn Heatmap](docs/screenshots/perimeter.png)

![DIRE MARSH — Spawn Heatmap](docs/screenshots/dire_marsh.png)

---

## UPLINK

AI tactical advisor. Auto-generated session briefings with trend analysis and alerts. Charts track survival rate, loot extracted, and runner eliminations across sessions. Terminal-style chat interface — ask UPLINK anything about your stats. Backed by 12 read-only database tools, separate model selection (Haiku for speed, Sonnet for depth).

![UPLINK — AI Tactical Advisor](docs/screenshots/uplink.png)

---

## DETECT.EXE

Live capture monitor. Shows the game window feed with OCR scan regions visualized (deploy, endgame, lobby). Engine status, recording state, and the full processing pipeline — Phase 0 (queue), Phase 1 (frames + stats), Phase 2 (narrative + clips). Processing queue shows each recording with pipeline progress shapes and real-time status. P2 worker gating ensures only 2 narrative analyses run concurrently.

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

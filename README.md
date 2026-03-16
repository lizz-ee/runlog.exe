# MARATHON RUNLOG

A desktop companion app for **Marathon** (Bungie, 2026). Drop a screenshot, get your stats.

---

## What Is This?

RunLog is a local-first desktop app that tracks your Marathon extraction runs using **screenshot parsing**. No manual data entry, no API keys, no accounts. Just screenshot your results screen, drop it in, and your stats build up over time.

**Powered by Claude Vision** — the app sends your end-of-match screenshot to Claude's vision API, which reads the game UI and extracts structured match data automatically.

---

## How It Works

```
1. Play a Marathon run
2. Screenshot the results screen (Win+Shift+S)
3. Drop / paste it into RunLog
4. Claude Vision extracts: kills, deaths, loot, survival, map, duration
5. You confirm or tweak the parsed data
6. Stats saved locally — dashboard updates
```

---

## Core Features

### Screenshot-Powered Run Logging
- **Drag & drop** or **Ctrl+V paste** screenshots directly into the app
- Claude Vision parses the end-of-match results screen
- Pre-filled form lets you confirm or correct extracted data
- Supports results screen + loadout screen screenshots

### Run History
- Chronological log of all your extraction runs
- Filter by map, runner, outcome (extracted/died), date range
- Search and sort across your full history

### Loadout Tracking
- Screenshot your loadout screen before a run
- Weapons, mods, and gear parsed and stored
- Link loadouts to specific runs (before/after pairing)
- Save and name favorite loadouts

### Stats Dashboard
- **Survival rate** — how often you extract vs. die
- **K/D ratio** — overall and per-map
- **Loot value** — total extracted value over time
- **Weapon performance** — kills per weapon across runs
- **Map breakdown** — your stats per map
- **Trends** — performance over time (daily/weekly/monthly graphs)
- **Session tracking** — group runs into play sessions

### Runner Profiles
- Track stats per Runner (character class)
- See which Runners you perform best with
- Loadout history per Runner

---

## Tech Stack

| Layer      | Tech                              |
|------------|-----------------------------------|
| Desktop    | Electron 28                       |
| Frontend   | React 19 + TypeScript + Vite      |
| Styling    | Tailwind CSS                      |
| State      | Zustand                           |
| Animation  | Framer Motion                     |
| Backend    | Python FastAPI + Uvicorn          |
| Database   | SQLite (local-first)              |
| AI/Vision  | Anthropic Claude API (Vision)     |
| Images     | Pillow                            |

---

## Data Models

### Runner
A Marathon character class the player uses.
- `id`, `name`, `icon`, `notes`

### Weapon
A weapon in Marathon.
- `id`, `name`, `type` (primary/secondary/heavy), `notes`

### Loadout
A saved combination of weapons, mods, and gear.
- `id`, `name`, `runner_id`, `primary_weapon`, `secondary_weapon`, `heavy_weapon`
- `mods`, `gear`, `notes`, `screenshot_path`, `created_at`

### Run
A single extraction run / match.
- `id`, `runner_id`, `loadout_id`, `map`, `date`
- `survived` (boolean — did you extract?)
- `kills`, `deaths`, `assists`
- `loot_extracted` (JSON — list of items/values)
- `loot_value_total` (calculated total)
- `duration_seconds`
- `squad_size`, `squad_members`
- `screenshot_path` (the results screen image)
- `notes`, `created_at`

### Session
A group of runs played in one sitting.
- `id`, `started_at`, `ended_at`, `notes`
- Links to multiple Runs

---

## Architecture

```
┌─────────────────────────────────────────┐
│           Electron Desktop App          │
│  ┌───────────────────────────────────┐  │
│  │     React Frontend (Vite)         │  │
│  │                                   │  │
│  │  ┌─────────┐  ┌───────────────┐   │  │
│  │  │Drop Zone│  │  Stats Dash   │   │  │
│  │  │ (paste/ │  │  (charts,     │   │  │
│  │  │  drag)  │  │   graphs)     │   │  │
│  │  └────┬────┘  └───────────────┘   │  │
│  │       │                           │  │
│  │  ┌────▼────┐  ┌───────────────┐   │  │
│  │  │Confirm  │  │  Run History  │   │  │
│  │  │ Form    │  │  (list/filter)│   │  │
│  │  └────┬────┘  └───────────────┘   │  │
│  └───────┼───────────────────────────┘  │
│          │ HTTP                          │
│  ┌───────▼───────────────────────────┐  │
│  │     FastAPI Backend               │  │
│  │                                   │  │
│  │  /api/parse-screenshot            │  │
│  │     → Claude Vision API           │  │
│  │     → returns structured JSON     │  │
│  │                                   │  │
│  │  /api/runs      (CRUD)            │  │
│  │  /api/loadouts  (CRUD)            │  │
│  │  /api/runners   (CRUD)            │  │
│  │  /api/stats     (aggregations)    │  │
│  │                                   │  │
│  │  SQLite ─── local .db file        │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

---

## API Endpoints

### Screenshot Parsing
- `POST /api/parse-screenshot` — Upload screenshot, returns parsed match data via Claude Vision

### Runs
- `GET /api/runs` — List all runs (with filters)
- `POST /api/runs` — Create a new run
- `GET /api/runs/{id}` — Get run details
- `PUT /api/runs/{id}` — Update a run
- `DELETE /api/runs/{id}` — Delete a run
- `GET /api/runs/recent` — Last N runs

### Loadouts
- `GET /api/loadouts` — List saved loadouts
- `POST /api/loadouts` — Save a new loadout
- `GET /api/loadouts/{id}` — Get loadout details
- `PUT /api/loadouts/{id}` — Update a loadout
- `DELETE /api/loadouts/{id}` — Delete a loadout

### Runners
- `GET /api/runners` — List runners
- `POST /api/runners` — Add a runner
- `GET /api/runners/{id}` — Get runner details + stats

### Stats
- `GET /api/stats/overview` — Global stats (survival rate, K/D, total runs)
- `GET /api/stats/by-map` — Stats broken down by map
- `GET /api/stats/by-runner` — Stats broken down by runner
- `GET /api/stats/by-weapon` — Weapon performance stats
- `GET /api/stats/trends` — Performance over time (daily/weekly)
- `GET /api/stats/sessions` — Session-grouped stats

---

## Screenshots the App Parses

### End-of-Match Results Screen
The main input. Claude Vision extracts:
- Kill count, death count, assists
- Whether you survived / extracted
- Map name
- Match duration
- Loot summary (items + values)

### Loadout Screen (Optional)
Screenshot your loadout before a run:
- Runner class
- Primary, secondary, heavy weapons
- Mods and gear equipped

---

## Getting Started

### Prerequisites
- Python 3.11+
- Node.js 18+
- Anthropic API key (for Claude Vision)

### Setup
```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env  # Add your ANTHROPIC_API_KEY
python run.py

# Frontend
cd frontend
npm install
npm run dev
```

### Launch
```bash
# Or use the launcher
./LAUNCH.bat
```

---

## Local-First Philosophy

- All data stored in a local SQLite database
- Screenshots saved locally in `backend/media_uploads/`
- No accounts, no cloud sync, no telemetry
- Your Anthropic API key is the only external dependency
- Works offline for everything except screenshot parsing

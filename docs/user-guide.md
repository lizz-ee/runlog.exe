# runlog.exe — User Guide

A complete guide to using runlog.exe, the local-first desktop companion for Marathon (Bungie, 2026).

---

## Table of Contents

1. [Installation](#installation)
2. [First Launch & Setup](#first-launch--setup)
3. [How It Works](#how-it-works)
4. [TERMINAL — Dashboard](#terminal--dashboard)
5. [RUN.LOG — Run History](#runlog--run-history)
6. [NEURAL.LINK — Shells & Squad](#neurallink--shells--squad)
7. [Maps — Spawn Heatmaps](#maps--spawn-heatmaps)
8. [UPLINK — AI Tactical Advisor](#uplink--ai-tactical-advisor)
9. [DETECT.EXE — Live Capture](#detectexe--live-capture)
10. [SYS.CONFIG — Settings](#sysconfig--settings)
11. [Highlight Clips](#highlight-clips)
12. [Data & Privacy](#data--privacy)
13. [Troubleshooting](#troubleshooting)

---

## Installation

### Prerequisites

- Windows 10 or 11
- Marathon (Bungie, 2026)
- An Anthropic API key **or** Claude CLI installed

### Install from Release

1. Download `runlog-1.0.0.exe` from [GitHub Releases](https://github.com/lizz-ee/runlog.exe/releases).
2. Run the installer.
3. runlog.exe launches into your system tray — all dependencies are bundled.

### Install from Source (Development)

**Requirements:** Python 3.12+, Node.js 18+, FFmpeg on PATH, Rust toolchain (optional).

```bash
# Backend
cd backend
pip install -r requirements.txt

# Build Rust recorder (optional — pre-built binary included)
cd recorder && cargo build --release && cd ..

# Frontend
cd frontend
npm install
```

**Run in development mode:**

```bash
# Terminal 1 — Backend
cd backend && RUNLOG_DEV=1 python run.py

# Terminal 2 — Frontend
cd frontend && npm run electron:dev
```

**Build installer:**

```bash
cd frontend && npm run dist
# Output in ../release/
```

---

## First Launch & Setup

runlog.exe is powered by Claude AI — authentication is the first thing you should set up. Without it, the app can record gameplay but can't extract stats, generate grades, write narratives, or cut highlight clips. In other words, it needs Claude to do its job.

1. **Launch runlog.exe** — the app icon appears in your system tray.
2. **Open the app** — click the tray icon or double-click to open the main window.
3. **Navigate to SYS.CONFIG** — the settings page in the left sidebar.
4. **Set up authentication** — choose one or both methods:

### Option A: API Key

1. Get an API key from [console.anthropic.com](https://console.anthropic.com) (starts with `sk-ant-`).
2. Paste it into the API Key field on the left panel of SYS.CONFIG.
3. Click **TEST & SAVE** — the app makes a test API call to verify the key works, then saves it only if the test passes.
4. Status indicator turns green with "ACTIVE" when saved.
5. To remove a saved key, click **REMOVE**.

Your key is stored locally at `%APPDATA%/runlog/settings.json` and is only ever sent to the Anthropic API. It's displayed masked in the UI (first 7 + last 4 characters).

### Option B: Claude CLI

This method uses your Claude subscription through the Claude Code CLI — no API tokens or credits needed.

1. Install Claude Code: `npm install -g @anthropic-ai/claude-code`
2. Authenticate in your terminal: `claude login` (this opens a browser for OAuth — **this step happens outside the app**).
3. In SYS.CONFIG, check the right panel — click **CHECK** to verify the app detects your CLI installation.
4. Status shows green "CONNECTED" with the path to the CLI binary if found.

The app searches for the `claude` binary on your system PATH and common install locations (`~/.local/bin/claude`, `~/AppData/Local/Programs/claude/claude.exe`). There is no login flow inside the app itself — authentication is handled entirely by the CLI.

### Using Both

You can have both an API key and CLI configured simultaneously. The app automatically picks the best method depending on the task:

| Feature | Prefers | Falls back to |
|---|---|---|
| Phase 1 (stats extraction) | API Key | CLI |
| Phase 2 (narrative + clips) | CLI | API Key |
| UPLINK chat | API Key | CLI |
| Screenshot parsing | CLI | API Key |

If only one method is configured, the app uses that for everything.

Once at least one auth method is set up, you're ready to go. Launch Marathon and play.

---

## How It Works

runlog.exe is fully automatic. Here's what happens during a typical session:

1. **Launch runlog.exe** — sits in your system tray, backend starts automatically.
2. **Launch Marathon** — runlog detects the Marathon window via Windows Graphics Capture.
3. **Ready up** — when the READY UP screen appears, runlog saves a screenshot of your loadout.
4. **Deploy** — when the deployment loading screen appears (map name visible), recording starts automatically.
5. **Play your run** — runlog records the entire run in the background at 60fps, up to native 4K.
6. **Run ends** — when RUN_COMPLETE appears, the endgame timestamp is logged. When you return to the lobby (PREPARE button visible), recording stops.
7. **Processing begins** — the recording is queued for two-phase AI analysis:
   - **Phase 1 (1–2 minutes):** Stats extracted — kills, deaths, loot, map, spawn, shell, loadout, squad. Your run appears in the app immediately.
   - **Phase 2 (~10 minutes):** Full video analysis — letter grade (S through F), narrative summary, and auto-generated highlight clips.
8. **Dashboard updates** — TERMINAL, RUN.LOG, maps, and NEURAL.LINK all reflect the new data automatically.

No manual data entry. No clicking "record." Just play.

---

## TERMINAL — Dashboard

**Sidebar label:** TERMINAL

Your career command center. Everything at a glance.

### Core Stats (top row)

- **Total Runs** — lifetime run count
- **Survival Rate** — percentage of runs where you extracted (vs KIA)
- **K/D Ratio** — kills to deaths across all runs
- **Total Time** — cumulative play time

### Favorites (left column)

- **Shell** — your most-used character class
- **Weapon** — your most-used weapon
- **Map** — your most-played map
- **Squad Mate** — the player you've run with the most

### Economy (right column)

- **Total Loot** — lifetime loot extracted
- **Average Per Run** — mean loot value per run
- **Best Run** — your highest loot haul
- **Worst Run** — your lowest (or biggest loss)

### Recent Runs (center)

A feed of your latest runs, each showing key stats. Click to expand for full details, clips, and the AI debrief.

### Vault Value Chart (bottom)

A line chart tracking your total vault value over time — see your wealth trend across your career.

---

## RUN.LOG — Run History

**Sidebar label:** RUN.LOG

Your complete run-by-run history with powerful filtering.

### Filters

Filters stack — combine any of these to narrow your view:

- **Outcome** — Survived or KIA
- **Grade** — S, A, B, C, D, or F
- **Map** — Perimeter, Dire Marsh, Outpost
- **Ranked Mode** — ranked vs unranked
- **Favorites** — runs you've starred

### Run Table

Each row shows:

| Column | Description |
|---|---|
| Shell | Character class used |
| Map | Map played |
| Spawn | Spawn location |
| PvE Kills | Combatant kills |
| PvP Kills | Runner eliminations |
| Deaths | Times killed |
| Loot | Net loot gained or lost |
| Duration | Run length |
| Grade | AI-assigned letter grade (S–F) |

### Expanded Run View

Click any run to expand it. The expanded view shows:

- **Squad composition** — who you played with
- **Weapons used** — primary and secondary
- **Inventory value change** — loot breakdown
- **Death breakdown** — who killed you, with what weapon, and all damage contributors
- **Highlight clips** — auto-generated clips with sprite sheet hover scrub (hover over the thumbnail to scrub through frames)
- **Custom clip editor** — set IN/OUT markers on any video, name your clip, and cut instantly via stream copy from the original 4K footage
- **AI debrief** — the narrative summary and letter grade explanation

### Actions

- **Star** — mark a run as favorite (click the star icon)
- **Mark viewed** — runs are flagged as new until you view them

---

## NEURAL.LINK — Shells & Squad

**Sidebar label:** NEURAL.LINK

Two tabs analyzing your performance by character class and squad composition.

### Shells Tab

All 7 Marathon shells ranked by a weighted performance score:

- **Triage, Assassin, Recon, Vandal, Destroyer, Thief, Rook**

Per-shell breakdown:

- Runs played
- Survival rate
- K/D ratio
- Average loot
- Combat breakdown (PvE vs PvP kills)
- Economy (loot trends)

Use this to find which shell fits your playstyle — or which one you should stop using.

### Squad Tab (Runners)

Your top 7 squad mates ranked by how they affect your stats:

- Runs played together
- Survival rate change vs your solo baseline
- Loot impact (do you earn more or less with them?)
- K/D change

This shows who actually makes you better — and who might be dragging you down.

---

## Maps — Spawn Heatmaps

**Sidebar labels:** PERIMETER, DIRE MARSH, OUTPOST

Each map has its own dedicated page with interactive spawn data.

### Map Stats (top)

- Total runs on this map
- Survival rate
- K/D ratio
- Total time played

### Interactive Map

A visual map with draggable spawn markers. Each marker represents a spawn point where you've deployed.

**Hover a spawn marker** to see per-spawn stats:

- Survival rate at this spawn
- Current win streak
- Average loot
- Kill counts (PvE and PvP)
- Favorite weapon at this spawn
- Favorite shell at this spawn
- Top enemy encountered

### Uncharted Spawns

When you deploy from a spawn location the app hasn't seen before, it appears as an uncharted marker (`VCTR//...`) in the top-left staging area.

To place it:

1. **Drag** the uncharted marker from the staging bracket onto the correct position on the map.
2. **Rename** it — give it a meaningful name.
3. **Save** — future runs with matching coordinates will automatically log to this spawn.

### Spawn List

Below the map, a scrollable list of all spawns, sortable by:

- Name
- Survival rate
- Average loot
- Win streak

### Map Breakdowns

Detailed stat panels covering:

- Favorites (most-used shell, weapon at this map)
- Economy (loot trends)
- Combat (kill/death patterns)
- Time (play time by spawn)

### CRYO ARCHIVE

A fourth map listed in the sidebar, currently redacted/disabled — reserved for future Marathon content.

---

## UPLINK — AI Tactical Advisor

**Sidebar label:** UPLINK

Your personal AI analyst and session tracker.

### Sessions

Every time you launch the app and play, a new session is created. Sessions are labeled with codes like `:01A:`, `:01B:`, `:02A:`, etc.

### Session Briefing

UPLINK auto-generates a briefing for each session:

- Number of runs played this session
- Session survival rate
- Trends vs your career baseline
- Alerts when you're performing significantly above or below average

### Performance Charts

Three charts tracking your performance across sessions:

- **Survival rate** over time
- **Loot** per session
- **Runner eliminations** per session

### Chat Interface

A terminal-style chat where you can ask UPLINK anything about your stats:

- *"What's my best map?"*
- *"How do I perform with Recon vs Assassin?"*
- *"What's my survival rate this week?"*
- *"Who's my best squad mate?"*

UPLINK has direct access to your database and can query any stat, filter, or trend. Powered by Claude Haiku (fast, lightweight) by default — switch to Sonnet in SYS.CONFIG for more detailed analysis.

---

## DETECT.EXE — Live Capture

**Sidebar label:** DETECT.EXE

The real-time monitoring dashboard for the capture engine.

### Capture Status

- **Window Detection** — shows whether the Marathon window is found
- **Recording State** — active or stopped, with elapsed time
- **Live Frame** — a real-time preview of what the capture engine sees (the current Marathon frame)

### Processing Pipeline

Each recording moves through 5 stages, visualized in real time:

```
QUEUED → FRAMES → STATS → GAMEPLAY → CLIPS
```

1. **QUEUED** — recording saved, waiting for a worker
2. **FRAMES** — extracting key frames from the video
3. **STATS** — Phase 1 AI analysis (kills, deaths, loot, map, shell)
4. **GAMEPLAY** — Phase 2 AI analysis (narrative, grade, highlight identification)
5. **CLIPS** — cutting highlight clips from the original footage

### Processing Queue

Shows all recordings currently being processed:

- Thumbnail preview
- Phase progress (P1: Stats, P2: Narrative + Clips)
- Status flags (phase 1 done, phase 2 done, or failed)
- Timing (when processing started, how long each phase took)

### Worker Concurrency

- **Phase 1** runs up to 4 workers in parallel (fast, ~1–2 minutes each)
- **Phase 2** runs up to 2 workers in parallel (heavy, ~10 minutes each)

You can adjust worker counts in SYS.CONFIG.

---

## SYS.CONFIG — Settings

**Sidebar label:** SYS.CONFIG

All app configuration in one place.

### Authentication

Choose your AI provider:

| Method | Description |
|---|---|
| **API Key** | Paste your Anthropic API key. Click TEST to validate, then SAVE. Key is stored locally and displayed masked. |
| **Claude CLI** | Uses your Claude Code subscription. No API tokens needed. App auto-detects the CLI installation. |

### Recording

| Setting | Options | Default |
|---|---|---|
| Encoder | HEVC (better quality) or H.264 (wider compatibility) | HEVC |
| Bitrate | 1–100 Mbps | 50 Mbps |
| FPS | 30 or 60 | 60 |

### AI Models

| Setting | Options | Default |
|---|---|---|
| Phase 1/2 Model | Sonnet (more capable) or Haiku (faster, cheaper) | Sonnet |
| UPLINK Model | Haiku (faster) or Sonnet (more detailed) | Haiku |

### Processing Workers

| Setting | Range | Default |
|---|---|---|
| P1 Workers | 1–8 | 4 |
| P2 Workers | 1–4 | 2 |

More workers = faster processing of multiple runs, but higher CPU/API usage.

### Overlay (In-Game HUD)

An optional overlay that appears on top of Marathon while you play.

| Setting | Options | Default |
|---|---|---|
| Enabled | On / Off | Off |
| Corner | Top-left, Top-center, Top-right, Bottom-left, Bottom-center, Bottom-right | — |
| Size | Small (250px), Medium (290px), Large (360px) | Medium |
| Opacity | 0–100% | 88% |
| Custom Position | Drag to set X/Y coordinates | — |
| Close When Done | Auto-close overlay when processing queue empties | Off |

The overlay shows recording status and run state while you play, so you can confirm the app is working without alt-tabbing.

---

## Highlight Clips

runlog.exe auto-generates highlight clips from every run during Phase 2 processing.

### What Gets Clipped

- Every PvP kill (runner elimination)
- Every death
- Revives
- Extractions

### Viewing Clips

Clips appear in the expanded run view in RUN.LOG. Each clip has:

- **Sprite sheet thumbnail** — hover to scrub through frames without loading the video
- **Video player** — click to play the full clip

### Custom Clip Editor

Want to clip a moment the AI didn't catch? Use the built-in editor:

1. Open a run's expanded view.
2. Open the clip editor.
3. Set your **IN** point (start time).
4. Set your **OUT** point (end time).
5. Name the clip.
6. Click cut — the clip is created instantly via stream copy from the original 4K footage (no re-encoding, no quality loss).

### Clip Storage

Clips are stored locally at:

```
%APPDATA%/runlog/marathon/data/clips/run_xxx/
```

---

## Data & Privacy

runlog.exe is local-first. Your data never leaves your machine (except for AI API calls to process screenshots and video).

### What's Stored Locally

| Data | Location |
|---|---|
| Database | `%APPDATA%/runlog/marathon/data/runlog.db` |
| Recordings | `%APPDATA%/runlog/marathon/data/` |
| Clips | `%APPDATA%/runlog/marathon/data/clips/` |
| Settings | `%APPDATA%/runlog/settings.json` |
| Backups | `%APPDATA%/runlog/marathon/data/backups/` |

### Backups

The database is automatically backed up every time the app starts. The last 7 backups are kept. Older backups are deleted automatically.

### Privacy

- **No accounts** — no signup, no login, no user tracking.
- **No cloud sync** — all data stays on your machine.
- **No telemetry** — the app sends nothing home.
- **Window-only capture** — the Rust recorder captures only the Marathon window, never your desktop or other apps.
- **API key stays local** — stored in your local settings file, never transmitted anywhere except to the Anthropic API for processing.
- **Works offline** — everything works without internet except AI analysis (which requires API access).

### What's Sent to the AI

When processing a run, the following is sent to the Anthropic API:

- Screenshots of your loadout, deployment, and end-of-run stats screens
- Video frames from your gameplay (for Phase 2 narrative analysis)

No personal information, account data, or system data is included.

---

## Troubleshooting

### Marathon not detected

- Make sure Marathon is running and visible (not minimized).
- runlog uses Windows Graphics Capture, which requires the game window to be active.
- Check DETECT.EXE — the window detection status should show "Marathon found."

### Recording doesn't start

- The capture engine waits for the deployment loading screen (map name visible in the center of the screen).
- Make sure you're past the READY UP screen and actually deploying into a run.
- Check DETECT.EXE for the current OCR state.

### Recording doesn't stop

- The engine stops when it detects the PREPARE button in the lobby.
- If the lobby UI changes or is obscured, detection may be delayed.
- You can manually stop capture from DETECT.EXE or the system tray.

### Stats not appearing

- Check that authentication is configured in SYS.CONFIG (API key tested or CLI detected).
- Check the processing queue in DETECT.EXE — your run should appear as QUEUED or in progress.
- Phase 1 takes 1–2 minutes. If it's been longer, check for errors in the queue.

### Phase 2 taking too long

- Phase 2 (narrative + clips) takes approximately 10 minutes per run.
- Only 2 Phase 2 workers run at a time by default. If you have many runs queued, they process sequentially.
- Increase P2 workers in SYS.CONFIG if your API rate limits allow it.

### Clips not generating

- Clips require Phase 2 to complete.
- FFmpeg must be installed and on your system PATH.
- Check the processing queue in DETECT.EXE for errors at the CLIPS stage.

### Uncharted spawns appearing

- This is normal. When you deploy from a new location, it appears as an uncharted marker (`VCTR//...`).
- Drag it to the correct position on the map page and rename it.
- Future runs at those coordinates will match automatically.

### API key not working

- Make sure you're using an Anthropic API key (starts with `sk-ant-`).
- Use the TEST button in SYS.CONFIG to validate it.
- Check that you have sufficient API credits.

### App won't start

- Make sure no other instance is running (check your system tray).
- The backend runs on port 8000 — make sure nothing else is using that port.
- For development mode, ensure Python 3.12+ and Node.js 18+ are installed.

### Database issues

- The database auto-backs up on every startup (last 7 kept).
- Backups are at `%APPDATA%/runlog/marathon/data/backups/`.
- If your database is corrupted, replace `runlog.db` with a recent backup.

---

## Keyboard & Navigation

- Use the **left sidebar** to navigate between all pages.
- The sidebar is divided into sections: **SYSTEM** (Terminal, Run.Log, Neural.Link), **MAPS** (Perimeter, Dire Marsh, Outpost, Cryo Archive), **LIVE** (Uplink, Detect.exe), and **CONFIG** (Sys.Config).
- **Window controls** are in the top-right corner: minimize, maximize, close.
- The app runs in the **system tray** — closing the window doesn't stop the capture engine.

---

## Quick Reference

| What you want | Where to go |
|---|---|
| See career stats | TERMINAL |
| Browse all runs | RUN.LOG |
| See which shell is best | NEURAL.LINK → Shells |
| See who to squad with | NEURAL.LINK → Runners |
| Check spawn stats on a map | MAPS → (select map) |
| Ask the AI about your stats | UPLINK → Chat |
| Check if recording is working | DETECT.EXE |
| Change API key or settings | SYS.CONFIG |
| Watch highlight clips | RUN.LOG → expand a run |
| Create a custom clip | RUN.LOG → expand a run → clip editor |
| Place an uncharted spawn | MAPS → drag marker from staging area |

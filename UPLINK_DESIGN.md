# UPLINK — Design Document

## Identity
**Nav position:** LIVE section (renamed from CAPTURE), below RUN REPORTS
**Page label:** `LIVE // UPLINK`
**Page title:** `UPLINK`
**Purpose:** Living AI intel page — auto-generated briefings, trend charts, conversational chat. Changes every session.
**Layout:** Concept B — two-column split (60/40). Intel panels left, chat right.

---

## Sessions

A **session** = one runlog.exe app lifecycle. App opens → session starts. App closes → session ends. Simple, unambiguous.

- Sessions are tracked in the DB with a session ID, start timestamp, and end timestamp
- All runs recorded while the app is open belong to that session
- The SESSION DEBRIEF and BRIEFING panels reference the latest session
- Chart x-axis groups data by session (S.01, S.02, ...)
- If the user closes and reopens the app, that's a new session — even if it's 2 minutes later

---

## Briefing Generation

**Auto-generates on page load.** No button, no clicks. Navigate to UPLINK and it fires.

**Loading sequence:**
1. Hero stats appear instantly (pure DB query)
2. Briefing panel shows skeleton state: `████████ ████ ██████████` redacted-style placeholder blocks with scanline overlay animating over them — looks like classified data being decrypted
3. Haiku generates the briefing (2-4 seconds)
4. Text streams in character by character, replacing the skeleton

**Caching:** If you revisit UPLINK during the same app session and no new runs have been processed since the last briefing, serve the cached version — no repeat AI call.

---

## Empty State (new user, zero runs)

When there's no data to show, the entire page displays a centered empty state:

```
INSUFFICIENT DATA
Complete runs to activate UPLINK.
```

- `INSUFFICIENT DATA` — `text-sm font-mono text-m-text-muted`
- Subtext — `text-xs font-mono text-m-text-muted`
- No hero stats, no briefing, no charts, no chat
- Once the first run is processed, the page fully activates

---

## AI Personality

The AI is not a generic chatbot. It's a tactical handler — mission control for your runs. It belongs in the Marathon universe.

**Voice rules:**
- Terse, military-tactical tone. No filler, no pleasantries, no "Great question!"
- Data-first — leads with numbers, follows with interpretation
- Uses the app's language: "extraction," "runner," "shell" — never "character," "class," "match"
- Addresses the user as "Runner"
- Short paragraphs. No bullet lists in responses unless comparing data
- Can surface alerts or warnings unprompted in briefings

**Example responses:**

> **Runner:** How am I doing on Outpost?
>
> **UPLINK:** Outpost. 19 runs logged. 32% survival — your lowest across all maps. South spawns are the problem — 2 extractions out of 9. You're dying to long-range engagements within the first 90 seconds. North spawns sit at 58% survival. Consider adjusting your approach from the south side, Runner.

> **Runner:** What's my best shell?
>
> **UPLINK:** Triage. 67% survival across 31 runs. Nearest competitor is Warlock at 44%. Triage also leads in avg loot extracted — 14,200 per run vs 8,900 overall. It's not close.

> **Runner:** Am I getting better?
>
> **UPLINK:** Last 10 sessions vs prior 10: survival up 8%, avg runner kills up 1.3 per run, loot per extraction up 22%. The trend is positive. Dire Marsh is the outlier — performance there is flat.

---

## Page Layout — Concept B (Two-Column Split)

```
┌─────────────────────────────────────────────────────────────────┐
│  LIVE // UPLINK                                                 │
│  UPLINK                                                         │
├──────────────────────────────────────┬──────────────────────────┤
│  LEFT COLUMN (60%) — scrollable      │  RIGHT COLUMN (40%)      │
│                                      │  fixed height, no scroll │
│  ┌────────┬────────┬────────┐        │                          │
│  │ RUNS   │ SURV.  │ R.KILL │        │  COMMS // UPLINK         │
│  │ 6      │ 50%    │ 23     │        │  ────────────────────    │
│  │ session│ 3 of 6 │ 3.8/rn │        │                          │
│  ├────────┼────────┼────────┤        │                          │
│  │ PVE    │ LOOT   │        │        │                          │
│  │ 47     │ 18,200 │        │        │    UPLINK ACTIVE         │
│  │ 7.8/rn │ extrd  │        │        │    Awaiting query,       │
│  └────────┴────────┴────────┘        │    Runner.               │
│                                      │                          │
│  BRIEFING // SESSION.07    MAR.19.26 │                          │
│  ┌────────────────────────────────┐  │                          │
│  │                                │  │                          │
│  │  6 runs processed. 3 exfils,   │  │                          │
│  │  3 eliminations. Triage on     │  │                          │
│  │  Perimeter was the standout —  │  │                          │
│  │  14 runner kills, clean exfil, │  │                          │
│  │  S-grade.                      │  │                          │
│  │                                │  │                          │
│  │  ■ TREND: Loot per extraction  │  │                          │
│  │  up 18% over last 3 sessions.  │  │                          │
│  │                                │  │                          │
│  │  ▲ ALERT: Deaths to sniper     │  │                          │
│  │  weapons up 40% this week.     │  │                          │
│  │  Concentrated on Outpost       │  │                          │
│  │  south spawns.                 │  │                          │
│  │                                │  │                          │
│  └────────────────────────────────┘  │                          │
│                                      │                          │
│  TRENDS // SURVIVAL    ▸ ALL MAPS ▾  │  ── after messages ──   │
│  ┌────────────────────────────────┐  │                          │
│  │ 80% ┤                          │  │       How's my Outpost   │
│  │     │          ╱╲              │  │        performance? ───  │
│  │ 60% ┤    ╱╲  ╱  ╲  ╱╲         │  │                          │
│  │     │╲  ╱  ╲╱    ╲╱  ╲  ╱╲    │  │  ── Outpost. 19 runs.   │
│  │ 40% ┤ ╲╱              ╲╱  ╲╱  │  │  32% survival — lowest   │
│  │     │                          │  │  across all maps. South  │
│  │ 20% ┤                          │  │  spawns are the problem: │
│  │     └──────────────────────    │  │  2 of 9 extracted.       │
│  │      S.01  S.03  S.05  S.07   │  │                          │
│  │                                │  │  You're dying to long    │
│  │  ── survival %   ── avg (52%) │  │  range in the first 90s. │
│  └────────────────────────────────┘  │  North spawns: 58%.      │
│                                      │  Adjust south approach,  │
│  TRENDS // LOOT         ▸ ALL MAPS ▾ │  Runner.                 │
│  ┌────────────────────────────────┐  │                          │
│  │ 18k ┤               ╱╲        │  │                          │
│  │ 14k ┤      ╱╲      ╱  ╲  ╱    │  │                          │
│  │ 10k ┤  ╱╲╱  ╲    ╱    ╲╱     │  │                          │
│  │  6k ┤╱       ╲╱╱              │  │                          │
│  │     └──────────────────────    │  │                          │
│  │      S.01  S.03  S.05  S.07   │  │                          │
│  └────────────────────────────────┘  │                          │
│                                      ├──────────────────────────┤
│                                      │ > query uplink...    [▶] │
├──────────────────────────────────────┴──────────────────────────┤
```

---

## Left Column — Panel Details

### SESSION DEBRIEF (hero stats)

Top of left column. Pure DB query, loads instantly — no AI needed.

**5 stat blocks** in `grid-cols gap-[1px] bg-m-border` pattern (same as Dashboard):

| Block | Label | Value | Context line |
|-------|-------|-------|-------------|
| RUNS | `label-tag text-m-text-muted` | `text-2xl font-mono font-bold text-m-green` | `text-xs text-m-text-muted` — "session" |
| SURVIVAL | same | same — show % | "3 of 6" (extracted / total) |
| R.KILLS | same | same | "3.8/run" (per-run average) |
| PVE.KILLS | same | same | "7.8/run" |
| LOOT | same | same — formatted number | "extracted" |

**Component:** Reuse `StatBlock` pattern from Dashboard. Data from `GET /api/uplink/session-summary`.

### BRIEFING // CURRENT

One panel below hero stats. AI-generated on page load via Haiku.

**Structure:**
```
┌──────────────────────────────────────────────┐
│ BRIEFING // SESSION.07               MAR.19.26│
│ ──────────────────────────────────────────── │
│                                              │
│ [2-3 lines session summary — what happened]  │
│                                              │
│ ■ TREND: [one positive or notable trend]     │
│                                              │
│ ▲ ALERT: [one concern or watch item]         │
│   (only if warranted — not forced)           │
│                                              │
└──────────────────────────────────────────────┘
```

**Style:**
- `bg-m-card border border-m-border`
- Header: label-tag `BRIEFING // SESSION.{n}` left, date right, both `text-m-text-muted`
- Body: `font-mono text-xs text-m-text`
- `■ TREND:` prefix in `text-m-green`
- `▲ ALERT:` prefix in `text-m-yellow` or `text-m-red` depending on severity
- Subtle scanline CSS overlay on the panel (same effect as DETECT.EXE feed)
- Optional: thin `border-l-2 border-m-green` left accent

**AI prompt context:** Session stats summary (run count, outcomes, maps, shells, kills, loot, grades). AI writes the narrative. Keep output to ~80 words max.

### TRENDS (charts)

Two line charts stacked below the briefing. No AI — pure DB queries rendered client-side.

**Chart 1: TRENDS // SURVIVAL**
- X-axis: sessions (S.01, S.02, ...) or dates
- Y-axis: survival % (0-100)
- Primary line: `m-green`
- Average line: dashed `m-text-muted`
- Grid lines: `m-border`
- Dropdown filter top-right: ALL MAPS / PERIMETER / DIRE MARSH / OUTPOST / CRYO ARCHIVE

**Chart 2: TRENDS // LOOT.EXTRACTED**
- X-axis: same session axis
- Y-axis: loot value (auto-scaled)
- Primary line: `m-green`
- Same dropdown filter

**Chart style:**
- `bg-m-card border border-m-border`
- Header: label-tag left, dropdown right
- Dark background, minimal grid, no fill under line (just the line)
- Hover: crosshair + tooltip with exact values
- Rendering: recharts or similar lightweight charting lib

**Future charts (can add later):**
- Runner kills per session
- Per-map survival comparison (multi-line)
- Loot trend by shell

---

## Right Column — Chat Details

### COMMS // UPLINK

Fixed-height column. Fills the right 40% of the page. Does not scroll with the left column — the chat has its own internal scroll.

**Layout (top to bottom):**
1. Header: `COMMS // UPLINK` label-tag
2. Message area: scrollable, flex-grow
3. Input bar: fixed at bottom

### Empty State

Centered in the message area when no messages exist:

```
UPLINK ACTIVE
Awaiting query, Runner.
```

- `UPLINK ACTIVE` — `text-sm font-mono text-m-green` with `animate-pulse-slow`
- `Awaiting query, Runner.` — `text-xs font-mono text-m-text-muted`

### Messages

**No avatars. No bubbles. No rounded chat UI.** This is a terminal, not iMessage.

**User messages:**
- Right-aligned text block
- `text-xs font-mono text-m-text`
- Thin `border-r-2 border-m-green` right accent
- Small `pr-3` padding from the accent line

**AI messages:**
- Left-aligned text block
- `text-xs font-mono text-m-text`
- Thin `border-l-2 border-m-text-muted` left accent (subtle, not green — distinguishes from user)
- Small `pl-3` padding from the accent line

**Message spacing:** `space-y-4` between messages.

**Streaming:** AI responses stream in character by character for the terminal feel. Cursor blink `█` at the end while streaming.

### Input Bar

Fixed at bottom of the right column.

```
┌──────────────────────────────┐
│ > query uplink...        [▶] │
└──────────────────────────────┘
```

- `bg-m-card border-t border-m-border`
- `>` prefix in `text-m-green font-mono`
- Input: `bg-transparent text-xs font-mono text-m-text` — no visible input border
- Placeholder: `query uplink...` in `text-m-text-muted`
- Send button: `▶` in `text-m-green`, or send on Enter
- Disabled state while AI is responding (input grayed, show streaming indicator)

---

## AI Identity

**Designation:** `██████-UPLINK`
**Clearance:** `[REDACTED]`

If asked its name, it does not break character:

> **Runner:** What's your name?
>
> **UPLINK:** Designation: ██████-UPLINK. Clearance details [REDACTED]. I process your operational data. That's what matters, Runner.

It's an intel system, not a person. It deflects identity questions back to the mission. Never breaks character.

---

## Technical Notes

### Architecture — Backend Gatekeeper

The AI (whether via API or CLI) never touches the DB, file system, or any system resource directly. The Python backend is the gatekeeper:

```
Frontend                    Backend                         AI (Haiku/Sonnet)
───────                    ───────                         ─────────────────
User sends message  ──→  POST /api/uplink/chat  ──→  Build prompt + tool defs
                                                          ──→  Send to AI (API or CLI)
                                                          ←──  AI responds or requests tool call
                         Execute tool function   ←──  "call get_stats_by_map('Perimeter')"
                         (safe, pre-built query)
                         Return result to AI     ──→  AI gets data, writes response
Stream response     ←──  Return final text       ←──  Final response
```

**This is the same flow for both API and CLI auth.** The AI never gets a DB connection, file path, or shell access. It only sees:
1. The system prompt (personality, instructions)
2. The conversation history
3. The tool definitions (names, parameters, descriptions)
4. The tool results (structured data returned by the backend)

**CLI is first-class, not a fallback.** Users who authenticate via `claude login` use their Claude subscription. The backend calls `claude` with the prompt and tool definitions — tool execution still happens in the backend, not in the CLI's environment.

### AI Calls
- **Page load:** One Haiku call to generate briefing from latest session stats
- **Chat messages:** One Haiku call per user message, with conversation context + tool access
- **Charts:** No AI needed — pure DB queries rendered client-side
- **Model:** Haiku by default, configurable to Sonnet in SYS.CONFIG (separate from processing model)

### Data Scope — Stats Only

The AI works from **structured database data only**. No media access.

**What the AI CAN access (via tools):**
- Run statistics (kills, deaths, loot, grades, outcomes)
- Map performance aggregates
- Shell performance aggregates
- Death/damage contributor data
- Weapon frequency and correlation data
- Performance trends over time
- Spawn point statistics
- Squad mate statistics
- Session summaries

**What the AI CANNOT access:**
- File system — no files, folders, or paths on the PC
- Screenshots, clips, or video files — no media of any kind
- Raw SQL — cannot construct or execute database queries
- Database writes — no INSERT, UPDATE, DELETE through any path
- Network/HTTP — cannot fetch URLs or reach external services
- Processes — cannot run shell commands, scripts, or spawn anything
- App settings — cannot read or modify SYS.CONFIG, API keys, or app configuration
- Recording pipeline — cannot start, stop, or modify recordings or processing
- Other apps or system resources — fully sandboxed to the tool definitions

### Tool Definitions (read-only)

These are the **only** functions the AI can call. Each runs a pre-built, parameterized query in the backend.

```
Tool: get_session_summary
  Description: Get stats summary for a play session
  Input:  { session_id?: number }  — optional, defaults to latest
  Output: { session_id, date, run_count, survival_rate,
            total_runner_kills, total_pve_kills, total_revives,
            total_loot, total_time_minutes, maps_played,
            shells_used, best_run: { grade, map, kills, loot } }

Tool: get_runs
  Description: Get filtered list of individual runs
  Input:  { map?: string, shell?: string, outcome?: "extracted"|"eliminated",
            last_n?: number, grade?: string, session_id?: number }
  Output: [{ run_id, date, map, shell, outcome, runner_kills, pve_kills,
             revives, loot, grade, squad_mates, spawn_point }]

Tool: get_stats_by_map
  Description: Get aggregate performance stats for a specific map
  Input:  { map_name: string }
  Output: { map, total_runs, survival_rate, avg_runner_kills, avg_pve_kills,
            avg_loot, best_run, worst_spawn, best_spawn,
            top_shell, top_weapon_died_to }

Tool: get_stats_by_shell
  Description: Get aggregate performance stats for a specific shell
  Input:  { shell_name: string }
  Output: { shell, total_runs, survival_rate, avg_runner_kills, avg_pve_kills,
            avg_loot, best_map, worst_map, favorite_primary, favorite_secondary }

Tool: get_death_stats
  Description: Get data about how the player dies
  Input:  { last_n?: number, map?: string, shell?: string }
  Output: { total_deaths, top_killers: [{ gamertag, kill_count }],
            top_weapons_died_to: [{ weapon, count }],
            damage_contributors: [{ gamertag, total_damage, encounters }],
            avg_survival_time_seconds }

Tool: get_weapon_stats
  Description: Get weapon usage frequency and performance correlation
  Input:  { }
  Output: { primary: [{ weapon, times_used, survival_rate, avg_kills }],
            secondary: [{ weapon, times_used, survival_rate, avg_kills }] }

Tool: get_performance_trend
  Description: Get time-series data for a stat over time
  Input:  { stat: "survival"|"runner_kills"|"pve_kills"|"loot"|"revives",
            range: "week"|"month"|"all",
            group_by: "session"|"run" }
  Output: [{ label, value, date, run_count? }]

Tool: get_spawn_stats
  Description: Get performance breakdown by spawn point
  Input:  { map: string, spawn?: string }
  Output: [{ spawn_name, coordinates, total_runs, survival_rate,
             avg_loot, avg_runner_kills, top_shell }]

Tool: get_squad_stats
  Description: Get performance data for squad mates
  Input:  { }
  Output: [{ gamertag, runs_together, survival_rate_with,
             survival_rate_without, diff, avg_combined_kills }]
```

### Frontend Endpoints

```
GET  /api/uplink/session-summary        → latest session hero stats (no AI)
GET  /api/uplink/trends?stat=X&range=Y  → time-series data for charts (no AI)
POST /api/uplink/chat                   → send message, returns streamed AI response
POST /api/uplink/briefing               → triggers AI briefing generation
```

### SYS.CONFIG Addition
- UPLINK model selector (Haiku / Sonnet) — separate from processing model
- Lives in SECTION 4 (API / AUTHENTICATION) alongside existing model selector

### Nav Change (Sidebar.tsx)
```
LIVE (renamed from CAPTURE)
  09 DETECT.EXE
  10 RUN REPORTS
  11 UPLINK        ← new, at the bottom
```

### Dependencies
- Charting library (recharts or similar) for trend graphs
- Streaming support for chat responses (SSE or WebSocket from backend)
- Haiku model access (same dual-path: API key or CLI)

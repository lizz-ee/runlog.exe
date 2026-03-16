# Marathon RunLog — TODO

## Auto-Capture: Screen Trigger System

**Goal:** Zero-interaction run logging. User plays, stats appear automatically.

**Current bottleneck:** User must manually press F12 to capture screenshots.

### Approach: Lightweight Screen Trigger

Instead of periodic full screenshots or relying on manual input, use a fast local screen watcher that detects when the results/map screens appear.

**How it works:**

1. **Every 500ms**, capture a small strip of the screen (~400x100px) from the center where the "EXFILTRATED" / "ELIMINATED" banner always appears
2. **OpenCV template match** (~5ms) against pre-cropped templates of:
   - Green "EXFILTRATED" banner → triggers run result capture
   - Red "ELIMINATED" banner → triggers run result capture
   - Map screen header (e.g. "DIRE MARSH" / "PERIMETER" title) → triggers spawn capture
3. **On match:** capture the full screenshot, send to Claude for parsing, log the run/spawn
4. **30-second cooldown** after each trigger to prevent re-processing the same screen
5. **Tab detection:** only capture when Marathon window is in foreground (check window title)

**Performance:**
- Small region capture: ~1ms
- Template match: ~5ms
- Total per loop: ~6ms (invisible to the user/game)
- Full capture only triggers on match (rare — a few times per play session)

**Templates needed** (crop from existing screenshots):
- `templates/exfiltrated.png` — the green EXFILTRATED banner
- `templates/eliminated.png` — the red ELIMINATED banner
- `templates/map_header.png` — the map screen top area (timer + zone name)
- `templates/stats_tab.png` — the STATS tab indicator (top right)
- `templates/loadout_tab.png` — the LOADOUT tab indicator

**Implementation:**
- Runs in the Electron main process (or a Python background service)
- Uses `screenshot-desktop` for capture + OpenCV/Pillow for template matching
- After detecting results screen, wait 2-3 seconds for user to tab through STATS → PROGRESS → LOADOUT, then capture each tab
- Or: detect each tab independently and merge the data from all 3

**Multi-tab capture strategy:**
- Detect STATS tab → capture → wait for LOADOUT tab → capture → merge both into one run
- Use a short window (~15 seconds) to collect all tabs for the same run
- Send all captured tabs to Claude in one request for combined parsing

**Future enhancement:**
- Could also detect the "READY UP" / "PREPARE" pre-match screen to log loadout going IN to a run
- Detect death screen mid-match for death location tracking
- OCR the map coordinates for precise spawn position instead of relying on Claude

## Other TODOs

### Map Images
- [ ] Get Cryo Archive map screenshot
- [ ] Crop all map images consistently from in-game map screen
- [ ] Add more spawn point data as games are played

### Data Quality
- [ ] Auto-link spawn points to runs (spawn captured before run = same session)
- [ ] Track weapon performance (which weapons lead to best outcomes)
- [ ] Session grouping (runs played in the same sitting)

### UI
- [ ] Add trends/charts to dashboard (survival rate over time, loot over time)
- [ ] Weapon stats page (K/D per weapon, win rate per weapon)
- [ ] Run detail view (click a run to see full breakdown)
- [ ] Export data (CSV/JSON)

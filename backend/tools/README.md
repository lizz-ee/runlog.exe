# backend/tools

Developer measurement utilities. Not shipped with the app, not imported by it.

## frametime_harness.py

Measures runlog.exe's real impact on **Marathon's** frame times using Intel
PresentMon (an ETW front-end). Use it to prove — not assert — that capture,
recording, the HUD overlay, and any future change (1440p30 defaults, E-core
pinning, overlay static-dot, etc.) do or don't move the game's frame pacing.

### One-time setup
1. Download `PresentMon-*-x64.exe` from
   <https://github.com/GameTechDev/PresentMon/releases>.
2. Put it on `PATH`, drop it in this folder, or pass `--presentmon <path>`.
3. Run from an **Administrator** terminal (ETW needs elevation).

### Use
```bash
# Single 30s snapshot of the current state
python frametime_harness.py capture --seconds 30

# Guided A/B/C: you stage each scenario, it captures + prints a delta table
python frametime_harness.py compare --seconds 30 \
    --scenarios "runlog OFF" "watching" "recording 1440p30" "recording + overlay"
```

### What to look at
- **Present mode** — the headline number. `Hardware: Independent Flip` is the
  cheap path; a shift to a `Composed` mode means something (usually the
  always-on-top overlay) demoted the game's present path and added latency.
- **Δmean / Δp99 vs baseline** — positive = the game got slower under that
  scenario.
- **1% / 0.1% low fps** — stutter, the thing players actually feel.

The tool only observes; it never touches the recorder, encoder, or any process.

# runlog.exe — TODO

## Features

### Maps
- [ ] Get Cryo Archive map image (currently marked REDACTED in sidebar)
- [ ] Add Cryo Archive spawn point data as games are played

### Stats & Charts
- [ ] Weapon performance scoring — combined survival rate + K/D + loot per weapon, best/worst weapon per shell and per map (basic stub exists in `tool_get_weapon_stats()`, needs full implementation)

### UI Enhancements
- [ ] Export data (CSV/JSON) for runs, stats, spawn data

### Processing Metrics
- [ ] Token usage tracking from API responses (input_tokens, output_tokens, cost estimate)

### Run Report Card Export
- [ ] Export button on run row
- [ ] Generates styled image card with Marathon cyberpunk aesthetic
- [ ] Card contents: grade, map, shell, kills, outcome, loot, narrative snippet, RUNLOG.EXE branding
- [ ] Dark background, Discord-friendly aspect ratio

---

## Highlights V2 — AI Clip Detection Improvements

Phase 1 (Quick Wins) and Phase 2 (Chain-of-Thought) are complete.

### Phase 3: Audio Energy Analysis
- [ ] Extract audio from recording via ffmpeg (`-vn -ac 1 -ar 22050`)
- [ ] Add `librosa` dependency, compute RMS energy per 0.5s window
- [ ] Flag "hot zones" where energy > 2x baseline for > 1 second
- [ ] Pass hot zones as combat-region context to Phase 2 prompt
- [ ] Smart frame extraction — 2-4fps during hot zones, 0.5fps during cold zones (reduces LLM cost ~70-80%)

### Phase 4: Kill Feed CV Classifier
- [ ] Collect kill feed crop dataset from existing recordings (~200-400 samples)
- [ ] Train lightweight CNN (MobileNet or similar), export as ONNX
- [ ] Run classifier on OCR frames during recording, log kill timestamps to `.kills` marker file
- [ ] Pass confirmed kill timestamps to Phase 2 as ground truth

### Phase 5: Advanced (Future)
- [ ] Voice/shout detection — energy spikes in 300-3000Hz band
- [ ] Scene change detection — histogram comparison between adjacent frames
- [ ] Multi-signal fusion — combine audio + kill feed CV + scene changes + LLM, clip when 2+ signals agree
- [ ] X-CLIP style classifier — 1-second sliding window, could replace LLM for highlight detection

---

## Infrastructure
- [ ] Code signing for Windows builds (electron-builder config scaffolded, needs certificate purchase)

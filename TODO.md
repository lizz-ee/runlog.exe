# runlog.exe — TODO

## Features

### Maps
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
**UNBLOCKED — audio capture shipped.** Recordings now carry a game-audio track: a Python
sidecar (`backend/app/audio_sidecar.py`) records Marathon-only audio via WASAPI
*per-process* loopback (`backend/app/wasapi_loopback.py`), and Phase 2 muxes the WAV into
the MP4 as AAC (`_mux_sidecar_audio` in `video_processor.py`). Toggle in SYS.CONFIG →
REC.CONFIG → AUDIO (`audio_capture`, default on). `AudioAnalyzer`
(backend/app/alpha/audio_analyzer.py, numpy — no librosa) is wired into ALPHA highlights
and reads the sidecar WAV automatically.
- [x] ~~WASAPI loopback capture + opt-in setting~~ — shipped in the Python sidecar (Marathon-only process loopback → whole-system fallback → off). Process loopback captures game audio only, so voice chat never leaks in.
- [ ] Optional: move audio into the Rust recorder for sample-accurate A/V sync + one less Python thread (blocked on the `windows-capture` audio path — confirm the original disable reason first). Sidecar sync is good enough today.
- [x] ~~Add `librosa` dependency~~ — RMS + spectral energy implemented with numpy in `AudioAnalyzer`
- [x] Hot zones → combat-region context for Phase 2 (done via kill feed events, see Phase 4)
- [x] Smart frame extraction — 2fps in confirmed combat windows, 0.25fps elsewhere (done via kill feed events)

### Phase 4: Kill Feed Detection
- [x] Live kill feed logging during recording — winocr on a dedicated OCR.KILLFEED scan region (cropped recorder-side), eliminations appended to a `.events` sidecar with run timestamps. ~16ms per 3s tick at below-normal priority — zero game impact.
- [x] Pass confirmed kill timestamps to Phase 2 as ground truth (CLI analyst gets event list + targeted two-pass extraction plan; API path gets the event list)
- [ ] Calibrate OCR.KILLFEED region coordinates against real 4K footage (current rect is from the HUD layout guide — misses are harmless, events are additive hints)
- [ ] Optional upgrade: CNN classifier (MobileNet → ONNX) if winocr accuracy on feed text proves insufficient

### Phase 5: Advanced (Future)
- [ ] Voice/shout detection — energy spikes in 300-3000Hz band
- [ ] Scene change detection — histogram comparison between adjacent frames
- [ ] Multi-signal fusion — combine audio + kill feed CV + scene changes + LLM, clip when 2+ signals agree
- [ ] X-CLIP style classifier — 1-second sliding window, could replace LLM for highlight detection

---

## Infrastructure
- [ ] Code signing for Windows builds (electron-builder config scaffolded, needs certificate purchase)

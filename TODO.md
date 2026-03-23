# runlog.exe — TODO

## Features

### Maps
- [ ] Get Cryo Archive map image (currently marked REDACTED in sidebar)
- [ ] Add Cryo Archive spawn point data as games are played

### Stats & Charts
- [ ] Weapon performance scoring — combined survival rate + K/D + loot per weapon, best/worst weapon per shell and per map (basic stub exists in `tool_get_weapon_stats()`, needs full implementation)

### UI Enhancements
- [ ] Export data (CSV/JSON) for runs, stats, spawn data
- [ ] Timeline markers — show AI-generated highlight clips as marked segments on the video timeline

### Capture Improvements
- [ ] Death screen detection for mid-match death location tracking (currently only passive in Phase 2 prompts)

### Processing Metrics
- [ ] Token usage tracking from API responses (input_tokens, output_tokens, cost estimate)

### Data
- [ ] Death heatmap — map game coordinates to map image, mark death locations

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

## Ollama / Local Model Support (ALPHA)

> **Status:** Planning — not yet implemented.
> This is an alpha feature. Local models have significantly lower accuracy than Claude for stats extraction. Results may be incorrect. Ship alongside develop branch as experimental.

### Core Integration (ai_client.py)
- [ ] `ollama_status()` — detect if Ollama is running (hit `/api/tags` at configured endpoint)
- [ ] `run_ollama_prompt()` — core execution via OpenAI-compatible endpoint (`/v1/chat/completions`) using `httpx`
- [ ] `run_ollama_prompt_async()` — async wrapper
- [ ] `test_ollama_connection(endpoint)` — validate endpoint reachability
- [ ] `prefer_ollama()` — routing function, same pattern as `prefer_api()` / `prefer_cli()`
- [ ] Update `_get_auth_mode()` to accept `"ollama"`
- [ ] Update `get_model_config()` to return Ollama model names
- [ ] Update `has_any_auth()` to check Ollama availability
- [ ] Add `format: "json"` to all Ollama calls expecting JSON responses
- [ ] No new pip dependencies — use `httpx` (already transitive dep of `anthropic`)

### Settings (settings_api.py)
- [ ] New defaults: `ollama_endpoint` (localhost:11434), `ollama_vision_model`, `ollama_tool_model`
- [ ] Expand `auth_mode` validation to accept `"ollama"`
- [ ] `GET /settings/ollama/status` — check connection + list downloaded models
- [ ] `GET /settings/ollama/models` — list available models from Ollama instance
- [ ] `POST /settings/ollama/test` — test endpoint connection
- [ ] `POST /settings/ollama/pull` — trigger model download
- [ ] Return Ollama status in `GET /settings`

### Curated Model Lists
- [ ] Maintain hardcoded lists of known-working models per capability:
  - **Vision models** (for capture/screenshots): `qwen2.5-vl:7b`, `llama3.2-vision:11b`, `gemma3:12b`, `llava:13b`, `glm-ocr`
  - **Tool models** (for UPLINK chat): `llama3.1:8b`, `qwen2.5:7b`, `qwen3.5:8b`, `mistral:7b`
- [ ] Only allow selecting vision models for capture, tool models for UPLINK — no free-text entry
- [ ] Show model size / VRAM estimate next to each option

### Consumer Integration
- [ ] `screenshot.py` — add Ollama path in `_call_claude()` (images + prompt → JSON)
- [ ] `uplink.py` — add `_run_ollama_path()` for tool-calling chat (separate tool-capable model)
- [ ] `uplink.py` — briefing endpoint uses same path
- [ ] `spawns.py` — already routes through `_call_claude()`, works automatically
- [ ] `video_processor.py` Phase 1 — add Ollama path for frame analysis (send extracted frames as images)
- [ ] `video_processor.py` Phase 2 — extract ~20-30 frames via FFmpeg, send as images to vision model (replaces full-video API call)

### Worker & Performance
- [ ] Auto-cap P1 workers to 1 when Ollama is active (single GPU queues requests)
- [ ] Auto-cap P2 workers to 1
- [ ] Consider batching frames (5-10 per call instead of 30+) for Ollama vision models

### Error Handling
- [ ] Ollama server down → show clear error ("Ollama offline"), do NOT silently fall back to Claude
- [ ] Model not pulled → block with "Model not downloaded" + PULL button, do not attempt call
- [ ] Bad JSON response → retry once with stricter prompt ("Return ONLY valid JSON"), then fail with error
- [ ] Invalid tool call → validate tool names exist before executing, ignore hallucinated tools
- [ ] No silent fallback to Claude — respect user's choice of local-only

### Prompt Tuning
- [ ] May need simplified prompts for local models (shorter, more explicit)
- [ ] Context window limits (8K-32K vs Claude's 200K) — ensure prompts fit
- [ ] Add explicit "Return ONLY valid JSON, no explanation" directives for Ollama calls
- [ ] Test and tune per model — accuracy will vary significantly

### Image Handling
- [ ] Send full resolution images to Ollama (4K needed for stats text readability)
- [ ] Let the model's vision encoder handle downscaling internally
- [ ] Consider cropping to relevant regions (OCR scan areas) to improve accuracy on smaller models

### Frontend (Settings.tsx)
- [ ] Expand AI.PROVIDER toggle: `[API KEY | CLI | OLLAMA]`
- [ ] Ollama config section (when selected):
  - Endpoint URL field (default: `http://localhost:11434`)
  - TEST CONNECTION button → "RUNNING" / "OFFLINE" status
  - Vision model dropdown (populated from curated list, filtered by what's downloaded)
  - UPLINK model dropdown (tool-capable models only)
  - PULL/DOWNLOAD button for models not yet downloaded
  - Download progress indicator
- [ ] Disable OLLAMA option if connection test fails
- [ ] Auto-select OLLAMA when it's the only available provider

### Alpha Disclaimer
- [ ] Show warning banner in SYS.CONFIG when Ollama is selected: "EXPERIMENTAL — Local model support is in alpha. Stats extraction accuracy is significantly lower than Claude. Results may be incorrect."
- [ ] Show warning in DETECT.EXE processing queue when Ollama processes a run
- [ ] Document limitations in user guide

### User Guide
- [ ] Add Ollama setup section to docs/user-guide.md
- [ ] Document model recommendations and VRAM requirements
- [ ] Document known limitations vs Claude

---

## Infrastructure
- [ ] Code signing for Windows builds (electron-builder config scaffolded, needs certificate purchase)

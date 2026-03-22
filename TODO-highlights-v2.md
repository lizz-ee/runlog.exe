# HIGHLIGHTS V2 — AI Clip Detection Overhaul

## Context
Current system sends full video to Sonnet CLI at 1fps, asks for highlights in one pass.
Results: clips too long (45-60s), missed PVP kills, mislabeled events, poor timestamp accuracy.
Goal: Short, punchy, accurate highlight clips (15-25s) with correct event classification.

---

## Phase 1: Quick Wins (Prompt Engineering Only)

### 1.1 Validate Highlights Against Phase 1 Stats
- [ ] Pass Phase 1 stats as hard constraints to Phase 2 prompt
- [ ] "Phase 1 detected N Runner Eliminations — you MUST find exactly N pvp_kill clips"
- [ ] If model can't find them, require explanation instead of fabricating
- **Effort**: Prompt change only
- **Impact**: Eliminates mislabeled and fabricated PVP kills

### 1.2 Burn Timestamps Into Frames
- [ ] Add MM:SS overlay to extracted frames via ffmpeg `-vf drawtext`
- [ ] Model sees the timestamp visually — no more mental math from frame index
- [ ] Format: white text, top-left corner, semi-transparent background
- **Effort**: One ffmpeg flag change
- **Impact**: Dramatically improves timestamp accuracy

### 1.3 Marathon HUD Description in Prompt
- [ ] Add specific HUD element locations to Phase 2 prompt:
  - Kill feed: top-right, "PlayerA [weapon] PlayerB" format
  - Death screen: full-screen "NEURAL LINK SEVERED" overlay, killer info right side
  - Health bar: bottom-center, red when low
  - Hit markers: white crosshair flash when dealing damage
  - Damage vignette: red screen edges when taking damage
  - Extraction UI: countdown timer at extraction point
- **Effort**: Prompt addition
- **Impact**: Model knows exactly what to look for and where

### 1.4 Duration Caps (DONE)
- [x] Hard cap at 25s in clip cutting code
- [x] Prompt updated with tight duration ranges per clip type
- [x] pvp_kill 8-15s, death 8-15s, combat 10-20s, extraction 10-15s

---

## Phase 2: Chain-of-Thought Prompting

### 2.1 Three-Step Structured Analysis
Replace single-pass prompt with structured chain-of-thought:

**Step 1 — Scene Inventory** (model outputs timeline first):
- For each 10-second segment: classify as idle/traversal/combat/menu/death/extraction
- List every frame showing: kill feed messages, damage indicators, health drops, death screen

**Step 2 — Event Identification** (anchored to scene inventory):
- For each combat segment: who is fighting, what weapons, does someone die?
- For each kill feed message: which frame number shows it?

**Step 3 — Highlight Selection** (only after events identified):
- Select highlights from identified events
- Quote exact frame numbers for start/end of action
- System calculates timestamps from frame numbers

- [ ] Restructure Phase 2 prompt into 3 steps
- [ ] Test with existing recordings to compare quality
- **Effort**: Major prompt restructure
- **Impact**: Research shows hallucinations drop from 38% to 18%

---

## Phase 3: Audio Energy Analysis

### 3.1 Audio Track Extraction
- [ ] Extract audio from recording via ffmpeg: `ffmpeg -i video.mp4 -vn -ac 1 -ar 22050 audio.wav`
- [ ] Add `librosa` to Python dependencies

### 3.2 Energy Timeline Computation
- [ ] Compute RMS energy per 0.5s window using librosa
- [ ] Compute baseline (median energy across full recording)
- [ ] Flag "hot zones" where energy > 2x baseline for > 1 second
- [ ] Merge adjacent hot zones within 5s of each other

### 3.3 Pass Hot Zones as Context to LLM
- [ ] Format: "Combat audio detected at: 2:30-2:45, 5:10-5:25, 8:40-9:00"
- [ ] Include in Phase 2 prompt as priority regions
- [ ] Model focuses frame analysis on these windows

### 3.4 Smart Frame Extraction (Hot Zone Weighted)
- [ ] Extract at 2-4fps during hot zones (combat)
- [ ] Extract at 0.5fps during cold zones (traversal/looting)
- [ ] Cap total frames at 60-80 (weighted toward action)
- [ ] Reduces LLM cost by 70-80% while improving accuracy

- **Effort**: New pipeline stage, librosa dependency
- **Impact**: Massive — model only sees relevant content, knows where combat is

---

## Phase 4: Kill Feed CV Classifier (Marathon-Specific)

### 4.1 Data Collection
- [ ] Define kill feed screen region (fixed position in Marathon HUD, top-right)
- [ ] Extract kill feed crops from existing recordings at 2fps during hot zones
- [ ] Build dataset: ~100-200 screenshots with kills, ~200 without
- [ ] Label: kill_event / no_kill_event / death_event

### 4.2 Model Training
- [ ] Train lightweight CNN (MobileNet or similar) on kill feed crops
- [ ] Target: >90% accuracy on kill detection
- [ ] Export as ONNX for fast inference

### 4.3 Real-Time Integration
- [ ] Run classifier on OCR frames during recording (piggyback on existing frame capture)
- [ ] Log kill timestamps to a `.kills` marker file alongside recording
- [ ] Pass confirmed kill timestamps to Phase 2 as ground truth

### 4.4 Benefits
- Kill detection without LLM involvement
- Real-time kill feed during recording (could show in overlay)
- Phase 2 validates against confirmed kills instead of guessing

- **Effort**: ML training pipeline, data labeling
- **Impact**: Near-perfect kill detection, real-time kill logging

---

## Phase 5: Advanced (Future)

### 5.1 Voice/Shout Detection
- [ ] Analyze audio for voice energy spikes (player reacting to kills/deaths)
- [ ] Powder.gg uses this — shouting/laughing = exciting moment
- [ ] Could use simple energy threshold in voice frequency band (300-3000Hz)

### 5.2 Scene Change Detection
- [ ] Histogram comparison between adjacent frames
- [ ] Detects transitions: gameplay → death screen → stats screen
- [ ] Cheap pre-filter to skip menus/loading

### 5.3 Multi-Signal Fusion
- [ ] Combine: audio energy + kill feed CV + scene changes + LLM analysis
- [ ] Weighted confidence scoring across signals
- [ ] Only clip when 2+ signals agree

### 5.4 X-CLIP Style Classifier
- [ ] Research paper achieves 94% accuracy across multiple FPS games
- [ ] 1-second sliding window classification
- [ ] Could replace LLM for highlight detection entirely
- [ ] LLM only used for narrative description of confirmed highlights

---

## Rollout Order

```
NOW        Phase 1.1  Validate against P1 stats (prompt change)
NOW        Phase 1.2  Burn timestamps into frames (ffmpeg flag)
NOW        Phase 1.3  Marathon HUD description (prompt addition)
NEXT       Phase 2.1  Chain-of-thought restructure (prompt overhaul)
NEXT       Phase 3.1  Audio extraction + energy analysis
NEXT       Phase 3.3  Hot zone context in prompt
LATER      Phase 3.4  Smart frame extraction (weighted sampling)
LATER      Phase 4    Kill feed classifier (ML training)
FUTURE     Phase 5    Voice detection, scene changes, multi-signal fusion
```

---

## Research Sources
- NVIDIA Highlights SDK — game event API integration pattern
- Powder.gg — 40+ game-specific AI models, audio analysis
- Crispy (open source) — game-specific neural networks on HUD
- Gameplay Highlights Generation (2025 paper) — X-CLIP, 94% accuracy
- VTG-LLM — timestamp knowledge via visual tokens
- Hallucination Mitigation paper — CLIP + CoT reduces errors from 38% to 18%
- NumPro — burning frame numbers into video frames
- NVIDIA VLM Prompt Guide — specificity and structured output
- Clypse 2026 — optimal clip length 15-34s for TikTok gaming

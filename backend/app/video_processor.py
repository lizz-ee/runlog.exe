"""
Video Processor -- Two-phase analysis pipeline for Marathon run recordings.

Phase 1 (Stats, ~1-2 min):
  1. Extract key frames from start (lobby/loading) and end (post-match) of video
  2. Send frames as images to Sonnet API for accurate stat extraction
  3. Save run to database immediately -- stats appear in app fast

Phase 2 (Story + Clips, ~10 min):
  1. Compress full video to 2K
  2. Send to CLI for narrative analysis (grade, summary, highlights)
  3. Update existing run with narrative data (never overwrites Phase 1 stats)
  4. Cut highlight clips from original 4K video

Fallback: If Phase 1 fails, falls back to legacy single-pass video analysis.
"""

import base64
import glob as glob_mod
import json
import os
import shutil
import subprocess
import time
from datetime import datetime

from .config import settings

# -- Frame extraction settings (easy to tune) -------------------------------
FRAME_RESOLUTION = 2560       # long edge px — 2K for legible UI text
FRAME_DURATION_START = 90     # seconds from start (loading screen can be 0-90s depending on session spawn wait)
FRAME_FPS_START = 0.5         # deployment loading screen — static, 0.5fps is plenty (~45 frames)
FRAME_FPS_END = 5             # post-match tabs — flip fast, need higher fps


# -- Phase 1 prompt (stats extraction from frames) --------------------------

PHASE1_PROMPT = """You are analyzing screenshots extracted from a Marathon (Bungie 2026 extraction shooter) gameplay recording.

The images are organized in TWO groups:
- **start_NNNN.jpg**: Frames from the FIRST 90 SECONDS of the run. Look for:
  - DEPLOYMENT LOADING SCREEN: A full-screen colored background (blue, red, black, purple, or green) with the map name in large text and TWO DECIMAL COORDINATE NUMBERS at the bottom center (e.g. "10.564070" and "195.869476"). These are spawn coordinates — capture them EXACTLY.
  - The lobby/loadout screen is NOT recorded — do not expect to see shell, squad, starting inventory, or equipped weapons in start frames. These come from end frames.

- **end_NNNN.jpg**: Frames from the LAST 30 SECONDS of the run. Look for:
  - DEATH SCREEN: Who killed the player, weapon used, damage contributors list
  - STATS tab: "EXFILTRATED" or death status, "Combatant Eliminations" (PvE), "Runner Eliminations" (PvP), "Crew Revives", "Inventory Value" (loot), "Run Time" (MM:SS)
  - PROGRESS tab: Season level, faction ranks
  - LOADOUT tab: Weapons extracted, "Wallet Balance" with gain amount, "Report Summary"

Extract ALL visible data. The STATS tab is GROUND TRUTH — use its exact numbers.

Return ONLY valid JSON:
{
  "map_name": "Perimeter" or "Outpost" or "Dire Marsh" or "Cryo Archive" or null,
  "shell_name": "character class visible on STATS tab (character model shown)" or null,
  "player_gamertag": "local player's gamertag from STATS or LOADOUT tab" or null,
  "squad_members": ["squad", "gamertags", "from end screens"] or null,
  "survived": true if "EXFILTRATED" or "Exit Successful", false if died,
  "kills": total from STATS tab (Combatant + Runner Eliminations),
  "combatant_eliminations": exact number from STATS tab,
  "runner_eliminations": exact number from STATS tab,
  "deaths": 0 if EXFILTRATED, 1 if died,
  "crew_revives": exact number from STATS tab,
  "duration_seconds": convert "Run Time" MM:SS to total seconds,
  "loot_value_total": "Inventory Value" from STATS tab. NEVER zero for survived runs. Check LOADOUT tab "Wallet Balance" gain if STATS not found.,
  "primary_weapon": "weapon name" or null,
  "secondary_weapon": "weapon name" or null,
  "killed_by": "gamertag of finisher from death screen" or null,
  "killed_by_weapon": "weapon from death screen" or null,
  "damage_contributors": [{"name": "gamertag", "damage": number, "finished": true/false}] or null,
  "spawn_coordinates": [10.564070, 195.869476] or null,
  "spawn_location": "zone name if visible" or null,
  "loading_screen_found": true if you found the deployment loading screen with coordinates,
  "stats_tab_found": true if you found the STATS tab with kill/loot numbers,
  "loadout_tab_found": true if you found the LOADOUT tab with weapons/wallet
}

IMPORTANT: Do NOT leave numeric fields as 0 unless the STATS tab explicitly shows 0. Check every end frame carefully.

Return ONLY valid JSON, no markdown fences, no explanation."""


# -- Phase 2 prompt (narrative only, for video) -----------------------------

PHASE2_PROMPT = """You are analyzing a recorded gameplay video from Marathon (Bungie 2026 extraction shooter).

The run's stats have ALREADY been extracted accurately. Do NOT extract or return any stats.

Watch the ENTIRE video and provide ONLY:
1. A performance GRADE
2. A narrative SUMMARY of the run
3. HIGHLIGHT timestamps for clip cutting

Return ONLY valid JSON:
{
  "grade": "S, A, B, C, D, or F — YOUR rating based on the criteria below",
  "summary": "A narrative story of this run written in second person (you). 2-4 paragraphs. Describe the flow like a sports commentator recap — the drop, early looting, key fights, turning points, and how it ended. Make it engaging and specific.",
  "highlights": [
    {
      "timestamp_seconds": number (seconds from start of video),
      "duration_seconds": 12,
      "type": "kill" or "death" or "loot" or "close_call" or "extraction" or "funny",
      "description": "Brief description of what happened"
    }
  ]
}

GRADING CRITERIA:
- S: Exceptional — survived with high kills (8+), big loot haul, clean execution
- A: Great run — survived, solid kills, good loot, few mistakes
- B: Solid — survived with decent stats, or died but put up a great fight
- C: Average — mediocre kills/loot, or died in an unremarkable way
- D: Poor — died quickly with little to show for it
- F: Disaster — died almost immediately, no kills, no loot

For highlights, identify the most exciting/notable moments:
- Player kills (especially PvP kills or multi-kills)
- Player death (the moment of dying)
- Close calls (nearly dying, clutch plays)
- Extraction moment
- Funny or unusual events
- Big loot finds

Return ONLY valid JSON, no markdown fences, no explanation."""


# -- Legacy prompt (full single-pass analysis, fallback) --------------------

VIDEO_PROMPT = """You are analyzing a recorded gameplay video from Marathon (Bungie 2026 extraction shooter).

Analyze the ENTIRE video carefully. The video covers one complete run from lobby to end.

You will see some or all of these phases:
1. **LOBBY/READY UP** - Character in lobby, green "READY UP" button visible. You can see the SHELL (character class) name and thumbnail image, the equipped loadout/weapons, and a STARTING INVENTORY VALUE (currency amount, e.g. "$4,500" or "B28/148"). Capture these.
2. **CONTRACT BRIEFING** - Appears after matchmaking, before deploying. Shows the active contract name (e.g. "BUILD MEETS CRAFT II"), contract type (e.g. "MULTI-ZONE"), objectives with progress bars, player username and season level at top. Also shows warning text about gear risk.
3. **DEPLOYING** - Countdown screen, shows map name and spawn coordinates
4. **LOADING SCREEN** - Full-screen colored background (blue, red, black, purple, or green) with map name in large text, description below, and TWO DECIMAL COORDINATE NUMBERS at the bottom center (e.g. "10.564070" and "195.869476"). These are spawn coordinates — VERY IMPORTANT to capture exactly.
5. **GAMEPLAY** - First-person shooter gameplay. Player loots, fights enemies (Combatants/AI and Runners/players), explores
6. **DEATH** - Screen showing who killed the player and with what weapon, OR
7. **EXTRACTION** - Player reaches extraction point and escapes with loot
8. **POST-MATCH SCREENS** - Three tabs that ALWAYS appear at the end, back-to-back. These are the GROUND TRUTH — data from these screens OVERRIDES any estimates from gameplay. You MUST check the last 30 seconds of the video for these:
   - **STATS tab** (appears FIRST): Shows character model, "EXFILTRATED" or death status, "Combatant Eliminations" (PvE kills), "Runner Eliminations" (PvP kills), "Crew Revives", "Inventory Value" (THIS IS THE LOOT VALUE), and "Run Time" (MM:SS). USE THESE EXACT NUMBERS.
   - **PROGRESS tab** (appears SECOND): Shows season level, faction ranks (CyAc, NLI, Traxus, etc.), contract completion. Less important for stats.
   - **LOADOUT tab** (appears THIRD): Shows weapons extracted, backpack items (e.g. "7/16"), items retained/transmuted/auto-sold/auto-vaulted, "Wallet Balance" at bottom with gain (e.g. "(+480) 64,941"), and "Report Summary: Exfil Successful".

Extract ALL of this information from the video:

{
  "map_name": "Perimeter" or "Outpost" or "Dire Marsh" or "Cryo Archive" or null,
  "shell_name": "name of the Shell (character class) visible in lobby, e.g. Triage, Warlock, etc." or null,
  "player_gamertag": "the local player's gamertag/username. In the squad display, the local player is ALWAYS the CENTER member. Extract their gamertag exactly as shown." or null,
  "squad_members": ["list", "of", "all", "squad", "member", "gamertags"] or null — include ALL members shown in the squad UI (including the local player). The local player is the center member.,
  "starting_loadout_value": starting inventory/currency value visible in lobby before deploying (number) or null,
  "survived": true if player extracted, false if died,
  "kills": total kills from STATS tab (Combatant Eliminations + Runner Eliminations). DO NOT estimate from gameplay — use the exact numbers from the STATS screen.,
  "combatant_eliminations": exact number from STATS tab "Combatant Eliminations" field,
  "runner_eliminations": exact number from STATS tab "Runner Eliminations" field,
  "deaths": 0 if EXFILTRATED, 1 if died,
  "crew_revives": exact number from STATS tab "Crew Revives" field,
  "duration_seconds": convert STATS tab "Run Time" (MM:SS format) to total seconds,
  "loot_value_total": exact number from STATS tab "Inventory Value" field. This is NEVER zero for a survived run. If STATS tab is not visible, check LOADOUT tab "Wallet Balance" gain amount.,
  "primary_weapon": name of primary weapon used,
  "secondary_weapon": name of secondary weapon used,
  "killed_by": gamertag of the player who landed the FINISHING blow (from death screen),
  "killed_by_weapon": weapon that killed you (if visible on death screen),
  "damage_contributors": [
    {"name": "gamertag", "damage": number, "finished": true/false}
  ] or null — ALL players/enemies who dealt damage to you on the death screen (the finisher has "finished": true, others contributed damage but didn't land the killing blow. e.g. [{"name": "Azuka", "damage": 81, "finished": true}, {"name": "WarNer", "damage": 88, "finished": false}, {"name": "Falling", "damage": 25, "finished": false}]),
  "spawn_coordinates": "two decimal numbers from the deployment loading screen, e.g. [10.564070, 195.869476]" or null,
  "spawn_location": "zone name visible on the in-game map or HUD if identifiable" or null,
  "grade": "YOUR rating of how well the player performed: S, A, B, C, D, or F (this is NOT from the game UI, YOU assign this grade based on the criteria below)",
  "highlights": [
    {
      "timestamp_seconds": number (seconds from start of video),
      "duration_seconds": 12,
      "type": "kill" or "death" or "loot" or "close_call" or "extraction" or "funny",
      "description": "Brief description of what happened"
    }
  ],
  "summary": "A narrative story of this run written in second person (you). 2-4 paragraphs. Describe the flow of the run like a sports commentator recap — the drop, early looting, key fights, turning points, and how it ended. Make it engaging and specific to what actually happened."
}

GRADING CRITERIA for "grade":
- S: Exceptional — survived with high kills (8+), big loot haul, clean execution
- A: Great run — survived, solid kills, good loot, few mistakes
- B: Solid — survived with decent stats, or died but put up a great fight
- C: Average — mediocre kills/loot, or died in an unremarkable way
- D: Poor — died quickly with little to show for it
- F: Disaster — died almost immediately, no kills, no loot

For highlights, identify the most exciting/notable moments:
- Player kills (especially PvP kills or multi-kills)
- Player death (the moment of dying)
- Close calls (nearly dying, clutch plays)
- Extraction moment
- Funny or unusual events
- Big loot finds

IMPORTANT: Do NOT leave numeric fields as 0 or null unless you are certain the data is not visible anywhere in the video. Check the post-match screens carefully — STATS tab, LOADOUT tab, and the top HUD bar all show inventory/loot values. A survived run with a "full bag" should ALWAYS have a non-zero loot_value_total.

Return ONLY valid JSON, no markdown fences, no explanation."""


# -- Helpers ----------------------------------------------------------------

def _find_claude_cli():
    """Find the claude CLI binary."""
    candidates = [
        shutil.which("claude"),
        os.path.expanduser("~/.local/bin/claude"),
        os.path.expanduser("~/.local/bin/claude.exe"),
        os.path.expanduser("~/AppData/Local/Programs/claude/claude.exe"),
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def _extract_json(text: str) -> dict:
    """Extract JSON from Sonnet response, handling extra text robustly."""
    text = text.strip()

    # Strip markdown fences
    if "```" in text:
        import re
        fence_match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

    # Find the first '{'
    start = text.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in response: {text[:200]}")

    candidate = text[start:]

    # First try: the whole thing from first { to end
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Second try: find balanced braces
    depth = 0
    for i, ch in enumerate(candidate):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(candidate[:i + 1])
                except json.JSONDecodeError:
                    continue

    # Last resort: first { to last }
    end = text.rfind("}") + 1
    if end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract valid JSON from response: {text[:500]}")


def _get_video_duration(video_path: str) -> float | None:
    """Get video duration in seconds using ffprobe."""
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'csv=p=0', video_path],
            capture_output=True, text=True, timeout=10,
        )
        return float(probe.stdout.strip())
    except Exception:
        return None


# -- Frame extraction -------------------------------------------------------

def extract_key_frames(video_path: str, frames_dir: str, video_duration: float) -> str:
    """Extract key frames from start and end of video for Phase 1 analysis.

    Start window: first FRAME_DURATION_START seconds at FRAME_FPS_START -- deployment loading screen
    End window: last 30s at FRAME_FPS_END -- STATS, PROGRESS, LOADOUT tabs
    Resolution: FRAME_RESOLUTION px long edge (2K for legible UI text)
    """
    os.makedirs(frames_dir, exist_ok=True)

    # Start frames: first 60s at 0.5fps (~30 frames, just need the loading screen)
    start_cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
        '-ss', '0', '-t', str(FRAME_DURATION_START),
        '-i', video_path,
        '-vf', f'scale={FRAME_RESOLUTION}:-2,fps={FRAME_FPS_START}',
        '-q:v', '3',
        os.path.join(frames_dir, 'start_%04d.jpg'),
    ]
    result = subprocess.run(start_cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"Start frame extraction failed: {result.stderr[:200]}")

    # End frames: last 30s (higher fps — tabs flip fast)
    end_start = max(0, video_duration - 30)
    end_cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
        '-ss', str(end_start), '-t', '30',
        '-i', video_path,
        '-vf', f'scale={FRAME_RESOLUTION}:-2,fps={FRAME_FPS_END}',
        '-q:v', '3',
        os.path.join(frames_dir, 'end_%04d.jpg'),
    ]
    result = subprocess.run(end_cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"End frame extraction failed: {result.stderr[:200]}")

    start_count = len(glob_mod.glob(os.path.join(frames_dir, 'start_*.jpg')))
    end_count = len(glob_mod.glob(os.path.join(frames_dir, 'end_*.jpg')))
    print(f"[processor] Extracted frames: {start_count} start + {end_count} end")

    if start_count == 0 and end_count == 0:
        raise RuntimeError("No frames extracted")

    return frames_dir


def _get_frame_paths(frames_dir: str) -> list[str]:
    """Get sorted list of all frame paths (start frames first, then end frames)."""
    start_frames = sorted(glob_mod.glob(os.path.join(frames_dir, 'start_*.jpg')))
    end_frames = sorted(glob_mod.glob(os.path.join(frames_dir, 'end_*.jpg')))
    return start_frames + end_frames


# -- Phase 1 analysis (frames -> stats) ------------------------------------

def _analyze_frames_with_api(frame_paths: list[str], prompt: str) -> dict:
    """Send frame images to Sonnet API as base64 image blocks."""
    import anthropic

    content = []
    for path in frame_paths:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })
    content.append({"type": "text", "text": prompt})

    print(f"[processor] Sending {len(frame_paths)} frames to Sonnet API...")
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": content}],
    )
    return _extract_json(message.content[0].text)


def _analyze_frames_with_cli(frame_paths: list[str], prompt: str) -> dict:
    """Send frame images to Claude CLI for analysis (fallback when no API key)."""
    claude_bin = _find_claude_cli()
    if not claude_bin:
        raise RuntimeError("Claude CLI not found")

    abs_paths = [os.path.abspath(p).replace("\\", "/") for p in frame_paths]
    image_list = "\n".join(f"- {p}" for p in abs_paths)
    full_prompt = f"""Read these Marathon gameplay screenshot images:
{image_list}

Then analyze them and follow these instructions:

{prompt}"""

    cmd = [claude_bin, "-p", full_prompt, "--model", "sonnet",
           "--dangerously-skip-permissions"]

    print(f"[processor] Sending {len(frame_paths)} frames to CLI...")
    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    output_lines = []
    try:
        for line in iter(proc.stdout.readline, b''):
            decoded = line.decode("utf-8", errors="replace").rstrip()
            if decoded:
                output_lines.append(decoded)
        proc.wait(timeout=600)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError("CLI timed out during Phase 1")

    output = "\n".join(output_lines).strip()
    if not output:
        raise RuntimeError("CLI returned no output for Phase 1")

    return _extract_json(output)


def analyze_frames_phase1(frames_dir: str) -> dict:
    """Analyze extracted frames for Phase 1 stats.

    Uses API (preferred for speed) with CLI fallback.
    """
    frame_paths = _get_frame_paths(frames_dir)
    if not frame_paths:
        raise RuntimeError("No frames found in frames directory")

    print(f"[processor] Phase 1: analyzing {len(frame_paths)} frames...")

    # API is preferred for Phase 1 (faster for images, no video overhead)
    if settings.anthropic_api_key:
        try:
            return _analyze_frames_with_api(frame_paths, PHASE1_PROMPT)
        except Exception as e:
            print(f"[processor] Phase 1 API failed: {e}")
            claude_bin = _find_claude_cli()
            if claude_bin:
                print("[processor] Falling back to CLI for Phase 1...")
            else:
                raise

    claude_bin = _find_claude_cli()
    if claude_bin:
        return _analyze_frames_with_cli(frame_paths, PHASE1_PROMPT)

    raise RuntimeError("No Claude auth available for Phase 1")


SPAWN_RETRY_CHUNK = 45        # seconds per retry chunk when searching for loading screen


def _maybe_expand_and_retry(
    analysis: dict, video_path: str, frames_dir: str, video_duration: float
) -> dict:
    """If key screens weren't found, expand the search window and retry.

    - loading_screen_found: false -> keep searching in 45s chunks until found or video exhausted
    - stats_tab_found: false -> expand end window to -60s to -30s, one retry
    Spawn coordinates are critical for map tracking, so we don't give up easily.
    """
    loading_found = analysis.get("loading_screen_found", True)
    stats_found = analysis.get("stats_tab_found", True)

    if loading_found and stats_found:
        return analysis

    # -- Retry end frames (stats tab) — one retry is enough --
    if not stats_found and video_duration > 60:
        print("[processor] Stats tab not found, expanding end window to -60s to -30s...")
        for f in glob_mod.glob(os.path.join(frames_dir, 'end_*.jpg')):
            os.remove(f)
        end_start = max(0, video_duration - 60)
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
            '-ss', str(end_start), '-t', '30',
            '-i', video_path,
            '-vf', f'scale={FRAME_RESOLUTION}:-2,fps={FRAME_FPS_END}',
            '-q:v', '3',
            os.path.join(frames_dir, 'end_%04d.jpg'),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"[processor] FFmpeg end frame expansion failed: {result.stderr[:200]}")

    # -- Retry start frames (loading screen) — keep searching in chunks --
    search_offset = FRAME_DURATION_START  # start after the initial window
    max_search = video_duration

    while not loading_found and search_offset < max_search:
        chunk_end = min(search_offset + SPAWN_RETRY_CHUNK, max_search)
        chunk_duration = chunk_end - search_offset
        print(f"[processor] Loading screen not found, searching {search_offset:.0f}-{chunk_end:.0f}s...")

        for f in glob_mod.glob(os.path.join(frames_dir, 'start_*.jpg')):
            os.remove(f)
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
            '-ss', str(search_offset), '-t', str(chunk_duration),
            '-i', video_path,
            '-vf', f'scale={FRAME_RESOLUTION}:-2,fps={FRAME_FPS_START}',
            '-q:v', '3',
            os.path.join(frames_dir, 'start_%04d.jpg'),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"[processor] FFmpeg start frame chunk failed: {result.stderr[:200]}")
            break

        # Analyze just the start frames for spawn data
        try:
            print(f"[processor] Analyzing chunk {search_offset:.0f}-{chunk_end:.0f}s for spawn...")
            retry_analysis = analyze_frames_phase1(frames_dir)
            loading_found = retry_analysis.get("loading_screen_found", False)

            # Merge spawn data if found
            if loading_found:
                print(f"[processor] Loading screen found at {search_offset:.0f}-{chunk_end:.0f}s!")
                for key in ("map_name", "spawn_coordinates", "spawn_location", "loading_screen_found"):
                    if retry_analysis.get(key) is not None:
                        analysis[key] = retry_analysis[key]
                break

            # Also merge any other data found along the way
            for key, value in retry_analysis.items():
                if value is not None and (analysis.get(key) is None or analysis.get(key) == 0):
                    analysis[key] = value
        except Exception as e:
            print(f"[processor] Chunk analysis failed: {e}")
            break

        search_offset = chunk_end

    if not loading_found:
        print(f"[processor] Loading screen not found after searching entire video ({video_duration:.0f}s)")

    # -- Final merged retry for stats if we expanded end frames --
    if not stats_found:
        try:
            print("[processor] Retrying with expanded end frames...")
            retry_analysis = analyze_frames_phase1(frames_dir)
            for key, value in retry_analysis.items():
                if value is not None and (analysis.get(key) is None or analysis.get(key) == 0):
                    analysis[key] = value
            analysis["stats_tab_found"] = retry_analysis.get("stats_tab_found", False)
            analysis["loadout_tab_found"] = retry_analysis.get(
                "loadout_tab_found", analysis.get("loadout_tab_found")
            )
        except Exception as e:
            print(f"[processor] End frame retry failed: {e}")

    return analysis


# -- Video compression (for Phase 2 / legacy) ------------------------------

def compress_for_analysis(input_path: str, output_path: str) -> bool:
    """Compress video to fit within 2000px for Sonnet CLI analysis.

    The API enforces a 2000px dimension limit when 21+ images are in one
    request. The CLI extracts frames autonomously, so we can't control
    the count -- keep the longest edge at 2000px to be safe.
    Original 4K is kept for clip cutting.
    """
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
        '-i', input_path,
        '-vf', 'scale=2000:-2',
        '-r', '30',
        '-c:v', 'libx264', '-crf', '26', '-preset', 'fast',
        '-an',
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[processor] 2K compression failed: {result.stderr[:200]}")
            return False
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
    except Exception as e:
        print(f"[processor] 2K compression error: {e}")
        return False


def compress_for_api(input_path: str, output_path: str, max_size_mb: int = 20) -> bool:
    """Compress video to 720p low-bitrate for API upload."""
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
        '-i', input_path,
        '-vf', 'scale=1280:720',
        '-r', '2',
        '-c:v', 'libx264', '-crf', '32', '-preset', 'fast',
        '-an',
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"[processor] Compression failed: {result.stderr}")
            return False

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"[processor] Compressed: {size_mb:.1f}MB")

        if size_mb > max_size_mb:
            cmd2 = [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
                '-i', input_path,
                '-vf', 'scale=854:480',
                '-r', '1',
                '-c:v', 'libx264', '-crf', '38', '-preset', 'fast',
                '-an',
                output_path,
            ]
            result2 = subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
            if result2.returncode != 0:
                print(f"[processor] Re-compression failed: {result2.stderr[:200]}")
                return False
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"[processor] Re-compressed: {size_mb:.1f}MB")

        return True
    except Exception as e:
        print(f"[processor] Compression error: {e}")
        return False


# -- Phase 2 analysis (video -> narrative) ---------------------------------

def _analyze_phase2_with_cli(video_path: str) -> dict:
    """Send video to CLI for Phase 2 narrative analysis."""
    claude_bin = _find_claude_cli()
    if not claude_bin:
        raise RuntimeError("Claude CLI not found")

    abs_path = os.path.abspath(video_path).replace("\\", "/")
    prompt = f"""There is a gameplay video file at: {abs_path}

Watch this video and extract the information below. You have access to ffmpeg and ffprobe to inspect the video, extract frames, and read them.

{PHASE2_PROMPT}"""

    cmd = [claude_bin, "-p", prompt, "--model", "sonnet",
           "--dangerously-skip-permissions"]
    print(f"[processor-p2] CLI analyzing video for narrative...")

    proc = subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    output_lines = []
    try:
        for line in iter(proc.stdout.readline, b''):
            decoded = line.decode("utf-8", errors="replace").rstrip()
            if decoded:
                output_lines.append(decoded)
                preview = decoded[:200] if len(decoded) > 200 else decoded
                print(f"[cli-p2] {preview}")
        proc.wait(timeout=1800)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError("Phase 2 CLI timed out after 30 minutes")

    stderr_out = proc.stderr.read().decode("utf-8", errors="replace").strip() if proc.stderr else ""
    if stderr_out:
        print(f"[cli-p2 stderr] {stderr_out[:500]}")

    output = "\n".join(output_lines).strip()
    if not output:
        raise RuntimeError(f"Phase 2 CLI returned no output. exit={proc.returncode}")

    return _extract_json(output)


def _analyze_phase2_with_api(video_path: str) -> dict:
    """Send video to API for Phase 2 narrative analysis (fallback)."""
    import anthropic

    with open(video_path, "rb") as f:
        video_data = base64.standard_b64encode(f.read()).decode("utf-8")

    size_mb = os.path.getsize(video_path) / (1024 * 1024)
    print(f"[processor-p2] Sending {size_mb:.1f}MB video to API for narrative...")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "video",
                    "source": {
                        "type": "base64",
                        "media_type": "video/mp4",
                        "data": video_data,
                    },
                },
                {"type": "text", "text": PHASE2_PROMPT},
            ],
        }],
    )
    return _extract_json(message.content[0].text)


def analyze_video_phase2(video_path: str) -> dict:
    """Phase 2: analyze video for narrative content. CLI first, API fallback."""
    claude_bin = _find_claude_cli()
    if claude_bin:
        try:
            return _analyze_phase2_with_cli(video_path)
        except Exception as e:
            print(f"[processor-p2] CLI failed: {e}")
            if settings.anthropic_api_key:
                print("[processor-p2] Falling back to API for Phase 2...")
            else:
                raise

    if settings.anthropic_api_key:
        return _analyze_phase2_with_api(video_path)

    raise RuntimeError("No Claude auth available for Phase 2")


# -- Legacy video analysis (fallback for Phase 1 failure) ------------------

def analyze_with_api(video_path: str) -> dict:
    """Send video to Claude Sonnet via API key."""
    import anthropic

    with open(video_path, "rb") as f:
        video_data = base64.standard_b64encode(f.read()).decode("utf-8")

    size_mb = os.path.getsize(video_path) / (1024 * 1024)
    print(f"[processor] Sending {size_mb:.1f}MB video to Sonnet API...")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "video",
                    "source": {
                        "type": "base64",
                        "media_type": "video/mp4",
                        "data": video_data,
                    },
                },
                {"type": "text", "text": VIDEO_PROMPT},
            ],
        }],
    )
    return _extract_json(message.content[0].text)


def analyze_with_cli(video_path: str) -> dict:
    """Send video to Claude Sonnet via CLI (uses OAuth/Max subscription)."""
    claude_bin = _find_claude_cli()
    if not claude_bin:
        raise RuntimeError("Claude CLI not found")

    abs_path = os.path.abspath(video_path).replace("\\", "/")
    prompt = f"""There is a gameplay video file at: {abs_path}

Analyze this video and extract the information below. You have access to ffmpeg and ffprobe to inspect the video, extract frames, and read them.

{VIDEO_PROMPT}"""

    cmd = [claude_bin, "-p", prompt, "--model", "sonnet",
           "--dangerously-skip-permissions"]
    print(f"[processor] CLI command: {' '.join(cmd[:5])}...")
    print(f"[processor] Video path: {abs_path}")

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    output_lines = []
    try:
        for line in iter(proc.stdout.readline, b''):
            decoded = line.decode("utf-8", errors="replace").rstrip()
            if decoded:
                output_lines.append(decoded)
                preview = decoded[:200] if len(decoded) > 200 else decoded
                print(f"[cli] {preview}")

        proc.wait(timeout=1800)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError("CLI timed out after 30 minutes")

    stderr_out = proc.stderr.read().decode("utf-8", errors="replace").strip() if proc.stderr else ""
    if stderr_out:
        print(f"[cli stderr] {stderr_out[:500]}")

    output = "\n".join(output_lines).strip()
    print(f"[processor] CLI finished: exit={proc.returncode}, output={len(output)} chars")

    if not output:
        raise RuntimeError(f"CLI returned no output. exit={proc.returncode}, stderr: {stderr_out[:500]}")

    return _extract_json(output)


def analyze_video(video_path: str) -> dict:
    """Legacy: analyze video using CLI first, fallback to API."""
    claude_bin = _find_claude_cli()
    if claude_bin:
        try:
            return analyze_with_cli(video_path)
        except Exception as e:
            print(f"[processor] CLI failed: {e}")
            if settings.anthropic_api_key:
                print("[processor] Falling back to API...")
            else:
                raise

    if settings.anthropic_api_key:
        return analyze_with_api(video_path)

    raise RuntimeError("No Claude auth available. Install Claude CLI or set ANTHROPIC_API_KEY.")


# -- Clip cutting -----------------------------------------------------------

def cut_clips(source_path: str, clips_dir: str, highlights: list[dict], run_timestamp: str | None = None) -> list[str]:
    """Cut highlight clips from the original full-quality video.

    Uses stream copy (no re-encoding) for instant cuts.
    Uses the run's recording timestamp in filename to link clips to runs.
    Returns list of clip file paths.
    """
    os.makedirs(clips_dir, exist_ok=True)
    clip_paths = []

    tag = run_timestamp or datetime.now().strftime('%Y%m%d_%H%M%S')

    for i, h in enumerate(highlights):
        ts = h.get("timestamp_seconds", 0)
        dur = h.get("duration_seconds", 12)
        clip_type = h.get("type", "highlight")

        # Start 3 seconds before the moment
        start = max(0, ts - 3)

        filename = f"clip_{tag}_{clip_type}_{i+1}.mp4"
        clip_path = os.path.join(clips_dir, filename)

        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
            '-ss', str(start),
            '-i', source_path,
            '-t', str(dur),
            '-c', 'copy',
            clip_path,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                print(f"[processor] Clip FFmpeg failed: {result.stderr[:200]}")
                continue
            if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                clip_paths.append(clip_path)
                print(f"[processor] Clip saved: {filename} ({clip_type} @ {ts}s)")

                # Generate thumbnail from middle of clip
                thumb_path = clip_path.replace(".mp4", "_thumb.jpg")
                try:
                    subprocess.run(
                        ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                         '-ss', str(dur // 2), '-i', clip_path,
                         '-vframes', '1', '-vf', 'scale=384:-1',
                         '-q:v', '5', thumb_path],
                        capture_output=True, timeout=10,
                    )
                except Exception:
                    pass
            else:
                print(f"[processor] Clip failed (empty): {filename}")
        except Exception as e:
            print(f"[processor] Clip error: {e}")

    return clip_paths


# -- Database operations ----------------------------------------------------

def _get_finisher_damage(analysis: dict) -> int | None:
    """Extract the finisher's damage from damage_contributors or killed_by_damage."""
    contributors = analysis.get("damage_contributors")
    if contributors and isinstance(contributors, list):
        for c in contributors:
            if c.get("finished"):
                return c.get("damage")
    return analysis.get("killed_by_damage")


def _build_notes(analysis: dict) -> str:
    """Build notes string including damage contributors if available."""
    parts = ["Auto-captured."]
    contributors = analysis.get("damage_contributors")
    if contributors and isinstance(contributors, list) and len(contributors) > 1:
        dmg_lines = []
        for c in contributors:
            tag = " (finished)" if c.get("finished") else ""
            dmg_lines.append(f"{c.get('name', '?')}: {c.get('damage', '?')} DMG{tag}")
        parts.append("Damage: " + ", ".join(dmg_lines))
    return " ".join(parts)


def save_run_to_db(analysis: dict, run_date: datetime | None = None) -> int | None:
    """Insert the analyzed run into the database. Returns the run ID.

    Also creates a spawn point if coordinates were extracted from the
    deployment loading screen, and matches the shell (runner) by name.
    """
    from .database import SessionLocal
    from .models import Run, SpawnPoint, Runner

    try:
        db = SessionLocal()

        # Create or match spawn point from loading screen coordinates.
        COORD_THRESHOLD = 5.0
        spawn_point_id = None
        coords = analysis.get("spawn_coordinates")
        if coords and isinstance(coords, list) and len(coords) == 2:
            coord_x, coord_y = float(coords[0]), float(coords[1])

            all_spawns = db.query(SpawnPoint).filter(
                SpawnPoint.game_coord_x.isnot(None),
                SpawnPoint.game_coord_y.isnot(None),
            ).all()

            best_match = None
            best_dist = float('inf')
            for sp in all_spawns:
                dist = ((sp.game_coord_x - coord_x) ** 2 + (sp.game_coord_y - coord_y) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_match = sp

            if best_match and best_dist < COORD_THRESHOLD:
                spawn_point_id = best_match.id
                n = len(best_match.runs) + 1
                best_match.game_coord_x = best_match.game_coord_x + (coord_x - best_match.game_coord_x) / n
                best_match.game_coord_y = best_match.game_coord_y + (coord_y - best_match.game_coord_y) / n
                db.commit()
                print(f"[processor] Matched spawn #{spawn_point_id} '{best_match.spawn_location}' (dist={best_dist:.1f}, avg updated)")
            else:
                spawn = SpawnPoint(
                    map_name=analysis.get("map_name") or "Unknown",
                    spawn_location=analysis.get("spawn_location"),
                    game_coord_x=coord_x,
                    game_coord_y=coord_y,
                    notes=f"Auto-detected coordinates: {coord_x}, {coord_y}",
                )
                db.add(spawn)
                db.commit()
                db.refresh(spawn)
                spawn_point_id = spawn.id
                print(f"[processor] New spawn #{spawn_point_id} created: ({coord_x}, {coord_y})")

        # Match shell (runner) by name from lobby screen
        runner_id = None
        shell_name = analysis.get("shell_name")
        if shell_name:
            runner = db.query(Runner).filter(
                Runner.name.ilike(shell_name)
            ).first()
            if runner:
                runner_id = runner.id
                print(f"[processor] Matched shell: {runner.name} (#{runner.id})")
            else:
                runner = Runner(name=shell_name)
                db.add(runner)
                db.commit()
                db.refresh(runner)
                runner_id = runner.id
                print(f"[processor] New shell created: {shell_name} (#{runner.id})")

        run = Run(
            map_name=analysis.get("map_name"),
            date=run_date or datetime.utcnow(),
            survived=analysis.get("survived"),
            kills=analysis.get("kills", 0),
            combatant_eliminations=analysis.get("combatant_eliminations", 0),
            runner_eliminations=analysis.get("runner_eliminations", 0),
            deaths=analysis.get("deaths", 0),
            assists=analysis.get("assists", 0),
            crew_revives=analysis.get("crew_revives", 0),
            duration_seconds=analysis.get("duration_seconds"),
            loot_value_total=analysis.get("loot_value_total", 0.0),
            primary_weapon=analysis.get("primary_weapon"),
            secondary_weapon=analysis.get("secondary_weapon"),
            killed_by=analysis.get("killed_by"),
            killed_by_damage=_get_finisher_damage(analysis),
            player_gamertag=analysis.get("player_gamertag"),
            squad_members=analysis.get("squad_members"),
            spawn_point_id=spawn_point_id,
            runner_id=runner_id,
            grade=analysis.get("grade"),
            summary=analysis.get("summary"),
            notes=_build_notes(analysis),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
        db.close()
        print(f"[processor] Run #{run_id} saved to database")
        return run_id
    except Exception as e:
        print(f"[processor] DB error: {e}")
        db.close()
        return None


def update_run_phase2(run_id: int, phase2_data: dict) -> bool:
    """Update an existing run with Phase 2 narrative data.

    Only writes grade, summary -- NEVER overwrites Phase 1 stats.
    """
    from .database import SessionLocal
    from .models import Run

    try:
        db = SessionLocal()
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            print(f"[processor-p2] Run #{run_id} not found for Phase 2 update")
            db.close()
            return False

        if phase2_data.get("grade"):
            run.grade = phase2_data["grade"]
        if phase2_data.get("summary"):
            run.summary = phase2_data["summary"]

        db.commit()
        db.close()
        print(f"[processor-p2] Run #{run_id} updated with Phase 2 (grade={phase2_data.get('grade')})")
        return True
    except Exception as e:
        print(f"[processor-p2] DB update error: {e}")
        db.close()
        return False


# -- Metrics logging --------------------------------------------------------

def _save_metrics(metrics: dict):
    """Append pipeline metrics to a JSON log file for analysis optimization."""
    from .config import _DATA_DIR

    metrics_file = os.path.join(_DATA_DIR, "sonnet_metrics.json")
    try:
        existing = []
        if os.path.exists(metrics_file):
            with open(metrics_file, 'r') as f:
                existing = json.load(f)

        existing.append(metrics)

        with open(metrics_file, 'w') as f:
            json.dump(existing, f, indent=2)

        print(f"[metrics] Logged: {metrics.get('recording')} | "
              f"video={metrics.get('video_duration_seconds', '?')}s | "
              f"analysis={metrics.get('analysis_seconds', metrics.get('phase1_analysis_seconds', '?'))}s | "
              f"total={metrics.get('total_seconds', '?')}s | "
              f"{metrics.get('status')}")
    except Exception as e:
        print(f"[metrics] Failed to save: {e}")


# -- Main pipelines --------------------------------------------------------

def process_recording(recording_path: str, clips_dir: str, on_phase=None) -> dict:
    """Phase 1 pipeline: extract frames -> analyze stats -> save to DB.

    Returns a result dict with status, run_id, and phase1_only flag.
    If Phase 1 fails, falls back to legacy full-video analysis.
    on_phase: optional callback(phase_name) for UI progress tracking.
    """
    def phase(name):
        if on_phase:
            on_phase(name)

    result = {
        "status": "error",
        "recording": recording_path,
        "analysis": None,
        "clips": [],
        "run_id": None,
        "phase1_only": False,
    }

    if not os.path.exists(recording_path):
        print(f"[processor] File not found: {recording_path}")
        return result

    file_size_mb = os.path.getsize(recording_path) / (1024 * 1024)
    print(f"[processor] Processing: {recording_path} ({file_size_mb:.0f}MB)")

    # Metrics tracking
    pipeline_start = time.time()
    metrics = {
        "recording": os.path.basename(recording_path),
        "file_size_mb": round(file_size_mb, 1),
        "started_at": datetime.utcnow().isoformat(),
    }

    # Get video duration
    video_duration = _get_video_duration(recording_path)
    if video_duration:
        metrics["video_duration_seconds"] = round(video_duration, 1)

    # Get resolution
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'stream=width,height',
             '-of', 'csv=p=0', recording_path],
            capture_output=True, text=True, timeout=10,
        )
        wh = probe.stdout.strip().split(',')
        if len(wh) >= 2:
            metrics["resolution"] = f"{wh[0]}x{wh[1]}"
    except Exception:
        pass

    # Extract run timestamp from recording filename
    rec_basename = os.path.basename(recording_path).replace(".mp4", "").replace("run_", "")
    try:
        run_date = datetime.strptime(rec_basename, "%Y%m%d_%H%M%S")
    except ValueError:
        run_date = None

    analysis = None
    use_legacy = False

    # -- Try Phase 1: frame extraction + image analysis --------------------
    if video_duration:
        frames_dir = recording_path.replace(".mp4", "_frames")
        try:
            phase("extracting_frames")
            t0 = time.time()
            extract_key_frames(recording_path, frames_dir, video_duration)
            metrics["frame_extraction_seconds"] = round(time.time() - t0, 1)

            phase("analyzing_stats")
            t0 = time.time()
            analysis = analyze_frames_phase1(frames_dir)

            # Retry with expanded windows if key screens not found
            analysis = _maybe_expand_and_retry(
                analysis, recording_path, frames_dir, video_duration
            )

            metrics["phase1_analysis_seconds"] = round(time.time() - t0, 1)
            result["phase1_only"] = True

            print(f"[processor] Phase 1 result: {analysis.get('map_name')} | "
                  f"{'SURVIVED' if analysis.get('survived') else 'DIED'} | "
                  f"{analysis.get('kills', 0)} kills | "
                  f"loading={'Y' if analysis.get('loading_screen_found') else 'N'} "
                  f"stats={'Y' if analysis.get('stats_tab_found') else 'N'}")

        except Exception as e:
            print(f"[processor] Phase 1 failed: {e}, falling back to full-video")
            use_legacy = True
        finally:
            if os.path.isdir(frames_dir):
                shutil.rmtree(frames_dir, ignore_errors=True)
    else:
        print("[processor] Could not determine video duration, using legacy pipeline")
        use_legacy = True

    # -- Legacy fallback: compress + full video analysis -------------------
    if use_legacy:
        compressed_path = recording_path.replace(".mp4", "_2k.mp4")
        analysis_path = recording_path
        t0 = time.time()

        if os.path.exists(compressed_path) and os.path.getsize(compressed_path) > 1024 * 1024:
            analysis_path = compressed_path
            print(f"[processor] 2K already exists (skipping compression)")
        else:
            phase("compressing")
            if compress_for_analysis(recording_path, compressed_path):
                analysis_path = compressed_path
                comp_size = os.path.getsize(compressed_path) / (1024 * 1024)
                print(f"[processor] Compressed to 2K: {comp_size:.0f}MB")
            else:
                print("[processor] 2K compression failed, using original...")
                compressed_path = None

        phase("analyzing")
        try:
            analysis = analyze_video(analysis_path)
            metrics["analysis_seconds"] = round(time.time() - t0, 1)
        except Exception as e:
            print(f"[processor] Legacy analysis failed: {e}")
            metrics["status"] = "error"
            metrics["error"] = str(e)[:200]
            _save_metrics(metrics)
            if compressed_path and os.path.exists(compressed_path):
                os.remove(compressed_path)
            return result

        if compressed_path and os.path.exists(compressed_path):
            os.remove(compressed_path)

        result["phase1_only"] = False  # Legacy has everything

    if not analysis:
        return result

    result["analysis"] = analysis

    # -- Save to database --------------------------------------------------
    phase("saving")
    run_id = save_run_to_db(analysis, run_date=run_date)
    result["run_id"] = run_id

    # If legacy (not phase1_only), also cut clips now since we have highlights
    if not result["phase1_only"]:
        phase("cutting_clips")
        highlights = analysis.get("highlights", [])
        if highlights:
            result["clips"] = cut_clips(
                recording_path, clips_dir, highlights, run_timestamp=rec_basename
            )
            print(f"[processor] Created {len(result['clips'])} clips")

    # Metrics
    metrics["total_seconds"] = round(time.time() - pipeline_start, 1)
    metrics["status"] = "phase1_done" if result["phase1_only"] else "success"
    metrics["run_id"] = run_id
    metrics["clips_count"] = len(result.get("clips", []))
    metrics["map"] = analysis.get("map_name")
    metrics["grade"] = analysis.get("grade")
    _save_metrics(metrics)

    result["status"] = "success"
    return result


def process_recording_phase2(
    recording_path: str, clips_dir: str, run_id: int, on_phase=None
) -> dict:
    """Phase 2 pipeline: compress -> narrative analysis -> update run -> cut clips.

    Runs after Phase 1 completes in the same worker thread.
    If it fails, the run keeps Phase 1 data (still useful).
    """
    def phase(name):
        if on_phase:
            on_phase(name)

    result = {
        "status": "error",
        "clips": [],
    }

    rec_basename = os.path.basename(recording_path).replace(".mp4", "").replace("run_", "")
    pipeline_start = time.time()

    # Step 1: Compress to 2K for CLI analysis
    compressed_path = recording_path.replace(".mp4", "_2k.mp4")
    analysis_path = recording_path

    if os.path.exists(compressed_path) and os.path.getsize(compressed_path) > 1024 * 1024:
        analysis_path = compressed_path
        print(f"[processor-p2] 2K already exists, skipping compression")
    else:
        phase("compressing")
        t0 = time.time()
        if compress_for_analysis(recording_path, compressed_path):
            analysis_path = compressed_path
            comp_size = os.path.getsize(compressed_path) / (1024 * 1024)
            print(f"[processor-p2] Compressed to 2K: {comp_size:.0f}MB in {time.time() - t0:.0f}s")
        else:
            print("[processor-p2] Compression failed, using original")
            compressed_path = None

    # Step 2: Analyze video for narrative
    phase("analyzing_gameplay")
    t0 = time.time()
    try:
        phase2_data = analyze_video_phase2(analysis_path)
        print(f"[processor-p2] Phase 2 analysis took {time.time() - t0:.0f}s, "
              f"grade={phase2_data.get('grade')}")
    except Exception as e:
        print(f"[processor-p2] Phase 2 analysis failed: {e}")
        if compressed_path and os.path.exists(compressed_path):
            os.remove(compressed_path)
        result["status"] = "phase2_failed"
        return result

    # Clean up compressed file
    if compressed_path and os.path.exists(compressed_path):
        os.remove(compressed_path)

    # Step 3: Update run with narrative data (never overwrites stats)
    update_run_phase2(run_id, phase2_data)

    # Step 4: Cut clips from original 4K
    phase("cutting_clips")
    highlights = phase2_data.get("highlights", [])
    if highlights:
        result["clips"] = cut_clips(
            recording_path, clips_dir, highlights, run_timestamp=rec_basename
        )
        print(f"[processor-p2] Created {len(result['clips'])} clips")

    result["status"] = "success"
    print(f"[processor-p2] Phase 2 complete in {time.time() - pipeline_start:.0f}s")
    return result

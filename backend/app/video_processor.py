"""
Video Processor -- Two-phase analysis pipeline for Marathon run recordings.

Phase 1 (Stats, ~1-2 min):
  1. Use OCR screenshots (deploy, readyup, endgame, stats) + extracted end frames
  2. Three parallel CLI calls: loadout/identity, shell ID, spawn coordinates
  3. Sequential call for stats/death/loot from end frames
  4. Save run to database immediately -- stats appear in app fast

Phase 2 (Story + Clips, ~10 min):
  1. Send full video to CLI for narrative analysis (grade, summary, highlights)
  2. Update existing run with narrative data (never overwrites Phase 1 stats)
  3. Cut highlight clips from original recording using stream copy
"""

import base64
import glob as glob_mod
import json
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone

from .config import settings
from . import ai_client


def _check_ffmpeg():
    """Log warning if ffmpeg/ffprobe are not on PATH."""
    if not shutil.which("ffprobe"):
        print("[video_processor] WARNING: ffprobe not found on PATH — video duration detection will fail")
    if not shutil.which("ffmpeg"):
        print("[video_processor] WARNING: ffmpeg not found on PATH — video processing will fail")

_check_ffmpeg()




def _run_claude_cli(cmd: list[str], timeout: int, label: str) -> str:
    """Run Claude CLI with bounded time and complete stdout/stderr draining."""
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=ai_client.cli_env(),
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise RuntimeError(f"{label} timed out")

    output = stdout.decode("utf-8", errors="replace").strip() if stdout else ""
    error_text = stderr.decode("utf-8", errors="replace").strip() if stderr else ""
    if error_text:
        print(f"[processor cli stderr] {label}: {error_text[:500]}")

    if ai_client.is_auth_failure(output) or ai_client.is_auth_failure(error_text):
        raise RuntimeError(
            "Claude CLI is not authenticated. Go to SYS.CONFIG and click LOGIN, "
            "or run `claude auth login` in your terminal."
        )

    if proc.returncode != 0:
        detail = error_text or output or f"exit code {proc.returncode}"
        raise RuntimeError(f"{label} failed: {detail[:500]}")

    return output


# -- Frame extraction settings (easy to tune) -------------------------------
FRAME_RESOLUTION_MAX = 3840   # never upscale beyond source resolution
FRAME_DURATION_START = 90     # seconds from start (loading screen can be 0-90s depending on session spawn wait)
FRAME_FPS_START = 0.5         # deployment loading screen — static, 0.5fps is plenty (~45 frames)
FRAME_FPS_END = 5             # post-match tabs — flip fast, need higher fps


def _get_video_resolution(video_path: str) -> int | None:
    """Get video width in pixels using ffprobe."""
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-select_streams', 'v:0',
             '-show_entries', 'stream=width',
             '-of', 'csv=p=0', video_path],
            capture_output=True, text=True, timeout=10,
        )
        return int(probe.stdout.strip())
    except Exception as e:
        print(f"[video_processor] Failed to get video resolution: {e}")
        return None


def _frame_resolution(video_path: str) -> int:
    """Determine frame extraction resolution: use native, never upscale."""
    native = _get_video_resolution(video_path)
    if native and native <= FRAME_RESOLUTION_MAX:
        print(f"[processor] Video is {native}px wide — extracting at native resolution")
        return native
    print(f"[processor] Video is {native or '?'}px wide — capping at {FRAME_RESOLUTION_MAX}px")
    return FRAME_RESOLUTION_MAX


# -- Phase 1 Call 2 prompt (end-of-run frames — stats, death, loot) -----------
# Call 1 prompt (loadout/identity) is inline in _analyze_with_screenshots()

PHASE1_CALL2_PROMPT = """You are analyzing end-of-run screenshots from a Marathon (Bungie 2026 extraction shooter) gameplay recording.

These images are from the LAST 30 SECONDS of the run. Look for:
- **//RUN_COMPLETE screen**: Appears at the end of every run. If the player was ELIMINATED, a "NEURAL LINK SEVERED" widget appears on the RIGHT side showing who killed them (gamertag#number), damage, and ALL damage contributors. If the player EXTRACTED, this widget is absent. Read EVERY contributor, do not skip any.
- **POST-MATCH REPORTS**: After a run ends, three report screens are shown. They are navigated via tabs in the TOP-RIGHT corner labeled "STATS", "PROGRESS", "LOADOUT". The ACTIVE screen is indicated by its tab being HIGHLIGHTED (bright/filled) in the top-right — the other tabs appear dimmed. The player clicks through them in order:
  1. **STATS** (tab highlighted in top-right): First screen. Shows "EXFILTRATED" or "ELIMINATED" status, player stats in columns (local player is CENTER column). Look for "Combatant Eliminations" (PvE), "Runner Eliminations" (PvP), "Crew Revives", "Inventory Value" (loot), "Run Time" (MM:SS). USE THESE EXACT NUMBERS.
  2. **PROGRESS REPORT** (tab highlighted in top-right): Second screen. Title "PROGRESS REPORT" at top-left. Shows "SEASON LEVEL" label with an XP progress bar below it.
     **ANIMATION WARNING**: Like the LOADOUT REPORT, the PROGRESS REPORT animates in. The season level starts at the PRE-RUN value and ticks up if the player leveled up. The number shown mid-animation is STALE.
     **CROSS-REFERENCE**: The TOP-LEFT pill on the screen always shows the correct post-run season level (green circular icon + number, e.g. 34). This is ALWAYS the final value. Use the TOP-LEFT pill as ground truth for player level, not the animated "SEASON LEVEL" number in the body of the report.
  3. **LOADOUT REPORT** (tab highlighted in top-right): Third screen. Title "LOADOUT REPORT" at top-left. Shows weapons extracted with mod slots, backpack grid on the right, and "Wallet Balance:" in bright green text at the bottom-left.
     **ANIMATION WARNING**: The LOADOUT REPORT (and PROGRESS REPORT) animate in their data over 1-2 seconds. When first opened, values are STALE (from before the run). Items tick in one by one, and ONLY when "Report Summary" appears at the bottom of the left column (with "Exfil Successful" or similar) are the numbers FINAL. If "Report Summary" is NOT visible, the Wallet Balance is STALE — do NOT use it.
     **CROSS-REFERENCE**: The TOP BAR of the screen always shows a pill with the player's vault value (e.g. the gear icon + "66,149"). This top bar value is ALWAYS the final/correct value. Use it as ground truth. The Wallet Balance at the bottom should MATCH the top bar value — if it doesn't, the animation hasn't finished and you should use the TOP BAR value instead.

The STATS screen is GROUND TRUTH — use its exact numbers. Do NOT estimate from gameplay.

Return ONLY valid JSON:
{
  "survived": true if "EXFILTRATED" or "Exit Successful", false if "ELIMINATED" or died, or null if unclear,
  "kills": total from STATS tab (Combatant + Runner Eliminations) or null if not visible,
  "combatant_eliminations": exact number from STATS tab "Combatant Eliminations" or null,
  "runner_eliminations": exact number from STATS tab "Runner Eliminations" or null,
  "deaths": 0 if EXFILTRATED, 1 if died, or null if unclear,
  "crew_revives": exact number from STATS tab "Crew Revives" or null,
  "duration_seconds": convert STATS tab "Run Time" MM:SS to total seconds or null,
  "loot_value_total": "Inventory Value" from STATS or null. NEVER zero for survived runs. Check LOADOUT REPORT "Wallet Balance" gain if STATS not found.,
  "primary_weapon": "weapon name from LOADOUT REPORT" or null,
  "secondary_weapon": "weapon name from LOADOUT REPORT" or null,
  "killed_by": "exact gamertag#number of finisher from death screen" or null,
  "killed_by_weapon": "weapon from death screen" or null,
  "killed_by_damage": finisher's damage number from death screen or null,
  "damage_contributors": [{"name": "gamertag", "damage": number, "finished": true/false}] or null — list ALL players/enemies from the death screen. The finisher has "finished": true. Include EVERY entry, even UESC Recruits or AI enemies.,
  "player_gamertag": "local player's gamertag from STATS tab (CENTER column)" or null,
  "squad_members": ["all", "squad", "gamertags", "from STATS tab columns"] or null — include ALL members shown,
  "player_level": season level from the TOP-LEFT pill on screen (green circular icon + number, always correct). Do NOT use the animated "SEASON LEVEL" number in the PROGRESS REPORT body — it may be mid-animation and stale. The top-left pill is ground truth. Or null,
  "vault_value": vault value from the TOP BAR pill (gear icon + number, always correct) or from "Wallet Balance" at bottom of LOADOUT REPORT ONLY if "Report Summary" is visible. Top bar is ground truth — if Wallet Balance differs from top bar, use the top bar value. Or null,
  "stats_tab_found": true if you found the STATS tab with kill/loot numbers,
  "stats_tab_needs_more_frames": true if stats tab is visible but too blurry/fast to read — request higher fps,
  "loadout_tab_found": true if you found the LOADOUT REPORT with weapons/wallet
}

IMPORTANT: Return null for ANY field you cannot confidently read. Do NOT guess or default to 0. null means "not found" — 0 means "the STATS tab explicitly showed 0". These are different.

FONT NOTE: Marathon uses a slashed-zero font where the digit 0 has a diagonal line through it. Do NOT misread 0 as 8. If a digit looks like it could be 0 or 8, it is almost certainly 0 (slashed zero). Pay extra attention to damage numbers.

Return ONLY valid JSON, no markdown fences, no explanation."""


# -- Phase 2 prompt (narrative only, for video) -----------------------------

PHASE2_PROMPT = """You are analyzing a recorded Marathon (Bungie 2026 extraction shooter) gameplay run.

The run's stats (kills, loot, survival, killed_by) have ALREADY been extracted by Phase 1. Do NOT extract or return any stats. Phase 2 is ONLY for narrative analysis.

You MUST complete three steps IN ORDER. Do all three before outputting the final JSON.

=== STEP 1: SCENE INVENTORY ===

Go through every frame and classify the video into segments. For each ~10-second window, write one line:

  [TIMESTAMP_START - TIMESTAMP_END] CATEGORY — brief note

Categories:
  IDLE — player walking, running, looting containers, no enemies visible, no combat
  COMBAT — active firefight, enemies visible on screen, shots being fired, hit markers, damage effects
  MENU — inventory screen, loadout screen, map screen (NEVER clip these)
  DEATH — NEURAL LINK SEVERED screen, black screen with killer info
  EXTRACTION — MATTER TRANSFER IN countdown, player glowing/phasing out
  POSTGAME — //RUN_COMPLETE banner, stats/progress/loadout report screens
  LOADING — solid color screens, deployment loading

Output this full timeline before moving to Step 2.

=== STEP 2: EVENT IDENTIFICATION ===

Now review ONLY the segments you marked as COMBAT, DEATH, or EXTRACTION. For each one, answer:

  [TIMESTAMP] EVENT TYPE — What happened? Who was involved?
  - Is the player dealing damage (hit markers, crosshair flash) or taking damage (red vignette, health bar dropping)?
  - Kill feed: any "[Name] eliminated [Name]" messages? Runner names have # tags (e.g. kale#8064). UESC names are NPCs.
  - Does the player kill a RUNNER (human, name with #)? → pvp_kill
  - Does the player die (NEURAL LINK SEVERED screen)? → death
  - Does the player revive a teammate (approach downed mate + revive animation)? → revive
  - Does the player nearly die but survive (critical health, red screen)? → close_call
  - Is this the extraction sequence (MATTER TRANSFER IN countdown)? → extraction
  - Is this just PvE combat with no notable outcome? → combat
  - Purple/gold rarity item pickup? → loot

Cross-check against Phase 1 stats: if Phase 1 says N runner kills, you must find exactly N pvp_kill events. If you cannot find one, say so — do NOT fabricate.

Output this event list before moving to Step 3.

=== STEP 3: FINAL OUTPUT ===

Using ONLY the events identified in Step 2, produce the final JSON. Every highlight MUST reference an event from Step 2 — you cannot add highlights for timestamps you classified as IDLE or MENU in Step 1.

MARATHON HUD GUIDE — use these visual cues to identify events:
- **TIMER**: Top-left corner, red pill showing remaining time (e.g. "1:56", "20:07"). Counts down.
- **COMPASS**: Top-center bar with cardinal directions (N, NE, E, etc.) and location name below.
- **SQUAD LIST**: Left side, vertical list of squad member gamertags with shell icons.
- **HEALTH BAR**: Bottom-left, horizontal bar. Green = healthy. When critically low, screen edges flash red.
- **WEAPON HUD**: Bottom-center, weapon icon + ammo count. Three ability icons (F, G, V).
- **CROSSHAIR**: Center screen. WHITE FLASH = dealing damage (hit markers). Red X = headshot.
- **KILL FEED**: Top-left area near timer. "[PlayerName] eliminated [TargetName]". Runner names have #numbers. UESC names are NPCs.
- **DAMAGE VIGNETTE**: Red overlay on screen edges when taking damage.
- **DEATH SCREEN**: Full black screen, "NEURAL LINK SEVERED" text, killer info widget on right.
- **//RUN_COMPLETE**: Bright yellow/green banner on black background.
- **EXTRACTION UI**: "MATTER TRANSFER IN" + countdown timer, player glowing/phasing.
- **INVENTORY SCREEN**: Full-screen menu with weapons, backpack. NEVER clip this.

Return ONLY valid JSON (no markdown fences):
{
  "grade": "S, A, B, C, D, or F",
  "summary": "Narrative story in second person (you). Scale: F/D or <3min = 1-2 sentences; C or 3-5min = 1 short paragraph; B or 5-10min = 1-2 paragraphs; A/S or 10+min = 2-4 paragraphs. Sports commentator recap style — the drop, key fights, turning points, how it ended.",
  "highlights": [
    {
      "timestamp_seconds": number,
      "duration_seconds": number,
      "type": "pvp_kill" or "combat" or "death" or "revive" or "close_call" or "extraction" or "loot" or "funny",
      "description": "What is ON SCREEN at this timestamp — be specific about what you see"
    }
  ]
}

GRADING CRITERIA — Marathon is an EXTRACTION shooter. Survival and loot matter MORE than kills.
Weight: Survival (35%) > Runner Kills (25%) > Loot (15%) > Revives (10%) > PvE Kills (5%) > Base (10%)
- S: Extracted with high loot ($3k+), runner kills, long run (10+ min), clean execution. OR exceptional loot ($5k+) even without kills.
- A: Extracted with good loot ($1k+), some kills, solid play. OR survived a long dangerous run (10+ min) with good loot.
- B: Extracted with modest loot, or died mid-run but put up a real fight — runner kills, extended combat.
- C: Extracted quickly with minimal loot and no kills. OR died in an average firefight.
- D: Died relatively quickly with little to show — few kills, low loot, short run (<3 min).
- F: Died almost immediately (<1 min), no kills, no loot.

HIGHLIGHT RULES:

PRIORITY: pvp_kill > death > revive > close_call > extraction > combat > loot > funny.

MANDATORY — ALWAYS include if they happened:
- Every PVP KILL (runner kill) — NEVER skip one
- The DEATH moment — if the player died
- Every REVIVE — if the player revived a teammate
- The EXTRACTION — if the player extracted

After mandatory clips, include all other notable combat moments, close calls, and loot finds.

CLIP TYPES:
- "pvp_kill": Player kills a RUNNER (human, name with #). Capture the FULL ENCOUNTER from first shots through the kill. Combine multi-kills within 20s into one clip.
- "death": FULL encounter leading to death — from first contact through NEURAL LINK SEVERED.
- "revive": Approach to downed teammate + full revive animation.
- "close_call": Player nearly dies but survives — critical health visible. If death follows shortly, it's a "death" clip instead.
- "extraction": MATTER TRANSFER IN countdown and escape.
- "combat": Extended firefight with enemies VISIBLE and shots being fired. Walking/running with no enemies is NOT combat.
- "loot": ONLY purple/gold rarity item pickups or locked crate openings.
- "funny": Unusual or unexpected events.

TIMESTAMP RULES:
- Encounter clips (pvp_kill, death, close_call, combat): timestamp = when the ENCOUNTER BEGINS (first shots/contact).
- Moment clips (extraction, loot, funny): timestamp = exact moment. System adds 3s lead-up.

DURATION (short and punchy):
- pvp_kill: 8-15s, MAX 20s
- death: 8-15s, MAX 20s
- revive: 6-10s, MAX 15s
- close_call: 8-15s, MAX 20s
- combat: 10-20s, MAX 25s
- extraction: 10-15s, MAX 20s
- loot: 5-8s, MAX 10s
- funny: 5-12s, MAX 15s

NEVER CLIP: menus, stats screens, traversal with no enemies, solid color screens, common item pickups.
SPACING: Clips must be 30+ seconds apart. Combine or pick the better one if closer.
OVERLAPPING: One fight = one clip, typed by how it ends (combat→kill = pvp_kill, combat→death = death).

Return ONLY valid JSON, no markdown fences, no explanation."""



# -- Helpers ----------------------------------------------------------------


def _extract_json(text: str) -> dict:
    """Extract JSON from Sonnet response, handling extra text robustly.

    Scans for ALL balanced JSON objects in the text and returns the best match
    (one containing expected keys like 'grade', 'survived', 'kills').
    Handles chain-of-thought output where JSON appears mid-stream with commentary after.
    """
    text = text.strip()

    # Strip markdown fences
    if "```" in text:
        import re
        fence_match = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

    # Find ALL balanced JSON objects in the text
    candidates = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
            for j in range(i, len(text)):
                if text[j] == '{':
                    depth += 1
                elif text[j] == '}':
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(text[i:j + 1])
                            if isinstance(obj, dict):
                                candidates.append(obj)
                        except json.JSONDecodeError:
                            pass
                        break
        i += 1

    if not candidates:
        raise ValueError(f"No JSON object found in response: {text[:200]}")

    # Prefer the object with the most expected keys
    expected_keys = {'grade', 'summary', 'highlights', 'survived', 'kills',
                     'combatant_eliminations', 'runner_eliminations', 'shell_name',
                     'map_name', 'spawn_coordinates', 'primary_weapon'}

    best = max(candidates, key=lambda obj: len(set(obj.keys()) & expected_keys))
    return best


def _get_video_duration(video_path: str) -> float | None:
    """Get video duration in seconds using ffprobe."""
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration',
             '-of', 'csv=p=0', video_path],
            capture_output=True, text=True, timeout=10,
        )
        return float(probe.stdout.strip())
    except Exception as e:
        print(f"[video_processor] Failed to get video duration: {e}")
        return None


def _sidecar_audio_path(recording_path: str) -> str:
    return os.path.splitext(recording_path)[0] + "_audio.wav"


def _has_audio_stream(video_path: str) -> bool:
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-select_streams', 'a:0',
             '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', video_path],
            capture_output=True, text=True, timeout=10,
        )
        return probe.returncode == 0 and "audio" in probe.stdout.lower()
    except Exception:
        return False


def _mux_sidecar_audio(recording_path: str) -> bool:
    """Mux sidecar WAV into the MP4 with video stream copy.

    Runs only in the heavy processing lane. Leaves the original video untouched
    if audio is missing, already muxed, or ffmpeg fails.
    """
    audio_path = _sidecar_audio_path(recording_path)
    if not os.path.exists(recording_path) or not os.path.exists(audio_path):
        return False
    if _has_audio_stream(recording_path):
        return True

    tmp_path = recording_path.replace(".mp4", "_muxing.mp4")
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
        '-i', recording_path,
        '-i', audio_path,
        '-map', '0:v:0',
        '-map', '1:a:0',
        '-c:v', 'copy',
        '-c:a', 'aac',
        '-b:a', '192k',
        '-shortest',
        '-movflags', '+faststart',
        tmp_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[audio] Mux failed: {result.stderr[:300]}")
            return False
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0 and _has_audio_stream(tmp_path):
            os.replace(tmp_path, recording_path)
            print(f"[audio] Muxed sidecar audio into {os.path.basename(recording_path)}")
            try:
                os.remove(audio_path)
                print(f"[audio] Removed sidecar WAV: {os.path.basename(audio_path)}")
            except Exception as e:
                print(f"[audio] Sidecar cleanup failed: {e}")
            return True
    except Exception as e:
        print(f"[audio] Mux error: {e}")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    return False


# -- Frame extraction -------------------------------------------------------

def extract_key_frames(video_path: str, frames_dir: str, video_duration: float) -> str:
    """Extract key frames from start and end of video for Phase 1 analysis.

    Start window: first FRAME_DURATION_START seconds at FRAME_FPS_START -- deployment loading screen
    End window: last 30s at FRAME_FPS_END -- STATS, PROGRESS, LOADOUT tabs
    Resolution: native (never upscale)
    """
    os.makedirs(frames_dir, exist_ok=True)
    res = _frame_resolution(video_path)

    # Start frames: first 60s at 0.5fps (~30 frames, just need the loading screen)
    # -ss BEFORE -i = fast input seeking (doesn't decode everything before the seek point)
    start_cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
        '-ss', '0',
        '-i', video_path,
        '-t', str(FRAME_DURATION_START),
        '-vf', f'scale={res}:-2,fps={FRAME_FPS_START}',
        '-q:v', '3',
        os.path.join(frames_dir, 'start_%04d.jpg'),
    ]
    result = subprocess.run(start_cmd, capture_output=True, text=True, timeout=180)
    if result.returncode != 0:
        raise RuntimeError(f"Start frame extraction failed: {result.stderr[:200]}")

    # End frames: last 30s (higher fps — tabs flip fast)
    # -ss BEFORE -i for fast seeking
    end_start = max(0, video_duration - 30)
    end_cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
        '-ss', str(end_start),
        '-i', video_path,
        '-t', '30',
        '-vf', f'scale={res}:-2,fps={FRAME_FPS_END}',
        '-q:v', '3',
        os.path.join(frames_dir, 'end_%04d.jpg'),
    ]
    result = subprocess.run(end_cmd, capture_output=True, text=True, timeout=180)
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
    print(f"[processor] Sending {len(frame_paths)} frames to Sonnet API...")
    result = ai_client.run_api_prompt(
        prompt,
        images=frame_paths,
        model=ai_client.get_model_config("capture")["api"],
        max_tokens=4096,
    )
    return _extract_json(result)


def _analyze_frames_with_cli(frame_paths: list[str], prompt: str) -> dict:
    """Send frame images to Claude CLI for analysis (fallback when no API key)."""
    claude_bin = ai_client.find_cli()
    if not claude_bin:
        raise RuntimeError("Claude CLI not found")

    abs_paths = [os.path.abspath(p).replace("\\", "/") for p in frame_paths]
    image_list = "\n".join(f"- {p}" for p in abs_paths)
    full_prompt = f"""You have {len(frame_paths)} Marathon gameplay screenshot images to analyze. Use your Read tool to view each of these image files:

{image_list}

Read ALL of these images, then analyze them and follow these instructions:

{prompt}"""

    # Give CLI access to the frames directory
    frames_dir = os.path.dirname(abs_paths[0]) if abs_paths else "."
    cmd = [claude_bin, "-p", full_prompt, "--model", ai_client.get_model_config("capture")["cli"],
           "--dangerously-skip-permissions", "--add-dir", frames_dir]

    print(f"[processor] Sending {len(frame_paths)} frames to CLI...")
    output = _run_claude_cli(cmd, timeout=600, label="CLI Phase 1")
    if not output:
        raise RuntimeError("CLI returned no output for Phase 1")

    return _extract_json(output)


def _analyze_with_screenshots(deploy_jpg: str, readyup_jpg: str, frames_dir: str) -> dict:
    """New Phase 1: two focused CLI calls using screenshots + end frames.

    Call 1: deploy.jpg + readyup.jpg + readyup_loadout.jpg + shell references → map, coords, shell, loadout
    Call 2: end frames → stats, death, loot
    Merges results into one analysis dict.
    """
    from .config import _DATA_DIR
    claude_bin = ai_client.find_cli()
    if not claude_bin:
        raise RuntimeError("Claude CLI not found")

    analysis = {}
    screenshot_dir = os.path.dirname(deploy_jpg)
    model = ai_client.get_model_config("capture")["cli"]

    # =========================================================================
    # Phase 1: Three parallel calls (1A, 2A, 3A)
    # =========================================================================

    def _run_cli_call(prompt, work_dir, label, timeout=120):
        """Run a CLI call and return parsed JSON or empty dict."""
        cmd = [claude_bin, "-p", prompt, "--model", model,
               "--dangerously-skip-permissions", "--add-dir", work_dir]
        try:
            text = _run_claude_cli(cmd, timeout=timeout, label=label)
            if text:
                result = _extract_json(text)
                print(f"[processor] {label}: {result}")
                return result
        except Exception as e:
            print(f"[processor] {label} failed: {e}")
        return {}

    # --- Call 1A: Loadout & Identity ---
    imgs_1a = []
    for phase in ['readyup', 'run', 'deploying']:
        full = os.path.join(screenshot_dir, f"{phase}.jpg")
        crop = os.path.join(screenshot_dir, f"{phase}_crop.jpg")
        if os.path.exists(full):
            imgs_1a.append(os.path.abspath(full).replace("\\", "/"))
        if os.path.exists(crop):
            imgs_1a.append(os.path.abspath(crop).replace("\\", "/"))

    prompt_1a = f"""Read these Marathon (2026 extraction shooter) pre-deployment screenshots:
{chr(10).join(f'- {p}' for p in imgs_1a)}

These are from the lobby/ready-up screens BEFORE deployment. Full screenshots show the game UI, _crop.jpg versions are center-cropped for detail.

**CRITICAL:** If screenshots span multiple lobbies (player swapped), trust the NEWEST one (deploying > run > readyup).

Read and return ONLY valid JSON:
{{
  "map_name": "Perimeter" or "Outpost" or "Dire Marsh" or "Cryo Archive" or null,
  "is_ranked": true if "Ranked" text appears ABOVE the map name, false otherwise,
  "player_gamertag": "gamertag of LOCAL player (CENTER of screen, above character)" or null,
  "squad_members": ["all", "visible", "gamertags"] or null — local player is CENTER, mates LEFT/RIGHT,
  "crew_size": "Solo" or "Duo" or "Trio" or null,
  "loadout_value": integer from gear icon ABOVE the loadout grid (e.g. "1.5K" = 1500, "703" = 703) or null
}}

Return ONLY valid JSON, no explanation."""

    # --- Call 2A: Shell Identification ---
    imgs_2a = []
    char_crop = os.path.join(screenshot_dir, "character_crop.jpg")
    face_crop = os.path.join(screenshot_dir, "face_crop.jpg")
    if os.path.exists(char_crop):
        imgs_2a.append(os.path.abspath(char_crop).replace("\\", "/"))
    if os.path.exists(face_crop):
        imgs_2a.append(os.path.abspath(face_crop).replace("\\", "/"))
    # Fallback to deploying_crop if no character crops
    if not imgs_2a:
        dep_crop = os.path.join(screenshot_dir, "deploying_crop.jpg")
        if os.path.exists(dep_crop):
            imgs_2a.append(os.path.abspath(dep_crop).replace("\\", "/"))

    # Shell reference images
    shell_refs = ""
    backend_dir = os.path.dirname(os.path.dirname(__file__))
    for shell_path_base in [
        os.path.join(backend_dir, "data", "images", "Shells"),
        os.path.join(backend_dir, "frontend", "src", "assets", "shells"),
    ]:
        if os.path.isdir(shell_path_base):
            for f in sorted(os.listdir(shell_path_base)):
                if f.endswith('.png'):
                    base = f.replace('.png', '')
                    if '-profile' in base:
                        display = base.replace('-profile', '').capitalize() + ' (profile view)'
                    else:
                        display = base.capitalize() + ' (action pose)'
                    shell_refs += f"\n- {display}: {os.path.abspath(os.path.join(shell_path_base, f)).replace(chr(92), '/')}"
            break

    prompt_2a = f"""Identify the Marathon shell (character class) in these images:
{chr(10).join(f'- {p}' for p in imgs_2a)}
{f'{chr(10)}Shell reference images for comparison:{shell_refs}' if shell_refs else ''}

character_crop.jpg shows the character's full upper body. face_crop.jpg shows the small portrait thumbnail from the loadout grid.

The seven shells: Assassin, Destroyer, Recon, Rook, Thief, Triage, Vandal.
Cosmetic skins completely change armor, helmet, and colors — do NOT use those.
Match by FACIAL GEOMETRY only: face shape, eyes, nose, mouth, skin features.

Key features:
- **Assassin**: hooded, narrow face, glowing red/orange eyes, pale skin
- **Destroyer**: bulky, full helmet with visor, face often hidden, stocky
- **Recon**: full helmet with large visor/goggles, robotic, face not visible
- **Rook**: masculine, broad jaw, short dark hair or buzzcut, strong brow, clean-shaven or stubble, military bearing
- **Thief**: East Asian female, dark hair in bun/topknot, facial tattoos on cheek
- **Triage**: masculine, split-tone skin (light/dark), green eyes, headphones, cross markings
- **Vandal**: feminine, wider/rounder face, fuller lips, often horns or spiked hair, nose piercing

Return ONLY valid JSON:
{{
  "shell_name": "Assassin" or "Destroyer" or "Recon" or "Rook" or "Thief" or "Triage" or "Vandal" or null
}}"""

    # --- Call 3A: Coordinates ---
    imgs_3a = []
    for deploy_name in ['deploy_3', 'deploy_2', 'deploy_1', 'deploy']:
        crop = os.path.join(screenshot_dir, f"{deploy_name}_crop.jpg")
        if os.path.exists(crop):
            imgs_3a.append(os.path.abspath(crop).replace("\\", "/"))

    prompt_3a = f"""Read the spawn coordinates from these Marathon deployment loading screen screenshots:
{chr(10).join(f'- {p}' for p in imgs_3a)}

These show a BLUE or BLACK screen with the map name in large yellow/green text, a description line below it, and TWO DECIMAL NUMBERS stacked vertically in smaller text at the BOTTOM CENTER.

Example: the text might read:
  10.215867
  191.408676

These are precise decimal numbers with 6-9 digits. Read EVERY digit carefully. The first number is X, the second is Y.

If multiple images are provided, use the CLEAREST one where both numbers are fully visible.

Return ONLY valid JSON:
{{
  "spawn_coordinates": [first_number, second_number] or null if not readable
}}

DOUBLE-CHECK your reading before returning. If unsure about ANY digit, return null."""

    # --- Run all three in parallel ---
    from concurrent.futures import ThreadPoolExecutor, as_completed
    deploy_dir = os.path.dirname(deploy_jpg) if os.path.exists(deploy_jpg) else "."

    futures = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        if imgs_1a:
            futures['1a'] = pool.submit(_run_cli_call, prompt_1a, deploy_dir, "Call 1A (Loadout)")
        if imgs_2a:
            futures['2a'] = pool.submit(_run_cli_call, prompt_2a, deploy_dir, "Call 2A (Shell)")
        if imgs_3a:
            futures['3a'] = pool.submit(_run_cli_call, prompt_3a, deploy_dir, "Call 3A (Coords)")

        for key, future in futures.items():
            try:
                result = future.result(timeout=180)
                if result:
                    analysis.update(result)
            except Exception as e:
                print(f"[processor] Call {key} error: {e}")

    print(f"[processor] Phase 1 merged: map={analysis.get('map_name')} shell={analysis.get('shell_name')} coords={analysis.get('spawn_coordinates')}")

    # --- Call 2: End frames → stats (iterative 20-frame batches at native 4K) ---
    all_end_frames = _get_frame_paths(frames_dir)
    BATCH_SIZE = 20
    # Critical fields we need from end frames
    CRITICAL_FIELDS = ['primary_weapon', 'secondary_weapon', 'survived', 'kills',
                       'combatant_eliminations', 'runner_eliminations', 'loot_value_total']

    # Collect endgame screenshot (death screen / RUN_COMPLETE) + damage crop
    endgame_screenshots = []
    eg_path = os.path.join(os.path.dirname(deploy_jpg), "endgame.jpg")
    if os.path.exists(eg_path):
        endgame_screenshots.append(eg_path)
    eg_damage_path = os.path.join(os.path.dirname(deploy_jpg), "endgame_damage.jpg")
    if os.path.exists(eg_damage_path):
        endgame_screenshots.append(eg_damage_path)
    # Postgame stats screenshots (3-shot burst: banner → stats screen)
    for i in range(1, 4):
        stats_shot = os.path.join(os.path.dirname(deploy_jpg), f"stats_{i}.jpg")
        if os.path.exists(stats_shot):
            endgame_screenshots.append(stats_shot)

    if all_end_frames or endgame_screenshots:
        # Prepend endgame screenshots to the first batch — they show who killed the player
        all_images = endgame_screenshots + all_end_frames
        print(f"[processor] {len(endgame_screenshots)} endgame screenshots + {len(all_end_frames)} end frames")

        # Save copies of end frames to screenshots folder for debugging
        import shutil
        screenshots_dir = os.path.dirname(deploy_jpg) if os.path.exists(deploy_jpg) else None
        if screenshots_dir:
            endframes_dir = os.path.join(screenshots_dir, "endframes")
            os.makedirs(endframes_dir, exist_ok=True)
            for frame_path in all_end_frames:
                shutil.copy2(frame_path, os.path.join(endframes_dir, os.path.basename(frame_path)))
            print(f"[processor] Saved {len(all_end_frames)} end frames to {endframes_dir}")
        batches = [all_images[i:i + BATCH_SIZE] for i in range(0, len(all_images), BATCH_SIZE)]

        for batch_idx, batch in enumerate(batches):
            abs_paths = [os.path.abspath(p).replace("\\", "/") for p in batch]
            image_list2 = "\n".join(f"- {p}" for p in abs_paths)

            # Tell Claude what we're still missing if this is a retry
            missing_hint = ""
            if batch_idx > 0:
                missing = [f for f in CRITICAL_FIELDS if analysis.get(f) is None]
                if missing:
                    missing_hint = f"\n\nPREVIOUS BATCH DID NOT FIND: {', '.join(missing)}. Look carefully for the LOADOUT tab (weapons), STATS tab (kills/loot), and death screen."

            # Tell Sonnet which images are high-quality OCR captures vs video frames
            ocr_note = ""
            ocr_files = [p for p in abs_paths if any(n in p for n in ['endgame.jpg', 'endgame_damage.jpg', 'stats_1.jpg', 'stats_2.jpg', 'stats_3.jpg'])]
            if ocr_files:
                ocr_list = ", ".join(os.path.basename(p) for p in ocr_files)
                ocr_note = f"\n\nPRIORITY IMAGES: {ocr_list} are direct 4K screen captures (not video frames). These are the highest quality — read stats, kills, loot, and death info from these FIRST. The remaining images are extracted video frames (lower quality) for finding PROGRESS REPORT and LOADOUT REPORT tabs."

            prompt2 = f"""Read these {len(batch)} Marathon end-of-run screenshot images using your Read tool:
{image_list2}

These are from the END of a Marathon run — stats screens, death screen, loadout report.{missing_hint}{ocr_note}
{PHASE1_CALL2_PROMPT}"""

            frames_parent = os.path.dirname(batch[0])
            cmd2 = [claude_bin, "-p", prompt2, "--model", ai_client.get_model_config("capture")["cli"],
                    "--dangerously-skip-permissions", "--add-dir", frames_parent]

            print(f"[processor] CLI Call 2 batch {batch_idx + 1}/{len(batches)}: {len(batch)} frames...")
            try:
                text2 = _run_claude_cli(cmd2, timeout=600, label=f"CLI Call 2 batch {batch_idx + 1}")
            except Exception as e:
                print(f"[processor] CLI Call 2 batch {batch_idx + 1} failed: {e}")
                continue

            if text2:
                try:
                    stats_data = _extract_json(text2)
                    # Merge — non-null values from this batch override
                    for key, val in stats_data.items():
                        if val is not None or key not in analysis:
                            analysis[key] = val
                    print(f"[processor] Batch {batch_idx + 1}: survived={stats_data.get('survived')} "
                          f"kills={stats_data.get('kills')} weapons={stats_data.get('primary_weapon')}/{stats_data.get('secondary_weapon')} "
                          f"loadout_tab={stats_data.get('loadout_tab_found')}")
                except Exception as e:
                    print(f"[processor] Call 2 batch {batch_idx + 1} parse failed: {e}")
                    continue

            # Check if we have all critical fields — stop early if we do
            missing = [f for f in CRITICAL_FIELDS if analysis.get(f) is None]
            if not missing:
                print(f"[processor] All critical fields found after batch {batch_idx + 1}")
                break
            elif batch_idx < len(batches) - 1:
                print(f"[processor] Still missing: {missing} — sending next batch")

    if not analysis:
        raise RuntimeError("Both CLI calls returned no data")

    # Ensure required fields exist
    # Check if any deploy screenshot exists (numbered burst or legacy single)
    _any_deploy = os.path.exists(deploy_jpg) or any(
        os.path.exists(os.path.join(screenshot_dir, f"deploy_{i}.jpg")) for i in range(1, 4)
    )
    analysis.setdefault('loading_screen_found', _any_deploy)
    analysis.setdefault('stats_tab_found', analysis.get('kills') is not None)
    analysis.setdefault('loadout_tab_found', analysis.get('primary_weapon') is not None)

    return analysis


def analyze_frames_phase1(frames_dir: str) -> dict:
    """Analyze extracted frames for Phase 1 stats (no-screenshot path).

    Used when OCR screenshots aren't available, and for FPS escalation retry.
    Uses API (preferred for speed) with CLI fallback.
    """
    frame_paths = _get_frame_paths(frames_dir)
    if not frame_paths:
        raise RuntimeError("No frames found in frames directory")

    print(f"[processor] Phase 1: {len(frame_paths)} total frames extracted")

    # API can handle many images — send all
    if settings.anthropic_api_key:
        try:
            return _analyze_frames_with_api(frame_paths, PHASE1_CALL2_PROMPT)
        except Exception as e:
            print(f"[processor] Phase 1 API failed: {e}")
            claude_bin = ai_client.find_cli()
            if claude_bin:
                print("[processor] Falling back to CLI for Phase 1...")
            else:
                raise

    # CLI reads images one at a time — cap at ~40 frames for speed
    # Keep all start frames, subsample end frames
    MAX_CLI_FRAMES = 40
    if len(frame_paths) > MAX_CLI_FRAMES:
        start_frames = [p for p in frame_paths if os.path.basename(p).startswith('start_')]
        end_frames = [p for p in frame_paths if os.path.basename(p).startswith('end_')]
        # Keep all start, subsample end to fill remaining budget
        end_budget = MAX_CLI_FRAMES - len(start_frames)
        if end_budget > 0 and len(end_frames) > end_budget:
            step = len(end_frames) / end_budget
            end_frames = [end_frames[int(i * step)] for i in range(end_budget)]
        frame_paths = start_frames + end_frames
        print(f"[processor] CLI mode: subsampled to {len(frame_paths)} frames ({len(start_frames)} start + {len(end_frames)} end)")

    claude_bin = ai_client.find_cli()
    if claude_bin:
        return _analyze_frames_with_cli(frame_paths, PHASE1_CALL2_PROMPT)

    raise RuntimeError("No Claude auth available for Phase 1")


SPAWN_RETRY_CHUNK = 45        # seconds per retry chunk when searching for loading screen
STATS_RETRY_CHUNK = 30        # seconds per retry chunk when searching backwards for stats
STATS_FPS_ESCALATION = [10, 15, 20, 30]  # fps escalation when Sonnet needs more frames (30 cap)


def _merge_analysis(base: dict, retry: dict) -> None:
    """Merge retry results into base — fills gaps, never overwrites existing data."""
    for key, value in retry.items():
        if value is not None and (base.get(key) is None or base.get(key) == 0):
            base[key] = value


def _extract_end_frames(video_path: str, frames_dir: str, start_sec: float, duration: float, fps: float) -> bool:
    """Extract end frames from a specific window. Returns True on success."""
    res = _frame_resolution(video_path)
    for f in glob_mod.glob(os.path.join(frames_dir, 'end_*.jpg')):
        os.remove(f)
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
        '-ss', str(start_sec), '-t', str(duration),
        '-i', video_path,
        '-vf', f'scale={res}:-2,fps={fps}',
        '-q:v', '3',
        os.path.join(frames_dir, 'end_%04d.jpg'),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        print(f"[processor] FFmpeg end frame extraction failed: {result.stderr[:200]}")
        return False
    return True


def _maybe_expand_and_retry(
    analysis: dict, video_path: str, frames_dir: str, video_duration: float
) -> dict:
    """If key screens weren't found, expand the search and retry.

    Spawn search: iterates forward in 45s chunks from the initial window until found
    or video ends. Spawn coordinates are critical for map tracking.

    Stats search: if Sonnet needs more frames (fps too low), re-extracts at higher fps.
    Then iterates backwards in 30s chunks from the end until found or video exhausted.
    """
    loading_found = analysis.get("loading_screen_found", True)
    stats_found = analysis.get("stats_tab_found", True)
    needs_more_frames = analysis.get("stats_tab_needs_more_frames", False)

    if loading_found and stats_found:
        return analysis

    # -- Stats: adaptive fps escalation if Sonnet sees tabs but can't read them --
    if needs_more_frames and not stats_found:
        end_window_start = max(0, video_duration - 30)
        for boost_fps in STATS_FPS_ESCALATION:
            print(f"[processor] Stats tab seen but frames too fast, re-extracting at {boost_fps}fps...")
            if _extract_end_frames(video_path, frames_dir, end_window_start, 30, boost_fps):
                try:
                    retry = analyze_frames_phase1(frames_dir)
                    _merge_analysis(analysis, retry)
                    stats_found = retry.get("stats_tab_found", False)
                    needs_more_frames = retry.get("stats_tab_needs_more_frames", False)
                    if stats_found:
                        analysis["stats_tab_found"] = True
                        print(f"[processor] Stats found at {boost_fps}fps!")
                        break
                    if not needs_more_frames:
                        # Sonnet no longer asking for more frames — stop escalating
                        break
                except Exception as e:
                    print(f"[processor] {boost_fps}fps retry failed: {e}")
                    break

    # -- Stats: iterate backwards through video in chunks --
    if not stats_found:
        # Start searching backwards from -60s (we already checked last 30s)
        search_end = video_duration - 30  # already checked this window
        while not stats_found and search_end > 30:
            window_start = max(0, search_end - STATS_RETRY_CHUNK)
            window_duration = search_end - window_start
            print(f"[processor] Stats not found, searching {window_start:.0f}-{search_end:.0f}s...")

            if _extract_end_frames(video_path, frames_dir, window_start, window_duration, FRAME_FPS_END):
                try:
                    retry = analyze_frames_phase1(frames_dir)
                    stats_found = retry.get("stats_tab_found", False)

                    if stats_found:
                        _merge_analysis(analysis, retry)
                        analysis["stats_tab_found"] = True
                        analysis["loadout_tab_found"] = retry.get("loadout_tab_found", analysis.get("loadout_tab_found"))
                        print(f"[processor] Stats found at {window_start:.0f}-{search_end:.0f}s!")
                        break

                    # Check if it needs more frames in this window — escalate fps
                    if retry.get("stats_tab_needs_more_frames"):
                        for boost_fps in STATS_FPS_ESCALATION:
                            print(f"[processor] Stats seen at {window_start:.0f}-{search_end:.0f}s, trying {boost_fps}fps...")
                            if _extract_end_frames(video_path, frames_dir, window_start, window_duration, boost_fps):
                                try:
                                    boost_retry = analyze_frames_phase1(frames_dir)
                                    stats_found = boost_retry.get("stats_tab_found", False)
                                    if stats_found:
                                        _merge_analysis(analysis, boost_retry)
                                        analysis["stats_tab_found"] = True
                                        print(f"[processor] Stats found at {boost_fps}fps at {window_start:.0f}-{search_end:.0f}s!")
                                        break
                                    if not boost_retry.get("stats_tab_needs_more_frames"):
                                        break  # stop escalating
                                except Exception as e:
                                    print(f"[processor] {boost_fps}fps boost failed: {e}")
                                    break
                        if stats_found:
                            break

                    _merge_analysis(analysis, retry)
                except Exception as e:
                    print(f"[processor] Stats chunk analysis failed: {e}")
                    break

            search_end = window_start

        if not stats_found:
            print(f"[processor] Stats tab not found after searching entire video")

    # -- Spawn: iterate forward through video in chunks --
    search_offset = FRAME_DURATION_START

    while not loading_found and search_offset < video_duration:
        chunk_end = min(search_offset + SPAWN_RETRY_CHUNK, video_duration)
        chunk_duration = chunk_end - search_offset
        print(f"[processor] Loading screen not found, searching {search_offset:.0f}-{chunk_end:.0f}s...")

        for f in glob_mod.glob(os.path.join(frames_dir, 'start_*.jpg')):
            os.remove(f)
        res = _frame_resolution(video_path)
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
            '-ss', str(search_offset), '-t', str(chunk_duration),
            '-i', video_path,
            '-vf', f'scale={res}:-2,fps={FRAME_FPS_START}',
            '-q:v', '3',
            os.path.join(frames_dir, 'start_%04d.jpg'),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"[processor] FFmpeg start frame chunk failed: {result.stderr[:200]}")
            break

        try:
            print(f"[processor] Analyzing chunk {search_offset:.0f}-{chunk_end:.0f}s for spawn...")
            retry = analyze_frames_phase1(frames_dir)
            loading_found = retry.get("loading_screen_found", False)

            if loading_found:
                print(f"[processor] Loading screen found at {search_offset:.0f}-{chunk_end:.0f}s!")
                for key in ("map_name", "spawn_coordinates", "spawn_location", "loading_screen_found"):
                    if retry.get(key) is not None:
                        analysis[key] = retry[key]
                break

            _merge_analysis(analysis, retry)
        except Exception as e:
            print(f"[processor] Chunk analysis failed: {e}")
            break

        search_offset = chunk_end

    if not loading_found:
        print(f"[processor] Loading screen not found after searching entire video ({video_duration:.0f}s)")

    return analysis



# -- Phase 2 analysis (video -> narrative) ---------------------------------

def _get_phase1_context(run_id: int | None) -> str:
    """Fetch Phase 1 stats from DB and format as context for Phase 2 prompt."""
    if not run_id:
        return ""
    try:
        from .database import SessionLocal
        from .models import Run
        db = SessionLocal()
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            db.close()
            return ""

        lines = ["PHASE 1 STATS (already extracted — use these as ground truth for your analysis):"]
        lines.append(f"- Survived: {'Yes (EXFILTRATED)' if run.survived else 'No (ELIMINATED)' if run.survived is not None else 'Unknown'}")
        if run.killed_by:
            lines.append(f"- Killed by: {run.killed_by}")
        if run.damage_contributors:
            import json
            try:
                contribs = json.loads(run.damage_contributors) if isinstance(run.damage_contributors, str) else run.damage_contributors
                contrib_strs = [f"{c['name']} ({c['damage']} dmg{', finisher' if c.get('finished') else ''})" for c in contribs]
                lines.append(f"- Damage contributors: {', '.join(contrib_strs)}")
            except Exception as e:
                print(f"[video_processor] Failed to parse damage contributors JSON: {e}")
        if run.combatant_eliminations is not None:
            lines.append(f"- Combatant Eliminations (PvE kills): {run.combatant_eliminations}")
        if run.runner_eliminations is not None:
            lines.append(f"- Runner Eliminations (PvP kills): {run.runner_eliminations} — you MUST find EXACTLY {run.runner_eliminations} pvp_kill clip(s) in the video. If you cannot find them, explain what you see instead. Do NOT fabricate kills or mislabel PvE kills as PvP.")
        if run.crew_revives is not None and run.crew_revives > 0:
            lines.append(f"- Crew Revives: {run.crew_revives} — you MUST find EXACTLY {run.crew_revives} revive clip(s) in the video")
        if run.duration_seconds:
            mins, secs = divmod(run.duration_seconds, 60)
            lines.append(f"- Run Time: {mins}:{secs:02d}")
        if run.loot_value_total is not None:
            lines.append(f"- Loot Value: {int(run.loot_value_total)}")
        if run.primary_weapon:
            lines.append(f"- Primary Weapon: {run.primary_weapon}")
        if run.secondary_weapon:
            lines.append(f"- Secondary Weapon: {run.secondary_weapon}")
        if run.map_name:
            lines.append(f"- Map: {run.map_name}")

        db.close()
        return "\n".join(lines)
    except Exception as e:
        print(f"[processor-p2] Failed to fetch Phase 1 context: {e}")
        return ""


def _verify_hud_events(raw_analysis: str, video_path: str, phase1_context: str) -> str:
    """Call 1.5 — HUD crop verification for kill/death/health events.

    Crops the bottom-left HUD region (squad list, health bar, kill feed)
    from frames at COMBAT timestamps identified by Call 1. Sends these
    focused crops to haiku to read the HUD text accurately.

    Returns a text summary of verified HUD events, or empty string on failure.
    """
    import re
    from PIL import Image

    claude_bin = ai_client.find_cli()
    if not claude_bin:
        return ""

    # Parse combat timestamps from analyst output
    # Matches patterns like [0:30 - 1:05], [00:00:30 - 00:01:05], [30 - 65]
    combat_timestamps = []
    for line in raw_analysis.split("\n"):
        line_upper = line.upper()
        if any(cat in line_upper for cat in ["COMBAT", "DEATH", "EXTRACTION", "CLOSE"]):
            # Extract start timestamp
            ts_match = re.search(r'\[(\d+:?\d*:?\d*)', line)
            if ts_match:
                ts_str = ts_match.group(1)
                parts = ts_str.split(":")
                if len(parts) == 3:
                    secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                elif len(parts) == 2:
                    secs = int(parts[0]) * 60 + int(parts[1])
                else:
                    secs = int(parts[0])
                combat_timestamps.append(secs)

    if not combat_timestamps:
        print(f"[processor-p2] HUD verify: no combat timestamps found in analysis")
        return ""

    # Limit to max 20 timestamps to keep costs down
    if len(combat_timestamps) > 20:
        step = len(combat_timestamps) / 20
        combat_timestamps = [combat_timestamps[int(i * step)] for i in range(20)]

    # Extract frames at combat timestamps directly from video, then crop HUD region.
    # Uses ffmpeg to seek to each timestamp — fast since it's just single frames.
    abs_video = os.path.abspath(video_path)
    rec_name = os.path.basename(video_path).replace(".mp4", "")
    rec_dir = os.path.dirname(abs_video)
    hud_crops_dir = os.path.join(rec_dir, f"hud_crops_{rec_name.replace('run_', '')}")
    os.makedirs(hud_crops_dir, exist_ok=True)

    crop_paths = []
    for ts in combat_timestamps:
        frame_path = os.path.join(hud_crops_dir, f"full_{ts}s.jpg")
        crop_path = os.path.join(hud_crops_dir, f"hud_{ts}s.jpg")
        # Extract single frame at this timestamp
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
            '-ss', str(ts), '-i', abs_video,
            '-vframes', '1', '-q:v', '3', frame_path,
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=15)
        except Exception as e:
            print(f"[processor-p2] HUD frame extract failed at {ts}s: {e}")
            continue
        if not os.path.exists(frame_path):
            continue
        # Crop bottom-left HUD region: 0-57% width, 58-100% height
        try:
            img = Image.open(frame_path)
            w, h = img.size
            crop = img.crop((0, int(h * 0.58), int(w * 0.57), h))
            crop.save(crop_path, quality=90)
            crop_paths.append((ts, crop_path))
            os.remove(frame_path)  # Clean up full frame, keep only crop
        except Exception as e:
            print(f"[processor-p2] HUD crop failed at {ts}s: {e}")

    if not crop_paths:
        print(f"[processor-p2] HUD verify: no crops generated")
        return ""

    print(f"[processor-p2] HUD verify: {len(crop_paths)} crops from combat segments")

    # Build verification prompt with image paths
    crop_list = "\n".join([f"- {os.path.abspath(p).replace(chr(92), '/')} (timestamp: {ts}s)" for ts, p in crop_paths])

    verify_prompt = f"""Read the HUD elements from these Marathon gameplay screenshots. Each image is a crop of the bottom-left HUD showing: squad list (left), health bar (bottom), and kill feed text (center).

{phase1_context}

For EACH image, report what you see:
1. KILL FEED (center text): "RUNNER ELIM" (PvP kill), "COMBATANT ELIM" (PvE kill), "FINISHER" (you got the kill), or nothing
2. HEALTH: Is the player's health bar critical (mostly red/pink)? Normal? Full?
3. SQUAD: Any teammate showing "ELIMINATED" (dead) or "REVIVING" status?
4. TOP LINE: Any "[Name] ☠ [Name]" kill notification? If so, who killed who?

Images to read:
{crop_list}

Read each image file using the Read tool, then output a simple list:
[timestamp]s: KILL_FEED: ... | HEALTH: ... | SQUAD: ... | KILLFEED_TOP: ...

Be precise — "RUNNER ELIM" means a runner (human player with #tag) was killed. "COMBATANT ELIM" means a PvE enemy (UESC) was killed. These are DIFFERENT. Note consecutive PvE kills as a streak."""

    cmd = [claude_bin, "-p", verify_prompt, "--model", "haiku",
           "--dangerously-skip-permissions", "--add-dir", hud_crops_dir]

    try:
        result = _run_claude_cli(cmd, timeout=300, label="HUD verification")
    except Exception as e:
        print(f"[processor-p2] HUD verify failed: {e}")
        return ""

    print(f"[processor-p2] HUD verify complete — {len(result)} chars")

    # Clean up crops
    try:
        import shutil
        shutil.rmtree(hud_crops_dir, ignore_errors=True)
    except Exception:
        pass

    return result


def _phase2_format_to_json(raw_analysis: str, phase1_context: str, max_retries: int = 2,
                           hud_verification: str = "") -> dict:
    """Call 2 — cheap text-only call to convert raw narrative into JSON.

    Takes the raw timeline + events text from Call 1 and formats it into
    the required JSON schema. Uses haiku for speed/cost since no images.
    Retries are nearly free (~$0.001 per attempt).
    """
    claude_bin = ai_client.find_cli()
    if not claude_bin:
        raise RuntimeError("Claude CLI not found")

    hud_section = ""
    if hud_verification:
        hud_section = f"""
=== HUD VERIFICATION (ground truth — use this to correct the analyst's event labels) ===
{hud_verification}
=== END HUD VERIFICATION ===

IMPORTANT: The HUD verification above was read directly from game screenshots. Use it to:
- Confirm pvp_kill events: frames showing "RUNNER ELIM" or "[Name] ☠ [RunnerName#tag]" = confirmed pvp_kill
- Confirm PvE kills: "COMBATANT ELIM" = PvE, NOT pvp_kill. But 3+ rapid PvE kills = clip-worthy "combat" highlight
- Confirm close_call: frames showing critical/red health bar during combat
- Confirm revive: frames showing "REVIVING..." in squad list
- If the analyst missed a pvp_kill but HUD shows "RUNNER ELIM", ADD it as a highlight
- If the analyst labeled something as pvp_kill but HUD shows "COMBATANT ELIM", CHANGE it to "combat"
"""

    format_prompt = f"""Convert this gameplay analysis into a JSON object. Do NOT add or change any information — just reformat what's already there.

{phase1_context}

=== RAW ANALYSIS ===
{raw_analysis}
=== END RAW ANALYSIS ===
{hud_section}
Using the timeline segments, events,{' and HUD verification' if hud_section else ''} above, produce this exact JSON structure:
{{
  "grade": "S, A, B, C, D, or F",
  "summary": "Narrative story in second person (you). Scale: F/D or <3min = 1-2 sentences; C or 3-5min = 1 short paragraph; B or 5-10min = 1-2 paragraphs; A/S or 10+min = 2-4 paragraphs. Sports commentator recap style.",
  "highlights": [
    {{
      "timestamp_seconds": number,
      "duration_seconds": number,
      "type": "pvp_kill" or "combat" or "death" or "revive" or "close_call" or "extraction" or "loot" or "funny",
      "description": "What happens at this timestamp"
    }}
  ]
}}

GRADING CRITERIA — Marathon is an EXTRACTION shooter. Survival and loot matter MORE than kills.
Weight: Survival (35%) > Runner Kills (25%) > Loot (15%) > Revives (10%) > PvE Kills (5%) > Base (10%)
- S: Extracted with high loot ($3k+), runner kills, long run (10+ min). OR exceptional loot ($5k+).
- A: Extracted with good loot ($1k+), some kills. OR survived a long dangerous run (10+ min).
- B: Extracted with modest loot, or died mid-run but put up a real fight.
- C: Extracted quickly with minimal loot and no kills. OR died in an average firefight.
- D: Died relatively quickly with little to show (<3 min).
- F: Died almost immediately (<1 min), no kills, no loot.

Convert timestamps like "0:05:30" or "5:30" to seconds (e.g. 330). Output ONLY the JSON — no commentary, no markdown fences."""

    for attempt in range(max_retries + 1):
        cmd = [claude_bin, "-p", format_prompt, "--model", "haiku",
               "--dangerously-skip-permissions"]
        print(f"[processor-p2] Formatter call {attempt + 1}/{max_retries + 1}...")

        try:
            output = _run_claude_cli(cmd, timeout=120, label=f"Phase 2 formatter attempt {attempt + 1}")
        except Exception as e:
            print(f"[processor-p2] Formatter failed on attempt {attempt + 1}: {e}")
            continue

        if not output:
            print(f"[processor-p2] Formatter returned empty on attempt {attempt + 1}")
            continue

        try:
            return _extract_json(output)
        except ValueError as e:
            print(f"[processor-p2] Formatter JSON parse failed attempt {attempt + 1}: {e}")
            if attempt == max_retries:
                raise

    raise RuntimeError("Phase 2 formatter failed after all retries")


def _analyze_phase2_with_cli(video_path: str, run_id: int | None = None) -> dict:
    """Phase 2 narrative analysis via two CLI calls.

    Call 1 (Analyst): Watches video, extracts frames, produces raw timeline + events.
        - Expensive (video + images), but no JSON requirement — just write naturally.
        - This is what Claude already does well; it fails at JSON formatting, not analysis.

    Call 2 (Formatter): Takes raw text, converts to JSON schema.
        - Cheap (text only, haiku), retryable (~$0.001 per attempt).
        - If Call 1 produced good analysis, Call 2 almost never fails.
    """
    claude_bin = ai_client.find_cli()
    if not claude_bin:
        raise RuntimeError("Claude CLI not found")

    abs_path = os.path.abspath(video_path).replace("\\", "/")
    phase1_context = _get_phase1_context(run_id)

    # ── Call 1: Analyst (expensive, video + frames) ──
    analyst_prompt = f"""There is a gameplay video file at: {abs_path}

Use ffmpeg to extract frames from the video, then read them to analyze the gameplay. Steps:
1. Use ffprobe to get the video duration
2. Extract frames at 1fps using ffmpeg with burned-in timestamps. Use this exact command:
   ffmpeg -i VIDEO -vf "fps=1,drawtext=text='%{{pts\\:hms}}':x=10:y=10:fontsize=36:fontcolor=white:box=1:boxcolor=black@0.5:boxborderw=5" -q:v 3 OUTPUT_DIR/frame_%04d.jpg
   This overlays MM:SS timestamps on each frame so you can read exact times directly from the images.
3. Read the extracted frames — the timestamp is BURNED INTO each frame in the top-left corner. Use THESE visible timestamps for your highlight timestamps, not frame index math.
4. After analyzing ALL frames, output your full analysis.

You do NOT need to output JSON. Just output plain text analysis.

{phase1_context}

You are analyzing a recorded Marathon (Bungie 2026 extraction shooter) gameplay run.
The run's stats have ALREADY been extracted by Phase 1. Do NOT extract stats. This is ONLY for narrative analysis.

Complete these steps IN ORDER:

=== STEP 1: SCENE INVENTORY ===
Go through every frame and classify the video into segments:
  [TIMESTAMP_START - TIMESTAMP_END] CATEGORY — brief note
Categories: IDLE, COMBAT, MENU, DEATH, EXTRACTION, POSTGAME, LOADING

=== STEP 2: EVENT IDENTIFICATION ===
Review ONLY COMBAT, DEATH, or EXTRACTION segments. For each one identify:
- Is this a pvp_kill, death, revive, close_call, extraction, combat, loot, or funny?
- Who was involved? What happened?
- Use the BURNED-IN timestamps from the frames.

MARATHON HUD GUIDE:
- TIMER: Top-left, red pill countdown
- KILL FEED: Top-left area, "[PlayerName] eliminated [TargetName]". Runner names have #numbers.
- CROSSHAIR: White flash = hit markers. Red X = headshot.
- DEATH SCREEN: "NEURAL LINK SEVERED", killer info on right.
- EXTRACTION: "MATTER TRANSFER IN" countdown.

=== STEP 3: SUMMARY ===
Write a brief narrative summary of the run in second person ("you"). Sports commentator recap style.
Assign a grade (S/A/B/C/D/F) based on: Survival (35%), Runner Kills (25%), Loot (15%), Revives (10%), PvE (5%), Base (10%).

Output all three steps as plain text. Do NOT output JSON."""

    video_dir = os.path.dirname(abs_path)
    cmd = [claude_bin, "-p", analyst_prompt, "--model", ai_client.get_model_config("capture")["cli"],
           "--dangerously-skip-permissions", "--add-dir", video_dir]
    print(f"[processor-p2] Call 1: Analyst — watching video...")

    raw_analysis = ""
    try:
        raw_analysis = _run_claude_cli(cmd, timeout=1800, label="Phase 2 analyst")
    except RuntimeError as e:
        raise RuntimeError(str(e)) from e

    if not raw_analysis:
        raise RuntimeError("Phase 2 analyst returned no output")

    for line in raw_analysis.splitlines()[:20]:
        preview = line[:200] if len(line) > 200 else line
        print(f"[cli-p2] {preview}".encode('ascii', errors='replace').decode())

    print(f"[processor-p2] Call 1 complete — {len(raw_analysis)} chars of analysis")

    # Try extracting JSON from Call 1 output first (sometimes Claude includes it anyway)
    try:
        result = _extract_json(raw_analysis)
        print(f"[processor-p2] JSON found in analyst output — skipping formatter")
        return result
    except ValueError:
        pass

    # ── Call 1.5: HUD Verification (cheap, cropped images, haiku) ──
    hud_verification = ""
    try:
        hud_verification = _verify_hud_events(raw_analysis, video_path, phase1_context)
    except Exception as e:
        print(f"[processor-p2] HUD verification failed (non-fatal): {e}")

    # ── Call 2: Formatter (cheap, text only, haiku) ──
    print(f"[processor-p2] Call 2: Formatter — converting to JSON...")
    return _phase2_format_to_json(raw_analysis, phase1_context, hud_verification=hud_verification)


def _analyze_phase2_with_api(video_path: str, run_id: int | None = None) -> dict:
    """Send video to API for Phase 2 narrative analysis (fallback)."""
    size_mb = os.path.getsize(video_path) / (1024 * 1024)
    print(f"[processor-p2] Sending {size_mb:.1f}MB video to API for narrative...")

    phase1_context = _get_phase1_context(run_id)
    prompt_text = f"{phase1_context}\n\n{PHASE2_PROMPT}" if phase1_context else PHASE2_PROMPT

    result = ai_client.run_api_prompt(
        prompt_text,
        video_path=video_path,
        model=ai_client.get_model_config("capture")["api"],
        max_tokens=4096,
    )
    return _extract_json(result)


def analyze_video_phase2(video_path: str, run_id: int | None = None) -> dict:
    """Phase 2: analyze video for narrative content. CLI first, API fallback."""
    claude_bin = ai_client.find_cli()
    if claude_bin:
        try:
            return _analyze_phase2_with_cli(video_path, run_id=run_id)
        except Exception as e:
            print(f"[processor-p2] CLI failed: {e}")
            if settings.anthropic_api_key:
                print("[processor-p2] Falling back to API for Phase 2...")
            else:
                raise

    if settings.anthropic_api_key:
        return _analyze_phase2_with_api(video_path, run_id=run_id)

    raise RuntimeError("No Claude auth available for Phase 2")



# -- Clip cutting -----------------------------------------------------------

def _generate_sprite_sheet(video_path: str, duration: float) -> bool:
    """Generate a sprite sheet (thumbnail grid) for hover scrub preview."""
    import math
    sprite_path = video_path.replace(".mp4", "_sprite.jpg")
    meta_path = video_path.replace(".mp4", "_sprite.json")
    try:
        # Frame count: 3 frames per second of clip, minimum 30, cap at 300
        total_frames = min(300, max(30, int(duration * 3)))
        fps = total_frames / max(1, duration)
        cols = min(10, total_frames)
        rows = math.ceil(total_frames / cols)

        # Timeout scales with duration: at least 30s, up to 10min for long recordings
        timeout = max(30, min(600, int(duration * 1.2)))

        result = subprocess.run(
            ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
             '-i', video_path,
             '-vf', f'fps={fps},scale=384:-1,tile={cols}x{rows}',
             '-q:v', '5', '-frames:v', '1',
             sprite_path],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0 and os.path.exists(sprite_path) and os.path.getsize(sprite_path) > 5000:
            size_kb = os.path.getsize(sprite_path) / 1024
            print(f"[processor] Sprite sheet: {os.path.basename(sprite_path)} ({total_frames} frames, {cols}x{rows}, {size_kb:.0f}KB)")
            # Write sprite metadata sidecar so /clips endpoint doesn't need ffprobe
            try:
                with open(meta_path, "w") as mf:
                    json.dump({"cols": cols, "rows": rows, "frames": total_frames}, mf)
            except Exception:
                pass
            return True
        else:
            for failed_path in (sprite_path, meta_path):
                if os.path.exists(failed_path):
                    try:
                        os.remove(failed_path)
                    except Exception:
                        pass
            print(f"[processor] Sprite generation failed: {result.stderr[:200]}")
    except Exception as e:
        for failed_path in (sprite_path, meta_path):
            if os.path.exists(failed_path):
                try:
                    os.remove(failed_path)
                except Exception:
                    pass
        print(f"[processor] Sprite error: {e}")
    return False


def cut_clips(source_path: str, clips_dir: str, highlights: list[dict], run_timestamp: str | None = None) -> list[str]:
    """Cut highlight clips from the original recording using stream copy.

    No re-encoding — instant cuts from the H.264 source at native resolution (4K).
    Uses the run's recording timestamp in filename to link clips to runs.
    Returns list of clip file paths.
    """
    tag = run_timestamp or datetime.now().strftime('%Y%m%d_%H%M%S')

    # Each run gets its own subfolder
    run_clips_dir = os.path.join(clips_dir, f"run_{tag}")
    os.makedirs(run_clips_dir, exist_ok=True)
    clip_paths = []

    for i, h in enumerate(highlights):
        ts = h.get("timestamp_seconds", 0)
        dur = min(h.get("duration_seconds", 12), 25)  # Hard cap at 25s
        clip_type = h.get("type", "highlight")

        # Encounter clips (pvp_kill, death, close_call, combat) timestamp the encounter start
        # — no lead-up needed. Moment clips (extraction, loot, funny) get 3s lead-up.
        encounter_types = {"pvp_kill", "death", "revive", "close_call", "combat"}
        lead_up = 0 if clip_type in encounter_types else 3
        start = max(0, ts - lead_up)

        filename = f"clip_{tag}_{clip_type}_{i+1}.mp4"
        clip_path = os.path.join(run_clips_dir, filename)

        # Stream copy — no re-encoding, instant cuts at native resolution.
        # Source is already proper H.264 MP4 from Rust recorder.
        cmd = [
            'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
            '-ss', str(start),
            '-i', source_path,
            '-t', str(dur),
            '-c:v', 'copy',
            '-c:a', 'copy',
            '-movflags', '+faststart',
            clip_path,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                print(f"[processor] Clip encode failed: {result.stderr[:200]}")
                continue
            if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                size_mb = os.path.getsize(clip_path) / (1024 * 1024)
                clip_paths.append(clip_path)
                print(f"[processor] Clip saved: {filename} ({clip_type} @ {ts}s, {size_mb:.1f}MB)")

                # Generate thumbnail at the action point (3s into clip = where the tagged moment is)
                thumb_path = clip_path.replace(".mp4", "_thumb.jpg")
                try:
                    subprocess.run(
                        ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                         '-ss', str(min(4, dur - 1)), '-i', clip_path,
                         '-vframes', '1', '-vf', 'scale=384:-1',
                         '-q:v', '5', thumb_path],
                        capture_output=True, timeout=10,
                    )
                except Exception as e:
                    print(f"[video_processor] Thumbnail generation failed for clip: {e}")

                # Generate sprite sheet for hover scrub
                _generate_sprite_sheet(clip_path, dur)
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


def _build_notes(analysis: dict) -> str | None:
    """Build notes string from damage contributors. Returns None if nothing useful."""
    parts = []
    contributors = analysis.get("damage_contributors")
    if contributors and isinstance(contributors, list) and len(contributors) > 0:
        dmg_lines = []
        for c in contributors:
            tag = " (finished)" if c.get("finished") else ""
            dmg_lines.append(f"{c.get('name', '?')}: {c.get('damage', '?')} DMG{tag}")
        parts.append("Damage: " + ", ".join(dmg_lines))
    killed_by = analysis.get("killed_by")
    killed_by_weapon = analysis.get("killed_by_weapon")
    if killed_by and killed_by_weapon:
        parts.append(f"Killed by {killed_by} with {killed_by_weapon}")
    elif killed_by:
        parts.append(f"Killed by {killed_by}")
    return " | ".join(parts) if parts else None


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
        COORD_THRESHOLD = 10.0
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
                try:
                    from .api.spawns import invalidate_heatmap_cache
                    invalidate_heatmap_cache()
                except Exception:
                    pass
                print(f"[processor] Matched spawn #{spawn_point_id} '{best_match.spawn_location}' (dist={best_dist:.1f}, avg updated)")
            else:
                # Count existing uncharted spawns to offset the staging position
                uncharted_count = db.query(SpawnPoint).filter(
                    SpawnPoint.spawn_location.like("VCTR//%")
                ).count()
                # Centered in bracket: bracket at 2%, width = count*3.5+4
                total = uncharted_count + 1
                bracket_center = 2 + (total * 3.5 + 4) / 2
                staging_x = bracket_center + (uncharted_count - (total - 1) / 2) * 3.5
                staging_y = 4.5  # vertically centered in bracket

                # Name includes truncated coordinates for quick reference
                cx_short = int(round(coord_x))
                cy_short = int(round(coord_y))
                spawn_name = f"VCTR//{cx_short}:{cy_short}"

                spawn = SpawnPoint(
                    map_name=analysis.get("map_name") or "Unknown",
                    spawn_location=spawn_name,
                    game_coord_x=coord_x,
                    game_coord_y=coord_y,
                    x=staging_x,
                    y=staging_y,
                )
                db.add(spawn)
                db.commit()
                db.refresh(spawn)
                spawn_point_id = spawn.id
                try:
                    from .api.spawns import invalidate_heatmap_cache
                    invalidate_heatmap_cache()
                except Exception:
                    pass
                print(f"[processor] New spawn #{spawn_point_id} {spawn_name} at staging ({staging_x}, {staging_y})")

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

        # Use session from analysis (injected from .session marker) or create new
        _sid = analysis.get("_session_id")
        if not _sid:
            try:
                from .main import get_or_create_session
                _sid = get_or_create_session()
            except ImportError:
                _sid = None

        run = Run(
            map_name=analysis.get("map_name"),
            date=run_date or datetime.now(timezone.utc),
            session_id=_sid,
            survived=analysis.get("survived"),
            kills=analysis.get("kills"),
            combatant_eliminations=analysis.get("combatant_eliminations"),
            runner_eliminations=analysis.get("runner_eliminations"),
            deaths=analysis.get("deaths"),
            assists=analysis.get("assists"),
            crew_revives=analysis.get("crew_revives"),
            duration_seconds=analysis.get("duration_seconds"),
            loot_value_total=analysis.get("loot_value_total"),
            primary_weapon=analysis.get("primary_weapon"),
            secondary_weapon=analysis.get("secondary_weapon"),
            killed_by=analysis.get("killed_by"),
            killed_by_damage=_get_finisher_damage(analysis),
            killed_by_weapon=analysis.get("killed_by_weapon"),
            damage_contributors=analysis.get("damage_contributors"),
            starting_loadout_value=analysis.get("starting_loadout_value") or analysis.get("loadout_value"),
            player_level=analysis.get("player_level"),
            vault_value=analysis.get("vault_value"),
            player_gamertag=analysis.get("player_gamertag"),
            squad_members=analysis.get("squad_members"),
            squad_size={"Solo": 1, "Duo": 2, "Trio": 3}.get(analysis.get("crew_size")) or analysis.get("squad_size"),
            spawn_point_id=spawn_point_id,
            runner_id=runner_id,
            grade=analysis.get("grade"),
            summary=analysis.get("summary"),
            notes=_build_notes(analysis),
            is_ranked=analysis.get("is_ranked", False),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
        db.close()
        try:
            from .api.spawns import invalidate_heatmap_cache
            invalidate_heatmap_cache()
        except Exception:
            pass
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

    Returns a result dict with status and run_id.
    on_phase: optional callback(phase_name) for UI progress tracking.
    """
    def phase(name, detail=None):
        if on_phase:
            on_phase(name, detail=detail)

    result = {
        "status": "error",
        "recording": recording_path,
        "analysis": None,
        "clips": [],
        "run_id": None,
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
        "started_at": datetime.now(timezone.utc).isoformat(),
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
    except Exception as e:
        print(f"[video_processor] Failed to detect video resolution: {e}")

    # Extract run timestamp from recording filename
    rec_basename = os.path.basename(recording_path).replace(".mp4", "").replace("run_", "")
    try:
        run_date = datetime.strptime(rec_basename, "%Y%m%d_%H%M%S")
    except ValueError:
        run_date = None

    analysis = None

    # -- Check for OCR screenshots -----------------------------------------
    rec_name = os.path.basename(recording_path).replace(".mp4", "")
    run_screenshots = os.path.join(clips_dir, rec_name, "screenshots")
    deploy_jpg = os.path.join(run_screenshots, "deploy.jpg")
    readyup_jpg = os.path.join(run_screenshots, "readyup.jpg")
    endgame_marker = recording_path + ".endgame"

    has_readyup = os.path.exists(readyup_jpg) or any(
        os.path.exists(os.path.join(run_screenshots, f"readyup_{i}.jpg")) for i in range(1, 4)
    )
    has_deploy = os.path.exists(deploy_jpg) or any(
        os.path.exists(os.path.join(run_screenshots, f"deploy_{i}.jpg")) for i in range(1, 4)
    )
    has_screenshots = has_deploy or has_readyup

    # Read run metadata (ranked flag, etc.)
    _run_metadata = {}
    _metadata_path = os.path.join(run_screenshots, "metadata.json")
    if os.path.exists(_metadata_path):
        try:
            import json as _json
            _run_metadata = _json.load(open(_metadata_path))
            print(f"[processor] Run metadata: {_run_metadata}")
        except Exception as e:
            print(f"[video_processor] Failed to load run metadata JSON: {e}")

    # Read endgame timestamp if available
    endgame_ts = None
    if os.path.exists(endgame_marker):
        try:
            endgame_ts = float(open(endgame_marker).read().strip())
            print(f"[processor] Endgame timestamp: {endgame_ts:.1f}s")
        except Exception as e:
            print(f"[video_processor] Failed to read endgame timestamp: {e}")

    # -- Try Phase 1: screenshot-based or frame extraction -----------------
    if video_duration:
        frames_dir = recording_path.replace(".mp4", "_frames")
        try:
            # Determine processor mode (alpha / hybrid / claude) before doing
            # any ffmpeg work. Alpha and hybrid P1 can read direct OCR
            # screenshots, so they should not extract video frames in the
            # menu-fast lane unless they later fall back to Claude.
            _processor_mode = "alpha"
            try:
                from .api.settings_api import get_config_value
                _processor_mode = get_config_value("processor_mode") or "alpha"
            except Exception:
                pass

            phase("extracting_frames")
            t0 = time.time()

            skip_frame_extract = _processor_mode in ("alpha", "hybrid") and has_screenshots

            if skip_frame_extract:
                os.makedirs(frames_dir, exist_ok=True)
                print("[processor] Screenshot pipeline: skipping P1 frame extraction for local mode")
                metrics["frame_extraction_seconds"] = 0.0
            elif has_screenshots:
                # NEW PIPELINE: screenshots + targeted end frame extraction
                end_start = endgame_ts if endgame_ts else max(0, video_duration - 60)
                print(f"[processor] Screenshot pipeline: deploy={'Y' if os.path.exists(deploy_jpg) else 'N'} "
                      f"readyup={'Y' if os.path.exists(readyup_jpg) else 'N'} "
                      f"endgame={'%.1fs' % endgame_ts if endgame_ts else 'N/A (using last 60s)'}")
                os.makedirs(frames_dir, exist_ok=True)
                # Extract end frames at native 4K resolution, 1fps for manageable count
                end_duration = video_duration - end_start
                if end_duration > 0:
                    end_cmd = [
                        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
                        '-ss', str(end_start),
                        '-i', recording_path,
                        '-t', str(min(end_duration, 90)),  # Cap at 90s
                        '-vf', 'fps=1',  # 1fps at native 4K — ~90 frames max
                        '-q:v', '2',
                        os.path.join(frames_dir, 'end_%04d.jpg'),
                    ]
                    subprocess.run(end_cmd, capture_output=True, text=True, timeout=180)
                metrics["frame_extraction_seconds"] = round(time.time() - t0, 1)
            else:
                # FALLBACK: full frame extraction (no screenshots available)
                print("[processor] No screenshots — using full frame extraction")
                extract_key_frames(recording_path, frames_dir, video_duration)
                metrics["frame_extraction_seconds"] = round(time.time() - t0, 1)

            phase("analyzing_stats")
            t0 = time.time()

            analysis = None

            if _processor_mode in ("alpha", "hybrid") and has_screenshots:
                _mode_label = "ALPHA" if _processor_mode == "alpha" else "HYBRID"
                print(f"[processor] {_mode_label} MODE — using local processor")
                try:
                    from pathlib import Path
                    from .alpha.hybrid_router import HybridRouter
                    _router = HybridRouter(mode=_processor_mode)
                    # process_run handles alpha-only, hybrid confidence gating,
                    # and Claude fallback for low-confidence fields internally
                    analysis = _router.process_run(
                        Path(os.path.dirname(deploy_jpg)), video_path=None
                    )
                    analysis.setdefault("loading_screen_found", has_deploy)
                    analysis.setdefault("stats_tab_found", analysis.get("stats_tab_found", False))
                    analysis.setdefault("loadout_tab_found", analysis.get("loadout_tab_found", False))
                    print(f"[processor] {_mode_label} routing: {analysis.get('_routing', 'alpha')}")
                except Exception as e:
                    print(f"[processor] Local Phase 1 failed ({e}), falling back to Claude")
                    _processor_mode = "claude"
                    analysis = None

            if _processor_mode == "claude" or analysis is None:
                if has_screenshots and not _get_frame_paths(frames_dir):
                    # Local mode failed or cloud mode was selected. Extract the
                    # end window now, instead of paying this cost for every
                    # successful Alpha P1 run.
                    end_start = endgame_ts if endgame_ts else max(0, video_duration - 60)
                    end_duration = video_duration - end_start
                    if end_duration > 0:
                        os.makedirs(frames_dir, exist_ok=True)
                        subprocess.run(
                            ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
                             '-ss', str(end_start), '-i', recording_path,
                             '-t', str(min(end_duration, 90)),
                             '-vf', 'fps=1', '-q:v', '2',
                             os.path.join(frames_dir, 'end_%04d.jpg')],
                            capture_output=True, text=True, timeout=180,
                        )
                if has_screenshots:
                    # Claude: two-call analysis with screenshots
                    analysis = _analyze_with_screenshots(
                        deploy_jpg, readyup_jpg, frames_dir
                    )
                else:
                    # Fallback: old frame-based analysis
                    analysis = analyze_frames_phase1(frames_dir)

                # Retry with expanded windows if key screens not found (fallback only)
                if not has_screenshots:
                    analysis = _maybe_expand_and_retry(
                        analysis, recording_path, frames_dir, video_duration
                    )

            metrics["phase1_analysis_seconds"] = round(time.time() - t0, 1)

            print(f"[processor] Phase 1 result: {analysis.get('map_name')} | "
                  f"{'SURVIVED' if analysis.get('survived') else 'DIED'} | "
                  f"{analysis.get('kills', 0)} kills | "
                  f"loading={'Y' if analysis.get('loading_screen_found') else 'N'} "
                  f"stats={'Y' if analysis.get('stats_tab_found') else 'N'}")

        except Exception as e:
            import traceback
            error_detail = str(e)[:200]
            print(f"[processor] Phase 1 failed: {error_detail}")
            print(f"[processor] Phase 1 traceback:\n{traceback.format_exc()}")

            # Log to file for debugging
            try:
                log_path = os.path.join(os.path.dirname(recording_path), "phase1_errors.log")
                with open(log_path, "a") as f:
                    f.write(f"\n--- {datetime.now().isoformat()} | {os.path.basename(recording_path)} ---\n")
                    f.write(traceback.format_exc())
                    f.write("\n")
            except Exception as e:
                print(f"[video_processor] Failed to write Phase 1 error log: {e}")

            phase("phase1_failed", detail=error_detail)
            metrics["status"] = "error"
            metrics["error"] = error_detail
            _save_metrics(metrics)
            return result
        finally:
            if os.path.isdir(frames_dir):
                shutil.rmtree(frames_dir, ignore_errors=True)
    else:
        print("[processor] Could not determine video duration")
        phase("phase1_failed", detail="Could not read video duration")
        metrics["status"] = "error"
        metrics["error"] = "Could not read video duration"
        _save_metrics(metrics)
        return result

    if not analysis:
        return result

    result["analysis"] = analysis

    # Merge run metadata (ranked flag, etc.) into analysis
    if _run_metadata:
        if _run_metadata.get("is_ranked") and not analysis.get("is_ranked"):
            analysis["is_ranked"] = True

    # Inject session ID from .session marker into analysis for save_run_to_db
    _session_marker = recording_path + ".session"
    if os.path.exists(_session_marker):
        try:
            analysis["_session_id"] = int(open(_session_marker).read().strip())
        except Exception as e:
            print(f"[video_processor] Failed to read session marker: {e}")

    # -- Save to database --------------------------------------------------
    phase("saving")
    run_id = save_run_to_db(analysis, run_date=run_date)
    result["run_id"] = run_id

    # Metrics
    metrics["total_seconds"] = round(time.time() - pipeline_start, 1)
    metrics["status"] = "phase1_done"
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
    """Phase 2 pipeline: narrative analysis -> update run -> cut clips.

    Sends full video to Claude for narrative analysis, grade, and highlight
    timestamps. Clips are cut using stream copy (no re-encoding).
    Runs after Phase 1 completes. If it fails, the run keeps Phase 1 data.
    """
    def phase(name, detail=None):
        if on_phase:
            on_phase(name, detail=detail)

    result = {
        "status": "error",
        "clips": [],
    }

    rec_basename = os.path.basename(recording_path).replace(".mp4", "").replace("run_", "")
    pipeline_start = time.time()

    # Analyze video for narrative
    phase("analyzing_gameplay")
    t0 = time.time()
    phase2_data = None

    # Determine processor mode
    _processor_mode = "alpha"
    try:
        from .api.settings_api import get_config_value
        _processor_mode = get_config_value("processor_mode") or "alpha"
    except Exception:
        pass

    if _processor_mode in ("alpha", "hybrid"):
        _mode_label = "ALPHA" if _processor_mode == "alpha" else "HYBRID"
        print(f"[processor-p2] {_mode_label} MODE — using local highlight detection")
        try:
            from .alpha.processor import AlphaProcessor
            _alpha = AlphaProcessor()
            # Load Phase 1 stats from DB for grading
            p1_stats = {}
            try:
                from .database import SessionLocal
                from .models import Run
                db = SessionLocal()
                run_row = db.query(Run).filter(Run.id == run_id).first()
                if run_row:
                    p1_stats = {
                        "runner_eliminations": run_row.runner_eliminations,
                        "combatant_eliminations": run_row.combatant_eliminations,
                        "survived": run_row.survived,
                        "kills": run_row.kills,
                        "crew_revives": run_row.crew_revives,
                        "duration_seconds": run_row.duration_seconds,
                        "loot_value_total": run_row.loot_value_total,
                        "map_name": run_row.map_name,
                    }
                db.close()
            except Exception as e:
                print(f"[processor-p2] Failed to load Phase 1 stats: {e}")
            sidecar_audio = _sidecar_audio_path(recording_path)
            phase2_data = _alpha.process_phase2(
                p1_stats,
                video_path=recording_path,
                audio_path=sidecar_audio if os.path.exists(sidecar_audio) else None,
            )
            print(f"[processor-p2] {_mode_label} Phase 2 took {time.time() - t0:.0f}s, "
                  f"grade={phase2_data.get('grade')}, "
                  f"{len(phase2_data.get('highlights', []))} highlights")
        except Exception as e:
            print(f"[processor-p2] Local Phase 2 failed ({e}), falling back to Claude")
            _processor_mode = "claude"
            phase2_data = None

    if _processor_mode == "claude" or phase2_data is None:
        try:
            phase2_data = analyze_video_phase2(recording_path, run_id=run_id)
            print(f"[processor-p2] Phase 2 analysis took {time.time() - t0:.0f}s, "
                  f"grade={phase2_data.get('grade')}")
        except Exception as e:
            import traceback
            print(f"[processor-p2] Phase 2 analysis failed: {e}")
            print(f"[processor-p2] Traceback:\n{traceback.format_exc()}")
            try:
                log_path = os.path.join(os.path.dirname(recording_path), "phase2_errors.log")
                with open(log_path, "a") as f:
                    from datetime import datetime as _dt
                    f.write(f"\n--- {_dt.now().isoformat()} | run #{run_id} | {os.path.basename(recording_path)} ---\n")
                    f.write(traceback.format_exc())
                    f.write("\n")
            except Exception:
                pass
            result["status"] = "phase2_failed"
            return result

    # Update run with narrative data (never overwrites stats)
    update_run_phase2(run_id, phase2_data)

    # Step 3.5: mux sidecar audio into the full recording if available. This is
    # deliberately here in Phase 2 so ffmpeg work stays out of match-time/P1.
    _mux_sidecar_audio(recording_path)

    # Step 4: Cut clips from original 4K
    phase("cutting_clips")
    highlights = phase2_data.get("highlights", [])
    if highlights:
        result["clips"] = cut_clips(
            recording_path, clips_dir, highlights, run_timestamp=rec_basename
        )
        print(f"[processor-p2] Created {len(result['clips'])} clips")
        # Invalidate clips cache so new clips show up immediately
        try:
            from .api.capture_api import invalidate_clips_cache
            invalidate_clips_cache()
        except Exception:
            pass

    # Re-mark as unviewed AFTER everything is done (grade, summary, clips all ready)
    try:
        from .database import SessionLocal
        from .models import Run
        db = SessionLocal()
        run = db.query(Run).filter(Run.id == run_id).first()
        if run:
            run.viewed = False
            db.commit()
        db.close()
    except Exception as e:
        print(f"[video_processor] Failed to re-mark run #{run_id} as unviewed: {e}")

    result["status"] = "success"
    print(f"[processor-p2] Phase 2 complete in {time.time() - pipeline_start:.0f}s")
    return result

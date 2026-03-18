"""
Video Processor -- Sends recorded run videos to Claude Sonnet for analysis.

Pipeline:
  1. Compress video (720p, low bitrate) for API upload
  2. Send whole video to Sonnet -> get run data + highlight timestamps
  3. Cut highlight clips from ORIGINAL full-quality video
  4. Insert run into database
  5. Delete full recording, keep clips
"""

import base64
import json
import os
import shutil
import subprocess
import time
from datetime import datetime

from .config import settings


# -- Sonnet prompt for video analysis ------------------------------------

VIDEO_PROMPT = """You are analyzing a recorded gameplay video from Marathon (Bungie 2026 extraction shooter).

Analyze the ENTIRE video carefully. The video covers one complete run from lobby to end.

You will see some or all of these phases:
1. **LOBBY/READY UP** - Character in lobby, green "READY UP" button visible. You can see the SHELL (character class) name and thumbnail image, the equipped loadout/weapons, and a STARTING INVENTORY VALUE (currency amount, e.g. "$4,500" or "B28/148"). Capture these.
2. **CONTRACT BRIEFING** - Appears after matchmaking, before deploying. Shows the active contract name (e.g. "BUILD MEETS CRAFT II"), contract type (e.g. "MULTI-ZONE"), objectives with progress bars, player username and season level at top. Also shows warning text about gear risk.
3. **DEPLOYING** - Countdown screen, shows map name and spawn coordinates
4. **LOADING SCREEN** - Blue screen with map name in large green/yellow text, description below, and TWO DECIMAL COORDINATE NUMBERS at the bottom center (e.g. "10.564070" and "195.869476"). These are spawn coordinates — VERY IMPORTANT to capture exactly.
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
  "spawn_coordinates": "two decimal numbers from the blue loading screen, e.g. [10.564070, 195.869476]" or null,
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


def _find_claude_cli():
    """Find the claude CLI binary."""
    candidates = [
        shutil.which("claude"),
        os.path.expanduser("~/.local/bin/claude"),
        os.path.expanduser("~/.local/bin/claude.exe"),
        r"C:\Users\User\.local\bin\claude.exe",
    ]
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    return None


def _extract_json(text: str) -> dict:
    """Extract JSON from Sonnet response, handling extra text robustly.

    Sonnet sometimes adds explanation text before/after the JSON.
    Strategy: find the first '{', then try parsing progressively larger
    substrings until we get valid JSON. This handles nested braces correctly.
    """
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

    # Try parsing from start, progressively finding each '}' from the end
    # This ensures we get the complete top-level JSON object
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


# -- Video compression ---------------------------------------------------

def compress_for_analysis(input_path: str, output_path: str) -> bool:
    """Compress video to fit within 2000px for Sonnet CLI analysis.

    The API enforces a 2000px dimension limit when 21+ images are in one
    request. The CLI extracts frames autonomously, so we can't control
    the count — keep the longest edge at 2000px to be safe.
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
    """Compress video to 720p low-bitrate for API upload.

    Target: under max_size_mb, 720p, 2fps is enough for analysis.
    """
    cmd = [
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'warning',
        '-i', input_path,
        '-vf', 'scale=1280:720',
        '-r', '2',
        '-c:v', 'libx264', '-crf', '32', '-preset', 'fast',
        '-an',  # No audio needed for analysis
        output_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"[processor] Compression failed: {result.stderr}")
            return False

        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"[processor] Compressed: {size_mb:.1f}MB")

        # If still too big, try harder compression
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
            subprocess.run(cmd2, capture_output=True, text=True, timeout=120)
            size_mb = os.path.getsize(output_path) / (1024 * 1024)
            print(f"[processor] Re-compressed: {size_mb:.1f}MB")

        return True
    except Exception as e:
        print(f"[processor] Compression error: {e}")
        return False


# -- Send to Sonnet -------------------------------------------------------

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
    """Send video to Claude Sonnet via CLI (uses OAuth/Max subscription).

    The CLI handles video analysis by using ffmpeg/ffprobe to extract
    frames and metadata, then reads and analyzes them. We give it full
    tool access (Bash + Read) so it can work autonomously.
    """
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

    # Stream output in real-time so we can see what the CLI is doing.
    # stdin=DEVNULL is critical — without it the CLI inherits the piped stdin
    # from Electron's backend-manager and hangs waiting for input.
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Read stdout line by line for real-time logging
    output_lines = []
    try:
        for line in iter(proc.stdout.readline, b''):
            decoded = line.decode("utf-8", errors="replace").rstrip()
            if decoded:
                output_lines.append(decoded)
                # Log progress (truncate long lines)
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
    """Analyze video using CLI first, fallback to API."""
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


# -- Clip cutting ---------------------------------------------------------

def cut_clips(source_path: str, clips_dir: str, highlights: list[dict], run_timestamp: str | None = None) -> list[str]:
    """Cut highlight clips from the original full-quality video.

    Uses stream copy (no re-encoding) for instant cuts.
    Uses the run's recording timestamp in filename to link clips to runs.
    Returns list of clip file paths.
    """
    os.makedirs(clips_dir, exist_ok=True)
    clip_paths = []

    # Use the run's recording timestamp (from filename) as the clip identifier
    # e.g. run_20260317_120215.mp4 -> 20260317_120215
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
            subprocess.run(cmd, capture_output=True, text=True, timeout=30)
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


# -- Database insert ------------------------------------------------------

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
    blue loading screen, and matches the shell (runner) by name.
    """
    from .database import SessionLocal
    from .models import Run, SpawnPoint, Runner

    try:
        db = SessionLocal()

        # Create or match spawn point from loading screen coordinates.
        # Uses proximity matching (within 5 game units) since the exact
        # coordinates vary slightly each time you spawn at the same point.
        COORD_THRESHOLD = 5.0
        spawn_point_id = None
        coords = analysis.get("spawn_coordinates")
        if coords and isinstance(coords, list) and len(coords) == 2:
            coord_x, coord_y = float(coords[0]), float(coords[1])

            # Find nearest existing spawn by Euclidean distance
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
                # Running average: move stored coords toward this reading
                n = len(best_match.runs) + 1  # approximate sample count
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
            # Case-insensitive match
            runner = db.query(Runner).filter(
                Runner.name.ilike(shell_name)
            ).first()
            if runner:
                runner_id = runner.id
                print(f"[processor] Matched shell: {runner.name} (#{runner.id})")
            else:
                # Create new runner entry
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
        return None


# -- Metrics logging (backend only) ----------------------------------------

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
              f"analysis={metrics.get('analysis_seconds', '?')}s | "
              f"total={metrics.get('total_seconds', '?')}s | "
              f"{metrics.get('status')}")
    except Exception as e:
        print(f"[metrics] Failed to save: {e}")


# -- Main pipeline --------------------------------------------------------

def process_recording(recording_path: str, clips_dir: str, on_phase=None) -> dict:
    """Full processing pipeline for a completed recording.

    Returns a result dict with status, run data, and clip paths.
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

    # Get video duration + resolution
    try:
        probe = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries',
             'format=duration:stream=width,height',
             '-of', 'csv=p=0', recording_path],
            capture_output=True, text=True, timeout=10,
        )
        parts = probe.stdout.strip().split('\n')
        if len(parts) >= 2:
            wh = parts[0].split(',')
            metrics["resolution"] = f"{wh[0]}x{wh[1]}"
            metrics["video_duration_seconds"] = round(float(parts[1]), 1)
    except Exception:
        pass

    # Step 1: Compress to 2K for Sonnet analysis
    # 4K files are too large for Sonnet to process in time (5.7GB → timeout).
    # 2K (2560x1440) gives excellent OCR accuracy at ~350MB, ~14 min analysis.
    # Original 4K is kept for clip cutting.
    compressed_path = recording_path.replace(".mp4", "_2k.mp4")
    analysis_path = recording_path
    t0 = time.time()

    # Skip compression if 2K already exists (from a previous interrupted run)
    if os.path.exists(compressed_path) and os.path.getsize(compressed_path) > 1024 * 1024:
        analysis_path = compressed_path
        comp_size = os.path.getsize(compressed_path) / (1024 * 1024)
        metrics["compress_seconds"] = 0
        metrics["compressed_size_mb"] = round(comp_size, 1)
        print(f"[processor] 2K already exists: {comp_size:.0f}MB (skipping compression)")
    else:
        phase("compressing")
        if compress_for_analysis(recording_path, compressed_path):
            analysis_path = compressed_path
            comp_size = os.path.getsize(compressed_path) / (1024 * 1024)
            metrics["compress_seconds"] = round(time.time() - t0, 1)
            metrics["compressed_size_mb"] = round(comp_size, 1)
            print(f"[processor] Compressed to 2K: {comp_size:.0f}MB in {metrics['compress_seconds']}s")
        else:
            print("[processor] 2K compression failed, using original...")
            compressed_path = None
            metrics["compress_seconds"] = round(time.time() - t0, 1)

    # Step 2: Send to Sonnet
    phase("analyzing")
    t0 = time.time()

    try:
        analysis = analyze_video(analysis_path)
        result["analysis"] = analysis
        metrics["analysis_seconds"] = round(time.time() - t0, 1)
        print(f"[processor] Analysis took {metrics['analysis_seconds']}s")
        print(f"[processor] Result: {analysis.get('map_name')} | "
              f"{'SURVIVED' if analysis.get('survived') else 'DIED'} | "
              f"{analysis.get('kills', 0)} kills")
    except Exception as e:
        print(f"[processor] Analysis failed: {e}")
        metrics["analysis_seconds"] = round(time.time() - t0, 1)
        metrics["status"] = "error"
        metrics["error"] = str(e)[:200]
        _save_metrics(metrics)
        if compressed_path and os.path.exists(compressed_path):
            os.remove(compressed_path)
        return result

    # Clean up compressed file if we made one
    if compressed_path and os.path.exists(compressed_path):
        os.remove(compressed_path)

    # Extract run timestamp from recording filename: run_20260317_120215.mp4 -> 20260317_120215
    rec_basename = os.path.basename(recording_path).replace(".mp4", "").replace("run_", "")
    try:
        run_date = datetime.strptime(rec_basename, "%Y%m%d_%H%M%S")
    except ValueError:
        run_date = None

    # Step 3: Save to database (before clips, so we have run_id)
    phase("saving")
    run_id = save_run_to_db(analysis, run_date=run_date)
    result["run_id"] = run_id

    # Step 4: Cut highlight clips from ORIGINAL 4K video
    phase("cutting_clips")
    highlights = analysis.get("highlights", [])
    if highlights:
        result["clips"] = cut_clips(recording_path, clips_dir, highlights, run_timestamp=rec_basename)
        print(f"[processor] Created {len(result['clips'])} clips")

    # Step 5: Delete full recording (keep clips)
    # Keep the original 4K recording — user decides to keep or delete
    # via the processing queue UI (video retention feature)
    print(f"[processor] Recording kept: {recording_path}")

    # Save pipeline metrics
    metrics["total_seconds"] = round(time.time() - pipeline_start, 1)
    metrics["status"] = "success"
    metrics["run_id"] = run_id
    metrics["clips_count"] = len(result.get("clips", []))
    metrics["map"] = analysis.get("map_name")
    metrics["grade"] = analysis.get("grade")
    _save_metrics(metrics)

    result["status"] = "success"
    return result

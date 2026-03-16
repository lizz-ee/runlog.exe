import asyncio
import base64
import json
import os
import shutil
import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException
from PIL import Image
import io

from ..config import settings
from ..schemas import ParsedScreenshot

router = APIRouter()

PARSE_PROMPT = """Analyze these Marathon (Bungie 2026 extraction shooter) end-of-match screenshots.

The Marathon post-match screen has 3 tabs — you may see one or more of them:

**STATS tab**: Shows the player's character model and key run stats:
- "EXFILTRATED" (green) = survived, or a death/failure indicator
- "Combatant Eliminations" = PvE kills (AI enemies)
- "Runner Eliminations" = PvP kills (other players)
- "Crew Revives" = teammates revived
- "Inventory Value" = total loot value for the run
- "Run Time" = match duration (MM:SS format)
- Player level shown in top-left (green circle with number)
- Top bar shows: level, currency amount (e.g. B28/148), and bullet balance (e.g. $59,385)

**LOADOUT tab**: Shows weapons and gear extracted:
- Primary weapon (slot 1) and Secondary weapon (slot 2) with names and rarity colors
- Backpack grid showing all carried items
- Equipment, Shield, Cores, Implants slots
- "+N Items Collected", "Data Card(s) Uploaded", "+N Items Auto-Vaulted"
- "Report Summary: Exit Successful" or failure
- "Bullet Balance" at bottom with total currency

**PROGRESS tab**: Shows season/faction progression (less important for run tracking):
- Season Level and XP
- Faction ranks (CyAc, NLI, Traxus, Arachne, Sekiguchi Genetics, etc.)

Extract all visible match data and return ONLY valid JSON with these fields:
{
  "survived": true/false (true if "EXFILTRATED" or "Exit Successful" is shown),
  "kills": number (total of Combatant Eliminations + Runner Eliminations, or 0),
  "combatant_eliminations": number (PvE kills, 0 if not visible),
  "runner_eliminations": number (PvP kills, 0 if not visible),
  "deaths": number (usually 0 if extracted, 1 if died — infer from outcome),
  "assists": number (crew revives count, 0 if not visible),
  "map_name": "string or null",
  "duration_seconds": number or null (convert MM:SS Run Time to total seconds),
  "loot_extracted": [{"name": "item name", "value": number}] or null (list visible items from backpack/loadout),
  "loot_value_total": number (the "Inventory Value" number, 0 if not visible),
  "runner_name": "string or null" (character class if identifiable),
  "primary_weapon": "string or null" (weapon name from slot 1),
  "secondary_weapon": "string or null" (weapon name from slot 2),
  "heavy_weapon": "string or null" (if a 3rd weapon slot is visible),
  "items_collected": number or null (the "+N Items Collected" count),
  "items_auto_vaulted": number or null (the "+N Items Auto-Vaulted" count),
  "bullet_balance": number or null (the $ currency shown),
  "raw_text": "brief summary of all key text visible in the screenshots",
  "confidence": "high/medium/low"
}

If a field is not visible in any screenshot, use null or 0 as appropriate.
Return ONLY the JSON object, no markdown, no explanation."""


# ── Helpers ──────────────────────────────────────────────────────────

def _find_claude_cli():
    """Find the claude CLI binary."""
    # Check common locations
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


async def _save_upload(file: UploadFile) -> str:
    """Save an uploaded file and return the path."""
    contents = await file.read()

    try:
        img = Image.open(io.BytesIO(contents))
        img.verify()
    except Exception:
        raise HTTPException(status_code=400, detail=f"Invalid image file: {file.filename}")

    upload_dir = os.path.abspath(settings.media_upload_dir)
    os.makedirs(upload_dir, exist_ok=True)
    ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else "png"
    filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(upload_dir, filename)

    with open(filepath, "wb") as f:
        f.write(contents)

    return filepath


async def _parse_with_cli(image_paths: list[str], prompt: str) -> str:
    """Call claude CLI with images and a prompt. Uses the user's OAuth session."""
    claude_bin = _find_claude_cli()
    if not claude_bin:
        raise HTTPException(status_code=500, detail="Claude CLI not found. Install Claude Code or set ANTHROPIC_API_KEY.")

    # Convert to absolute paths
    abs_paths = [os.path.abspath(p) for p in image_paths]

    # Tell Claude to read the image files, then parse them
    image_instructions = "\n".join(
        f"- Read the image file at: {p}" for p in abs_paths
    )
    full_prompt = f"""First, read these image files:
{image_instructions}

Then, analyze the images and follow these instructions:

{prompt}"""

    cmd = [claude_bin, "-p", full_prompt, "--allowedTools", "Read"]

    # Use subprocess.run in a thread to avoid Windows asyncio subprocess issues
    import subprocess
    import functools

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        functools.partial(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            cwd=os.path.dirname(abs_paths[0]) if abs_paths else None,
            timeout=300,
        ),
    )

    output = result.stdout.strip() if result.stdout else ""
    err_output = result.stderr.strip() if result.stderr else ""

    # Claude CLI may return non-zero but still produce valid output
    if output:
        return output

    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Claude CLI error (exit {result.returncode}): {err_output or 'no output'}")

    return output


async def _parse_with_api(image_paths: list[str], prompt: str) -> str:
    """Call Claude API directly with images and a prompt. Requires ANTHROPIC_API_KEY."""
    import anthropic
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    image_blocks = []
    for path in image_paths:
        with open(path, "rb") as f:
            data = f.read()
        ext = path.split(".")[-1].lower()
        media_type = f"image/{ext}" if ext in ("png", "jpeg", "jpg", "gif", "webp") else "image/png"
        if ext == "jpg":
            media_type = "image/jpeg"
        b64 = base64.b64encode(data).decode("utf-8")
        image_blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64},
        })

    content = image_blocks + [{"type": "text", "text": prompt}]

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )
    return message.content[0].text.strip()


async def _call_claude(image_paths: list[str], prompt: str) -> str:
    """Call Claude using CLI (OAuth) first, falling back to API key if CLI not available."""
    claude_bin = _find_claude_cli()

    if claude_bin:
        # Prefer CLI — uses the user's existing OAuth login, no API key needed
        return await _parse_with_cli(image_paths, prompt)
    elif settings.anthropic_api_key:
        # Fallback to API key
        return await _parse_with_api(image_paths, prompt)
    else:
        raise HTTPException(
            status_code=500,
            detail="No authentication available. Either install Claude Code (for OAuth) or set ANTHROPIC_API_KEY in .env"
        )


def _extract_json(text: str) -> dict:
    """Extract JSON from Claude's response, stripping markdown fences if present."""
    text = text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = text.strip()

    # Try to find JSON object in the text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        text = text[start:end]

    return json.loads(text)


# ── Endpoints ────────────────────────────────────────────────────────

@router.post("/parse", response_model=ParsedScreenshot)
async def parse_screenshot(files: List[UploadFile] = File(...)):
    """Upload one or more Marathon screenshots and parse match data using Claude Vision.

    Uses Claude CLI (OAuth) if available, otherwise falls back to API key.
    For best results, upload both the STATS tab and LOADOUT tab screenshots.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    # Save all uploaded images
    saved_paths = []
    for file in files:
        filepath = await _save_upload(file)
        saved_paths.append(filepath)

    # Call Claude (CLI or API)
    try:
        response_text = await _call_claude(saved_paths, PARSE_PROMPT)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(f"Claude error: {tb}")
        raise HTTPException(status_code=500, detail=f"Claude error: {type(e).__name__}: {str(e) or tb[-300:]}")

    # Parse JSON response
    try:
        parsed = _extract_json(response_text)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail=f"Could not parse Claude response as JSON. Raw response: {response_text[:500]}"
        )

    return ParsedScreenshot(**parsed)


@router.get("/last-path")
async def get_last_screenshot_path():
    """Get the path of the most recently saved screenshot."""
    upload_dir = settings.media_upload_dir
    if not os.path.exists(upload_dir):
        return {"path": None}

    files = sorted(
        [f for f in os.listdir(upload_dir) if not f.startswith(".")],
        key=lambda f: os.path.getmtime(os.path.join(upload_dir, f)),
        reverse=True,
    )
    if files:
        return {"path": os.path.join(upload_dir, files[0])}
    return {"path": None}

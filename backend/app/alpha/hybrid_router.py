"""
Hybrid Router — Confidence-gate routing between Alpha (local) and Claude (API).

Runs the alpha pipeline first (free, fast, local). If any critical fields
fall below the confidence threshold, sends ONLY the relevant screenshot crops
to Claude for targeted extraction. Merges Claude's answers back in.

Modes:
  - "local"  : Alpha only, never calls Claude (default, zero cost)
  - "hybrid" : Alpha first, Claude fallback for low-confidence fields
  - "cloud"  : Claude only (original behavior, most expensive)

Usage:
    from backend.app.alpha.hybrid_router import HybridRouter
    router = HybridRouter(mode="hybrid")
    result = router.process_run(screenshots_dir, video_path=None)
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone

from PIL import Image

from backend.app.alpha.processor import AlphaProcessor, DEFAULT_CONFIDENCE_THRESHOLD

logger = logging.getLogger(__name__)

# Fields that must be correct for the run record to be useful.
CRITICAL_FIELDS = {
    "survived", "kills", "combatant_eliminations", "runner_eliminations",
    "crew_revives", "loot_value_total", "duration_seconds",
}

# Fields hybrid mode is allowed to repair. This is deliberately broader than
# CRITICAL_FIELDS so map/loadout/shell/spawn issues do not linger in hybrid.
FALLBACK_FIELDS = CRITICAL_FIELDS | {
    "map_name", "shell_name", "spawn_coordinates",
    "primary_weapon", "secondary_weapon", "player_level", "vault_value",
    "killed_by", "killed_by_weapon", "killed_by_damage", "damage_contributors",
}

# Fields that can be answered from specific screenshot crops
FIELD_TO_SCREENSHOT = {
    "survived": ["stats_", "endgame"],
    "kills": ["stats_"],
    "combatant_eliminations": ["stats_"],
    "runner_eliminations": ["stats_"],
    "crew_revives": ["stats_"],
    "loot_value_total": ["stats_"],
    "duration_seconds": ["stats_"],
    "map_name": ["deploy", "readyup"],
    "shell_name": ["readyup", "_char"],
    "spawn_coordinates": ["deploy"],
    "primary_weapon": ["loadout_", "stats_"],
    "secondary_weapon": ["loadout_", "stats_"],
    "player_level": ["stats_", "loadout_", "progress_"],
    "vault_value": ["stats_", "loadout_", "progress_"],
    "killed_by": ["endgame", "endgame_damage"],
    "killed_by_weapon": ["endgame", "endgame_damage"],
    "killed_by_damage": ["endgame", "endgame_damage"],
    "damage_contributors": ["endgame", "endgame_damage"],
}


def _build_targeted_prompt(low_fields: list[str], alpha_values: dict,
                           confidence: dict) -> str:
    """Build a minimal Claude prompt that only asks for the fields we need."""
    field_descriptions = {
        "survived": '"survived": true/false (true if "EXFILTRATED" shown, false if eliminated)',
        "kills": '"kills": number (total Combatant + Runner Eliminations)',
        "combatant_eliminations": '"combatant_eliminations": number (PvE kills)',
        "runner_eliminations": '"runner_eliminations": number (PvP kills)',
        "crew_revives": '"crew_revives": number (teammates revived)',
        "loot_value_total": '"loot_value_total": number (Inventory Value)',
        "duration_seconds": '"duration_seconds": number (Run Time MM:SS converted to seconds)',
        "map_name": '"map_name": "string" (Perimeter, Outpost, Dire Marsh, or Cryo Archive)',
        "shell_name": '"shell_name": "string" (assassin, destroyer, recon, rook, thief, triage, or vandal)',
        "spawn_coordinates": '"spawn_coordinates": [x, y] (two decimal numbers from deploy screen)',
        "primary_weapon": '"primary_weapon": "string" (weapon name from slot 1)',
        "secondary_weapon": '"secondary_weapon": "string" (weapon name from slot 2)',
        "player_level": '"player_level": number (top-left green level pill)',
        "vault_value": '"vault_value": number (top bar vault/gear value, not stale animation)',
        "killed_by": '"killed_by": "string" (exact finisher gamertag#number from death widget)',
        "killed_by_weapon": '"killed_by_weapon": "string" (weapon/source from death widget)',
        "killed_by_damage": '"killed_by_damage": number (finisher damage)',
        "damage_contributors": '"damage_contributors": [{"name": "string", "damage": number, "finished": true/false}]',
    }

    fields_json = ",\n  ".join(
        field_descriptions.get(f, f'"{f}": value')
        for f in low_fields
    )

    alpha_context = {
        field: {
            "alpha_value": alpha_values.get(field),
            "alpha_confidence": confidence.get(field),
        }
        for field in low_fields
    }

    return f"""These are Marathon (Bungie 2026) end-of-match screenshots.
I need ONLY these specific low-confidence values. Ignore everything else.
Local alpha already tried these fields and produced this context:
{json.dumps(alpha_context, indent=2)}

{{
  {fields_json}
}}

Return ONLY valid JSON with these fields. Use null if not visible. Do not guess."""


def _find_relevant_screenshots(ss_dir: Path, low_fields: list[str]) -> list[str]:
    """Find the minimum set of screenshots needed for the low-confidence fields."""
    needed_prefixes = set()
    for field in low_fields:
        prefixes = FIELD_TO_SCREENSHOT.get(field, [])
        needed_prefixes.update(prefixes)

    if not needed_prefixes:
        return []

    screenshots = []
    priority = {
        "endgame_damage": 0,
        "endgame": 1,
        "stats_": 2,
        "loadout_": 3,
        "progress_": 4,
        "deploy": 5,
        "readyup": 6,
        "_char": 7,
    }
    for f in sorted(ss_dir.iterdir()):
        if not f.suffix.lower() in (".jpg", ".jpeg", ".png"):
            continue
        for prefix in needed_prefixes:
            if prefix in f.name:
                screenshots.append(str(f))
                break

    def sort_key(path: str):
        name = Path(path).name
        best = min((rank for token, rank in priority.items() if token in name), default=99)
        return (best, name)

    deduped = list(dict.fromkeys(sorted(screenshots, key=sort_key)))
    # Keep the call targeted but allow enough images to cover stats + loadout + death.
    return deduped[:8]


class HybridRouter:
    """Route processing through Alpha, Claude, or both."""

    def __init__(self, mode: str = "alpha", confidence_threshold: float = None):
        """
        Parameters
        ----------
        mode : "alpha" (local only), "hybrid" (local + Claude fallback), or "claude" (cloud only)
        confidence_threshold : override for hybrid fallback threshold (default 0.8)
        """
        self.mode = mode
        self.threshold = confidence_threshold or DEFAULT_CONFIDENCE_THRESHOLD
        self._alpha = None

    @property
    def alpha(self) -> AlphaProcessor:
        if self._alpha is None:
            self._alpha = AlphaProcessor()
        return self._alpha

    def process_run(self, screenshots_dir: str | Path,
                    video_path: str | None = None) -> dict:
        """Process a run using the configured mode.

        Returns the same schema as AlphaProcessor.process_run().
        """
        if self.mode == "claude":
            return self._process_cloud(screenshots_dir)

        # Alpha first (alpha or hybrid)
        result = self.alpha.process_run(screenshots_dir, video_path=video_path)

        if self.mode == "alpha":
            result["_routing"] = "alpha"
            return result

        # Hybrid: repair every supported low-confidence field, not just stats.
        low_fields = [
            f for f in result.get("_low_confidence_fields", [])
            if f in FALLBACK_FIELDS
        ]

        if not low_fields:
            logger.info("Hybrid: all supported fields high confidence - no Claude call needed")
            result["_routing"] = "alpha_only"
            result.setdefault("_claude_fields", [])
            result["_alpha_health"] = {
                **result.get("_alpha_health", {}),
                "routing": "alpha_only",
                "claude_fields": [],
            }
            return result

        # Send targeted Claude call for just the low-confidence fields
        logger.info(f"Hybrid: {len(low_fields)} low-confidence fields, calling Claude")
        claude_result = self._targeted_claude_call(
            Path(screenshots_dir), low_fields, result
        )

        if claude_result:
            # Merge Claude answers into result (Claude overrides low-confidence alpha)
            deltas = {}
            for field, value in claude_result.items():
                if field.startswith("_"):
                    continue
                if value is not None:
                    old_val = result.get(field)
                    result[field] = value
                    result.setdefault("_confidence", {})[field] = 0.95
                    result.setdefault("_sources", {})[field] = "claude_targeted"
                    deltas[field] = {"alpha": old_val, "claude": value}
                    logger.info("Hybrid override: %s: %s -> %s", field, old_val, value)

            # Recalculate derived fields
            if (
                "kills" in low_fields
                or "combatant_eliminations" in low_fields
                or "runner_eliminations" in low_fields
            ):
                ce = result.get("combatant_eliminations")
                re_ = result.get("runner_eliminations")
                ce = ce if ce is not None else 0
                re_ = re_ if re_ is not None else 0
                result["kills"] = ce + re_
                result.setdefault("_confidence", {})["kills"] = min(
                    result.get("_confidence", {}).get("combatant_eliminations", 0.95),
                    result.get("_confidence", {}).get("runner_eliminations", 0.95),
                )

            if "survived" in low_fields and result.get("survived") is not None:
                result["deaths"] = 0 if result["survived"] else 1

            # Re-grade with corrected stats
            from backend.app.alpha.grading import calculate_grade, generate_summary
            grade = calculate_grade(
                survived=bool(result.get("survived", False)),
                runner_kills=result.get("runner_eliminations") or 0,
                combatant_kills=result.get("combatant_eliminations") or 0,
                loot_value=result.get("loot_value_total") or 0,
                crew_revives=result.get("crew_revives") or 0,
                duration_seconds=result.get("duration_seconds") or 0,
                combat_intensity=result.get("combat_intensity", 0.0),
            )
            result["grade"] = grade
            result["summary"] = generate_summary({**result, "grade": grade})

            # Remove corrected fields from low-confidence list
            result["_low_confidence_fields"] = [
                f for f in result.get("_low_confidence_fields", [])
                if f not in deltas
            ]
            result["_routing"] = "hybrid"
            result["_claude_fields"] = list(claude_result.keys())
            result["_claude_deltas"] = deltas
            result["_alpha_health"] = {
                **result.get("_alpha_health", {}),
                "routing": "hybrid",
                "claude_fields": list(claude_result.keys()),
                "remaining_low_confidence_fields": result["_low_confidence_fields"],
            }
            self._save_fallback_trace(Path(screenshots_dir), low_fields, result, claude_result, deltas)
        else:
            result["_routing"] = "alpha_fallback"
            result.setdefault("_claude_fields", [])
            result["_alpha_health"] = {
                **result.get("_alpha_health", {}),
                "routing": "alpha_fallback",
                "claude_fields": [],
                "remaining_low_confidence_fields": result.get("_low_confidence_fields", []),
            }
            logger.warning("Hybrid: Claude call failed, using alpha results as-is")

        return result

    def _targeted_claude_call(self, ss_dir: Path, low_fields: list[str],
                              alpha_result: dict) -> dict | None:
        """Send a minimal Claude call for specific low-confidence fields.

        Returns parsed dict of just the requested fields, or None on failure.
        """
        screenshots = _find_relevant_screenshots(ss_dir, low_fields)
        if not screenshots:
            logger.warning("No relevant screenshots found for Claude fallback")
            return None

        prompt = _build_targeted_prompt(
            low_fields,
            alpha_result,
            alpha_result.get("_confidence", {}),
        )

        try:
            from backend.app.ai_client import run_api_prompt, run_cli_prompt, prefer_cli

            if prefer_cli():
                image_instructions = "\n".join(
                    f"- Read the image file at: {Path(p).resolve()}" for p in screenshots
                )
                response = run_cli_prompt(
                    f"First read these image files:\n{image_instructions}\n\n{prompt}",
                    purpose="capture",
                    work_dir=str(ss_dir),
                    allowed_tools=["Read"],
                    timeout=60,
                )
            else:
                response = run_api_prompt(
                    prompt,
                    images=screenshots,
                    purpose="capture",
                    max_tokens=512,
                )

            # Parse JSON from response
            text = response.strip()
            # Strip markdown fences if present
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                text = text[start:end]

            parsed = json.loads(text)
            logger.info("Claude targeted response: %s", parsed)
            return {k: v for k, v in parsed.items() if k in low_fields or k.startswith("_")}

        except json.JSONDecodeError as e:
            logger.error(f"Claude returned invalid JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"Claude targeted call failed: {e}")
            return None

    def _save_fallback_trace(self, ss_dir: Path, requested_fields: list[str],
                             result: dict, claude_result: dict, deltas: dict) -> None:
        """Append targeted fallback results for later alpha training/validation."""
        try:
            from backend.app.config import _DATA_DIR
            trace_path = Path(_DATA_DIR) / "alpha_hybrid_feedback.jsonl"
            trace = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "screenshots_dir": str(ss_dir),
                "requested_fields": requested_fields,
                "claude_fields": list(claude_result.keys()),
                "deltas": deltas,
                "confidence": {
                    field: result.get("_confidence", {}).get(field)
                    for field in requested_fields
                },
                "sources": {
                    field: result.get("_sources", {}).get(field)
                    for field in requested_fields
                },
            }
            with open(trace_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(trace, ensure_ascii=True) + "\n")
        except Exception:
            logger.debug("Failed to save hybrid fallback trace", exc_info=True)

    def _process_cloud(self, screenshots_dir: str | Path) -> dict:
        """Full Claude-only processing (original behavior).

        Uses the API client directly (sync) to avoid async event loop issues.
        """
        ss_dir = Path(screenshots_dir)
        image_paths = sorted([
            str(f) for f in ss_dir.iterdir()
            if f.suffix.lower() in (".jpg", ".jpeg", ".png")
        ])

        if not image_paths:
            return {"error": "No screenshots found"}

        try:
            from backend.app.ai_client import run_api_prompt, run_cli_prompt, prefer_cli
            from backend.app.api.screenshot import PARSE_PROMPT

            if prefer_cli():
                response = run_cli_prompt(
                    PARSE_PROMPT,
                    purpose="capture",
                    work_dir=str(ss_dir),
                    allowed_tools=["Read"],
                    timeout=120,
                )
            else:
                response = run_api_prompt(
                    PARSE_PROMPT,
                    images=image_paths,
                    purpose="capture",
                )

            text = response.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            result = json.loads(text)
            result["_routing"] = "cloud"
            return result
        except Exception as e:
            logger.error(f"Cloud processing failed: {e}")
            return {"error": str(e), "_routing": "cloud_failed"}


def get_processing_mode() -> str:
    """Read processing mode from user settings.

    Returns "alpha", "hybrid", or "claude".
    """
    try:
        from backend.app.api.settings_api import get_config_value
        mode = get_config_value("processor_mode")
        if mode in ("alpha", "hybrid", "claude"):
            return mode
    except Exception:
        pass
    return "alpha"


def create_router() -> HybridRouter:
    """Create a HybridRouter with the user's configured mode."""
    mode = get_processing_mode()
    logger.info(f"Creating HybridRouter in '{mode}' mode")
    return HybridRouter(mode=mode)

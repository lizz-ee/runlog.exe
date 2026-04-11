"""
Alpha Data Preparation — Extract and label training data from existing RunLog captures.

This script cross-references the RunLog database with captured screenshots to produce:
1. Labeled shell crops for classifier training
2. Stats region crops with ground truth for OCR validation
3. Template images for game state detection
4. Deploy coordinate crops for OCR validation

Usage:
    python -m backend.app.alpha.data_prep [command]

Commands:
    all             Run all extraction steps
    shells          Extract shell training crops
    stats           Extract stats OCR validation pairs
    templates       Extract template images
    coords          Extract coordinate OCR validation pairs
    summary         Print data inventory summary
"""

import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# --- Paths ---
APPDATA_DIR = Path(os.environ.get("APPDATA", "")) / "runlog" / "marathon" / "data"
DB_PATH = APPDATA_DIR / "runlog.db"
CLIPS_DIR = APPDATA_DIR / "clips"
RECORDINGS_DIR = APPDATA_DIR / "recordings"

ALPHA_DIR = Path(__file__).parent
TRAINING_DIR = ALPHA_DIR / "training_data"
TEMPLATES_DIR = ALPHA_DIR / "templates"

# Where Steam screenshots live (can be overridden)
STEAM_SCREENSHOTS_DIR = Path(__file__).parents[3] / "screenshots"


# --- Crop Regions (percentage-based, matching capture.py) ---
CROPS = {
    # Shell identification crops
    "character": (0.395, 0.10, 0.605, 0.43),   # Upper body for shell ID
    "face":      (0.395, 0.43, 0.439, 0.581),  # Face portrait
    # Center crop (loadout, gamertag area)
    "center":    (0.39, 0.39, 0.61, 0.64),
    # Stats wide crop
    "stats_wide": (0.03, 0.55, 0.97, 0.92),
    # Endgame damage widget
    "damage":    (0.74, 0.17, 0.97, 0.75),
    # Deploy text region (map name + coords)
    "deploy_text": (0.30, 0.35, 0.70, 0.70),
    # Coordinate region (tighter crop for just the numbers)
    "coords_only": (0.40, 0.55, 0.60, 0.68),
    # Banner region (EXFILTRATED/ELIMINATED)
    "banner":    (0.25, 0.40, 0.75, 0.60),
    # Top bar (level pill, vault)
    "top_bar":   (0.0, 0.0, 0.35, 0.05),
    # Tab headers (STATS/PROGRESS/LOADOUT)
    "tabs":      (0.75, 0.0, 1.0, 0.05),
    # Map name region on deploy screen
    "map_name":  (0.30, 0.42, 0.70, 0.55),
    # Stats column regions for trio layout
    "stats_left":   (0.03, 0.40, 0.35, 0.92),
    "stats_center": (0.35, 0.40, 0.65, 0.92),
    "stats_right":  (0.65, 0.40, 0.97, 0.92),
    # Individual stat rows (relative to a single column)
    # These are within the stats_wide crop, as fractions of the column
    "gamertag_row":     (0.0, 0.0, 1.0, 0.12),
    "banner_row":       (0.0, 0.12, 1.0, 0.25),
    "combatant_val":    (0.5, 0.28, 1.0, 0.38),
    "runner_val":       (0.5, 0.38, 1.0, 0.48),
    "revives_val":      (0.5, 0.48, 1.0, 0.58),
    "inventory_val":    (0.5, 0.58, 1.0, 0.70),
    # Run time at bottom center
    "run_time":  (0.35, 0.88, 0.65, 0.95),
    # Bottom bar (lobby state)
    "lobby_bar": (0.33, 0.72, 0.67, 0.89),
    # Readyup gamertag (top center)
    "readyup_gamertag": (0.40, 0.02, 0.60, 0.08),
    # Loadout value overlay
    "loadout_value": (0.42, 0.39, 0.52, 0.44),
}


def crop_region(img: Image.Image, region: tuple) -> Image.Image:
    """Crop an image using percentage-based region (x1%, y1%, x2%, y2%)."""
    w, h = img.size
    x1 = int(w * region[0])
    y1 = int(h * region[1])
    x2 = int(w * region[2])
    y2 = int(h * region[3])
    return img.crop((x1, y1, x2, y2))


def folder_timestamp_to_db_date(folder_ts: str) -> str:
    """Convert folder timestamp '20260322_211334' to match DB date '2026-03-22 21:13:34'."""
    # folder_ts: 20260322_211334
    dt = datetime.strptime(folder_ts, "%Y%m%d_%H%M%S")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def get_db_runs() -> list:
    """Load all runs from database with shell names."""
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute("""
        SELECT r.id, r.date, rn.name as shell_name, r.map_name, r.survived,
               r.kills, r.combatant_eliminations, r.runner_eliminations,
               r.crew_revives, r.duration_seconds, r.loot_value_total,
               r.primary_weapon, r.secondary_weapon, r.killed_by,
               r.killed_by_weapon, r.killed_by_damage, r.damage_contributors,
               r.player_gamertag, r.squad_members, r.player_level, r.vault_value,
               r.grade
        FROM runs r
        LEFT JOIN runners rn ON r.runner_id = rn.id
        ORDER BY r.date
    """).fetchall()
    db.close()
    return [dict(row) for row in rows]


def match_folder_to_run(folder_name: str, runs: list) -> dict | None:
    """Match a clip folder name to a database run by timestamp."""
    folder_ts = folder_name.replace("run_", "")
    target_date = folder_timestamp_to_db_date(folder_ts)

    for run in runs:
        if not run["date"]:
            continue
        # Normalize DB date format (handles both space and T separator, with/without timezone)
        db_date = run["date"].replace("T", " ").split("+")[0].split(".")[0]
        if db_date == target_date:
            return run

    # Fuzzy match: within 60 seconds
    try:
        target_dt = datetime.strptime(target_date, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

    for run in runs:
        if not run["date"]:
            continue
        db_date_str = run["date"].replace("T", " ").split("+")[0].split(".")[0]
        try:
            db_dt = datetime.strptime(db_date_str, "%Y-%m-%d %H:%M:%S")
            if abs((db_dt - target_dt).total_seconds()) < 120:
                return run
        except ValueError:
            continue

    return None


# =============================================================================
# Step 1: Extract Shell Training Crops
# =============================================================================

def extract_shells(runs: list):
    """Extract and label shell crops from readyup screenshots."""
    shells_dir = TRAINING_DIR / "shells"
    extracted = {s: 0 for s in ["assassin", "destroyer", "recon", "rook", "thief", "triage", "vandal"]}

    print("\n=== Extracting Shell Training Crops ===")

    for folder in sorted(CLIPS_DIR.iterdir()):
        if not folder.name.startswith("run_"):
            continue
        ss_dir = folder / "screenshots"
        if not ss_dir.exists():
            continue

        run = match_folder_to_run(folder.name, runs)
        if not run or not run.get("shell_name"):
            continue

        shell = run["shell_name"].lower()
        shell_dir = shells_dir / shell
        shell_dir.mkdir(parents=True, exist_ok=True)

        # Extract from character_crop if it exists (best quality)
        char_crop = ss_dir / "character_crop.jpg"
        if char_crop.exists():
            dest = shell_dir / f"{folder.name}_character.jpg"
            if not dest.exists():
                img = Image.open(char_crop)
                img.save(str(dest), quality=95)
                extracted[shell] += 1
                print(f"  [char_crop] {shell}: {folder.name}")

        # Extract from face_crop if it exists
        face_crop = ss_dir / "face_crop.jpg"
        if face_crop.exists():
            dest = shell_dir / f"{folder.name}_face.jpg"
            if not dest.exists():
                img = Image.open(face_crop)
                img.save(str(dest), quality=95)

        # Extract character region from readyup screenshots
        for ss_name in ["readyup.jpg", "readyup_1.jpg", "readyup_2.jpg", "readyup_3.jpg"]:
            ss_path = ss_dir / ss_name
            if ss_path.exists():
                dest = shell_dir / f"{folder.name}_{ss_name.replace('.jpg', '')}_char.jpg"
                if not dest.exists():
                    img = Image.open(ss_path)
                    char = crop_region(img, CROPS["character"])
                    char.save(str(dest), quality=95)
                    extracted[shell] += 1
                    print(f"  [readyup] {shell}: {folder.name}/{ss_name}")

        # Extract from deploying screenshots
        deploying = ss_dir / "deploying.jpg"
        if deploying.exists():
            dest = shell_dir / f"{folder.name}_deploying_char.jpg"
            if not dest.exists():
                img = Image.open(deploying)
                char = crop_region(img, CROPS["character"])
                char.save(str(dest), quality=95)
                extracted[shell] += 1

    print(f"\n  Shell crop totals:")
    for shell, count in sorted(extracted.items()):
        print(f"    {shell}: {count}")
    print(f"  Total: {sum(extracted.values())}")

    return extracted


# =============================================================================
# Step 2: Extract Stats OCR Validation Data
# =============================================================================

def extract_stats(runs: list):
    """Extract stats tab crops paired with ground truth from DB."""
    stats_dir = TRAINING_DIR / "stats"
    stats_dir.mkdir(parents=True, exist_ok=True)

    print("\n=== Extracting Stats OCR Validation Data ===")

    pairs = []

    for folder in sorted(CLIPS_DIR.iterdir()):
        if not folder.name.startswith("run_"):
            continue
        ss_dir = folder / "screenshots"
        if not ss_dir.exists():
            continue

        run = match_folder_to_run(folder.name, runs)
        if not run:
            continue

        # Find stats screenshots
        stats_files = sorted([f for f in ss_dir.iterdir()
                              if f.name.startswith("stats_") and "crop" not in f.name])

        if not stats_files:
            continue

        # Save ground truth JSON
        ground_truth = {
            "run_id": run["id"],
            "folder": folder.name,
            "map_name": run["map_name"],
            "survived": bool(run["survived"]),
            "kills": run["kills"],
            "combatant_eliminations": run["combatant_eliminations"],
            "runner_eliminations": run["runner_eliminations"],
            "crew_revives": run["crew_revives"],
            "duration_seconds": run["duration_seconds"],
            "loot_value_total": run["loot_value_total"],
            "primary_weapon": run["primary_weapon"],
            "secondary_weapon": run["secondary_weapon"],
            "killed_by": run["killed_by"],
            "player_gamertag": run["player_gamertag"],
            "player_level": run["player_level"],
            "vault_value": run["vault_value"],
            "grade": run["grade"],
        }

        run_stats_dir = stats_dir / folder.name
        run_stats_dir.mkdir(exist_ok=True)

        # Save ground truth
        gt_path = run_stats_dir / "ground_truth.json"
        with open(gt_path, "w") as f:
            json.dump(ground_truth, f, indent=2)

        # Copy and crop stats screenshots
        for ss in stats_files:
            # Full screenshot
            dest = run_stats_dir / ss.name
            if not dest.exists():
                img = Image.open(ss)
                img.save(str(dest), quality=95)

            # Wide crop (stat values area)
            img = Image.open(ss)
            wide = crop_region(img, CROPS["stats_wide"])
            wide.save(str(run_stats_dir / f"{ss.stem}_wide.jpg"), quality=95)

            # Banner region
            banner = crop_region(img, CROPS["banner"])
            banner.save(str(run_stats_dir / f"{ss.stem}_banner.jpg"), quality=95)

            # Top bar (level, vault)
            top = crop_region(img, CROPS["top_bar"])
            top.save(str(run_stats_dir / f"{ss.stem}_topbar.jpg"), quality=95)

            # Tab headers
            tabs = crop_region(img, CROPS["tabs"])
            tabs.save(str(run_stats_dir / f"{ss.stem}_tabs.jpg"), quality=95)

            # Run time
            run_time = crop_region(img, CROPS["run_time"])
            run_time.save(str(run_stats_dir / f"{ss.stem}_runtime.jpg"), quality=95)

        pairs.append(folder.name)
        print(f"  [{len(stats_files)} stats] {folder.name}: "
              f"{'EXFILTRATED' if ground_truth['survived'] else 'ELIMINATED'} "
              f"kills={ground_truth['kills']} loot={ground_truth['loot_value_total']}")

    # Also extract from endgame screenshots
    for folder in sorted(CLIPS_DIR.iterdir()):
        if not folder.name.startswith("run_"):
            continue
        ss_dir = folder / "screenshots"
        if not ss_dir.exists():
            continue

        run = match_folder_to_run(folder.name, runs)
        if not run:
            continue

        # Endgame damage widget
        dmg = ss_dir / "endgame_damage.jpg"
        if dmg.exists():
            run_stats_dir = stats_dir / folder.name
            run_stats_dir.mkdir(exist_ok=True)
            dest = run_stats_dir / "endgame_damage.jpg"
            if not dest.exists():
                img = Image.open(dmg)
                img.save(str(dest), quality=95)

            # Save damage ground truth if available
            if run.get("damage_contributors"):
                gt_path = run_stats_dir / "damage_ground_truth.json"
                with open(gt_path, "w") as f:
                    json.dump({
                        "killed_by": run["killed_by"],
                        "killed_by_weapon": run["killed_by_weapon"],
                        "killed_by_damage": run["killed_by_damage"],
                        "damage_contributors": run["damage_contributors"],
                    }, f, indent=2)

    print(f"\n  Total runs with stats data: {len(pairs)}")
    return pairs


# =============================================================================
# Step 3: Extract Template Images
# =============================================================================

def extract_templates(runs: list):
    """Extract clean template images for matching."""
    maps_dir = TEMPLATES_DIR / "maps"
    banners_dir = TEMPLATES_DIR / "banners"
    tabs_dir = TEMPLATES_DIR / "tabs"
    pixel_data = {}

    maps_dir.mkdir(parents=True, exist_ok=True)
    banners_dir.mkdir(parents=True, exist_ok=True)
    tabs_dir.mkdir(parents=True, exist_ok=True)

    print("\n=== Extracting Template Images ===")

    # --- Map name templates from deploy screenshots ---
    map_templates = {}
    for folder in sorted(CLIPS_DIR.iterdir()):
        if not folder.name.startswith("run_"):
            continue
        ss_dir = folder / "screenshots"
        if not ss_dir.exists():
            continue

        run = match_folder_to_run(folder.name, runs)
        if not run or not run.get("map_name"):
            continue

        map_name = run["map_name"]

        # Find deploy screenshots
        for deploy_name in ["deploy.jpg", "deploy_1.jpg", "deploy_2.jpg", "deploy_3.jpg"]:
            deploy_path = ss_dir / deploy_name
            if not deploy_path.exists():
                continue

            img = Image.open(deploy_path)
            # Check if it's actually a deploy screen (not black)
            arr = np.array(img)
            center_brightness = arr[arr.shape[0]//3:2*arr.shape[0]//3,
                                   arr.shape[1]//3:2*arr.shape[1]//3].mean()
            if center_brightness < 15:
                continue  # Too dark, probably a bad capture

            # Crop map name region
            map_crop = crop_region(img, CROPS["map_name"])
            coord_crop = crop_region(img, CROPS["coords_only"])
            deploy_crop = crop_region(img, CROPS["deploy_text"])

            key = map_name.upper().replace(" ", "_")
            if key not in map_templates:
                map_templates[key] = deploy_path
                # Save map name template
                map_crop.save(str(maps_dir / f"{key}_{img.size[0]}x{img.size[1]}.jpg"), quality=95)
                # Save full deploy text for reference
                deploy_crop.save(str(maps_dir / f"{key}_full_{img.size[0]}x{img.size[1]}.jpg"), quality=95)
                print(f"  [map] {key} from {folder.name}/{deploy_name} ({img.size[0]}x{img.size[1]})")

                # Sample pixel color from deploy screen for color gate
                center_pixel = arr[arr.shape[0]//2, arr.shape[1]//2]
                pixel_data[f"deploy_{key}"] = {
                    "position": [0.5, 0.5],
                    "color_rgb": center_pixel.tolist(),
                    "resolution": list(img.size),
                }

    # --- Banner templates from endgame/stats screenshots ---
    exfiltrated_found = False
    eliminated_found = False

    for folder in sorted(CLIPS_DIR.iterdir()):
        if not folder.name.startswith("run_"):
            continue
        ss_dir = folder / "screenshots"
        if not ss_dir.exists():
            continue

        run = match_folder_to_run(folder.name, runs)
        if not run:
            continue

        # Check stats screenshots for banners
        for stats_name in ["stats_1.jpg", "stats_2.jpg", "stats_3.jpg"]:
            stats_path = ss_dir / stats_name
            if not stats_path.exists():
                continue

            img = Image.open(stats_path)
            arr = np.array(img)

            # Check if EXFILTRATED or ELIMINATED by center color
            banner_region = crop_region(img, CROPS["banner"])
            banner_arr = np.array(banner_region)
            avg_r = banner_arr[:, :, 0].mean()
            avg_g = banner_arr[:, :, 1].mean()

            if run["survived"] and not exfiltrated_found and avg_g > avg_r:
                banner_region.save(str(banners_dir / f"EXFILTRATED_{img.size[0]}x{img.size[1]}.jpg"), quality=95)
                exfiltrated_found = True
                print(f"  [banner] EXFILTRATED from {folder.name}/{stats_name}")

                # Pixel sample for green banner
                pixel_data["exfiltrated_banner"] = {
                    "position": [0.5, 0.48],
                    "avg_color_rgb": [int(avg_r), int(avg_g), int(banner_arr[:, :, 2].mean())],
                    "resolution": list(img.size),
                }

            elif not run["survived"] and not eliminated_found and avg_r > avg_g:
                banner_region.save(str(banners_dir / f"ELIMINATED_{img.size[0]}x{img.size[1]}.jpg"), quality=95)
                eliminated_found = True
                print(f"  [banner] ELIMINATED from {folder.name}/{stats_name}")

                pixel_data["eliminated_banner"] = {
                    "position": [0.5, 0.48],
                    "avg_color_rgb": [int(avg_r), int(avg_g), int(banner_arr[:, :, 2].mean())],
                    "resolution": list(img.size),
                }

        # Tab headers
        for stats_name in ["stats_1.jpg"]:
            stats_path = ss_dir / stats_name
            if not stats_path.exists():
                continue

            img = Image.open(stats_path)
            if img.size[1] < 500:
                continue

            tabs_crop = crop_region(img, CROPS["tabs"])
            dest = tabs_dir / f"tabs_{img.size[0]}x{img.size[1]}.jpg"
            if not dest.exists():
                tabs_crop.save(str(dest), quality=95)
                print(f"  [tabs] Tab headers from {folder.name}")
                break  # One is enough per resolution

    # --- RUN_COMPLETE banner from endgame screenshots ---
    for folder in sorted(CLIPS_DIR.iterdir()):
        if not folder.name.startswith("run_"):
            continue
        ss_dir = folder / "screenshots"
        endgame = ss_dir / "endgame.jpg"
        if not endgame.exists():
            continue

        img = Image.open(endgame)
        arr = np.array(img)
        # RUN_COMPLETE has a bright yellow-green banner at ~15-25% height
        banner_region = arr[int(arr.shape[0]*0.12):int(arr.shape[0]*0.22),
                           int(arr.shape[1]*0.28):int(arr.shape[1]*0.72)]
        avg_brightness = banner_region.mean()
        avg_g = banner_region[:, :, 1].mean()

        if avg_brightness > 100 and avg_g > 150:
            # This is a RUN_COMPLETE screen
            crop = img.crop((int(img.size[0]*0.25), int(img.size[1]*0.10),
                           int(img.size[0]*0.75), int(img.size[1]*0.25)))
            dest = banners_dir / f"RUN_COMPLETE_{img.size[0]}x{img.size[1]}.jpg"
            if not dest.exists():
                crop.save(str(dest), quality=95)
                print(f"  [banner] RUN_COMPLETE from {folder.name}")
            break

    # --- Also extract from Steam screenshots for 4K templates ---
    if STEAM_SCREENSHOTS_DIR.exists():
        steam_files = sorted(STEAM_SCREENSHOTS_DIR.glob("*.jpg"))
        for ss_path in steam_files:
            if not ss_path.name[0].isdigit():
                continue
            try:
                img = Image.open(ss_path)
            except Exception:
                continue

            if img.size[0] != 3840:
                continue  # Only want 4K

            arr = np.array(img)

            # Check for blue deploy screen
            center = arr[arr.shape[0]//3:2*arr.shape[0]//3,
                        arr.shape[1]//3:2*arr.shape[1]//3]
            avg_b = center[:, :, 2].mean()
            avg_r = center[:, :, 0].mean()
            avg_g = center[:, :, 1].mean()

            if avg_b > 150 and avg_r < 80 and avg_g < 80:
                # Blue deploy screen at 4K
                deploy_crop = crop_region(img, CROPS["deploy_text"])
                map_crop = crop_region(img, CROPS["map_name"])
                # Try to identify which map
                dest = maps_dir / f"DEPLOY_4K_{ss_path.stem}.jpg"
                if not dest.exists():
                    deploy_crop.save(str(dest), quality=95)
                    map_crop.save(str(maps_dir / f"MAP_4K_{ss_path.stem}.jpg"), quality=95)
                    print(f"  [steam 4K] Deploy screen: {ss_path.name}")

                # Save pixel calibration for blue deploy
                pixel_data["deploy_blue_4k"] = {
                    "position": [0.5, 0.5],
                    "color_rgb": [int(avg_r), int(avg_g), int(avg_b)],
                    "resolution": [3840, 2160],
                }

            # Check for stats tab (EXFILTRATED green or ELIMINATED red at 4K)
            banner_area = arr[int(arr.shape[0]*0.40):int(arr.shape[0]*0.55),
                             int(arr.shape[1]*0.30):int(arr.shape[1]*0.70)]
            b_r, b_g = banner_area[:,:,0].mean(), banner_area[:,:,1].mean()

            if b_g > 150 and b_g > b_r * 1.5 and "exfiltrated_4k" not in pixel_data:
                # EXFILTRATED at 4K
                banner = crop_region(img, CROPS["banner"])
                dest = banners_dir / f"EXFILTRATED_4K_{ss_path.stem}.jpg"
                if not dest.exists():
                    banner.save(str(dest), quality=95)
                    print(f"  [steam 4K] EXFILTRATED: {ss_path.name}")
                pixel_data["exfiltrated_4k"] = {
                    "position": [0.5, 0.48],
                    "avg_color_rgb": [int(b_r), int(b_g), int(banner_area[:,:,2].mean())],
                    "resolution": [3840, 2160],
                }

            if b_r > 120 and b_r > b_g * 1.5 and "eliminated_4k" not in pixel_data:
                # ELIMINATED at 4K
                banner = crop_region(img, CROPS["banner"])
                dest = banners_dir / f"ELIMINATED_4K_{ss_path.stem}.jpg"
                if not dest.exists():
                    banner.save(str(dest), quality=95)
                    print(f"  [steam 4K] ELIMINATED: {ss_path.name}")

    # Save pixel calibration data
    cal_path = TEMPLATES_DIR / "pixel_calibration.json"
    with open(cal_path, "w") as f:
        json.dump(pixel_data, f, indent=2)
    print(f"\n  Pixel calibration saved to {cal_path}")
    print(f"  Calibration points: {len(pixel_data)}")


# =============================================================================
# Step 4: Extract Deploy Coordinate Validation Data
# =============================================================================

def extract_coords(runs: list):
    """Extract deploy screen coordinate crops paired with DB spawn data."""
    coords_dir = TRAINING_DIR / "deploy"
    coords_dir.mkdir(parents=True, exist_ok=True)

    print("\n=== Extracting Deploy Coordinate Validation Data ===")

    # Get spawn points from DB
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    spawn_points = {
        row["id"]: dict(row)
        for row in db.execute("SELECT * FROM spawn_points").fetchall()
    }
    # Get spawn_point_id for each run
    run_spawns = {
        row["id"]: row["spawn_point_id"]
        for row in db.execute("SELECT id, spawn_point_id FROM runs WHERE spawn_point_id IS NOT NULL").fetchall()
    }
    db.close()

    pairs = []

    for folder in sorted(CLIPS_DIR.iterdir()):
        if not folder.name.startswith("run_"):
            continue
        ss_dir = folder / "screenshots"
        if not ss_dir.exists():
            continue

        run = match_folder_to_run(folder.name, runs)
        if not run:
            continue

        # Get spawn coordinates from DB
        spawn_id = run_spawns.get(run["id"])
        spawn = spawn_points.get(spawn_id) if spawn_id else None

        for deploy_name in ["deploy.jpg", "deploy_1.jpg", "deploy_2.jpg", "deploy_3.jpg"]:
            deploy_path = ss_dir / deploy_name
            if not deploy_path.exists():
                continue

            img = Image.open(deploy_path)
            arr = np.array(img)

            # Skip black/empty screens
            center_brightness = arr[arr.shape[0]//3:2*arr.shape[0]//3,
                                   arr.shape[1]//3:2*arr.shape[1]//3].mean()
            if center_brightness < 15:
                continue

            # Crop the full deploy text area
            text_crop = crop_region(img, CROPS["deploy_text"])
            coord_crop = crop_region(img, CROPS["coords_only"])

            dest_prefix = f"{folder.name}_{deploy_name.replace('.jpg', '')}"

            text_crop.save(str(coords_dir / f"{dest_prefix}_text.jpg"), quality=95)
            coord_crop.save(str(coords_dir / f"{dest_prefix}_coords.jpg"), quality=95)

            # Save ground truth
            ground_truth = {
                "map_name": run["map_name"],
                "spawn_point_id": spawn_id,
            }
            if spawn:
                ground_truth["game_x"] = spawn.get("game_x")
                ground_truth["game_y"] = spawn.get("game_y")
                ground_truth["screen_x"] = spawn.get("screen_x")
                ground_truth["screen_y"] = spawn.get("screen_y")
                ground_truth["location_name"] = spawn.get("name")

            gt_path = coords_dir / f"{dest_prefix}_truth.json"
            with open(gt_path, "w") as f:
                json.dump(ground_truth, f, indent=2)

            pairs.append(dest_prefix)
            break  # One good deploy screenshot per run is enough

    print(f"  Total coordinate validation pairs: {len(pairs)}")
    return pairs


# =============================================================================
# Summary
# =============================================================================

def print_summary():
    """Print a summary of all available training data."""
    print("\n" + "=" * 60)
    print("TRAINING DATA INVENTORY")
    print("=" * 60)

    # Shells
    shells_dir = TRAINING_DIR / "shells"
    if shells_dir.exists():
        print("\n--- Shell Training Crops ---")
        total = 0
        for shell_dir in sorted(shells_dir.iterdir()):
            if shell_dir.is_dir():
                count = len(list(shell_dir.glob("*.jpg")))
                total += count
                status = "OK" if count >= 20 else "NEEDS MORE" if count >= 5 else "CRITICAL"
                print(f"  {shell_dir.name}: {count} crops [{status}]")
        print(f"  Total: {total}")
    else:
        print("\n--- Shell Training Crops: NOT EXTRACTED ---")

    # Stats
    stats_dir = TRAINING_DIR / "stats"
    if stats_dir.exists():
        runs_with_stats = len([d for d in stats_dir.iterdir() if d.is_dir()])
        print(f"\n--- Stats Validation Data ---")
        print(f"  Runs with stats screenshots: {runs_with_stats}")
        gt_count = len(list(stats_dir.glob("*/ground_truth.json")))
        print(f"  Runs with ground truth: {gt_count}")
    else:
        print("\n--- Stats Validation Data: NOT EXTRACTED ---")

    # Deploy coords
    coords_dir = TRAINING_DIR / "deploy"
    if coords_dir.exists():
        coord_pairs = len(list(coords_dir.glob("*_truth.json")))
        print(f"\n--- Coordinate Validation Data ---")
        print(f"  Coordinate pairs: {coord_pairs}")
    else:
        print("\n--- Coordinate Validation Data: NOT EXTRACTED ---")

    # Templates
    if TEMPLATES_DIR.exists():
        print(f"\n--- Template Images ---")
        for subdir in ["maps", "banners", "tabs"]:
            d = TEMPLATES_DIR / subdir
            if d.exists():
                count = len(list(d.glob("*.jpg")))
                print(f"  {subdir}: {count} templates")
        cal = TEMPLATES_DIR / "pixel_calibration.json"
        if cal.exists():
            with open(cal) as f:
                data = json.load(f)
            print(f"  pixel_calibration: {len(data)} calibration points")
    else:
        print("\n--- Template Images: NOT EXTRACTED ---")


# =============================================================================
# Main
# =============================================================================

def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "all"

    if command == "summary":
        print_summary()
        return

    print(f"Loading database from {DB_PATH}...")
    runs = get_db_runs()
    print(f"Loaded {len(runs)} runs")

    if command in ("all", "shells"):
        extract_shells(runs)

    if command in ("all", "stats"):
        extract_stats(runs)

    if command in ("all", "templates"):
        extract_templates(runs)

    if command in ("all", "coords"):
        extract_coords(runs)

    print_summary()


if __name__ == "__main__":
    main()

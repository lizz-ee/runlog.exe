"""
Alpha capability health checks.

This lets the backend/UI distinguish "alpha is fully capable" from "alpha is
running in degraded mode because an OCR/runtime dependency is missing".
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from functools import lru_cache
from pathlib import Path


ALPHA_DIR = Path(__file__).resolve().parent
MODEL_PATH = ALPHA_DIR / "models" / "shell_classifier.pth"
CLASSES_PATH = ALPHA_DIR / "models" / "shell_classes.json"
TEMPLATES_DIR = ALPHA_DIR / "templates"
TRAINING_DIR = ALPHA_DIR / "training_data"


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _tesseract_path() -> str | None:
    for candidate in [
        os.environ.get("TESSERACT_CMD"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        shutil.which("tesseract"),
    ]:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def _count_files(path: Path, pattern: str) -> int:
    try:
        return len(list(path.glob(pattern))) if path.exists() else 0
    except Exception:
        return 0


@lru_cache(maxsize=1)
def alpha_health() -> dict:
    deps = {
        "winocr": _module_available("winocr"),
        "easyocr": _module_available("easyocr"),
        "pytesseract": _module_available("pytesseract"),
        "tesseract_binary": _tesseract_path() is not None,
        "opencv": _module_available("cv2"),
        "torch": _module_available("torch"),
        "torchvision": _module_available("torchvision"),
        "scipy": _module_available("scipy"),
    }
    assets = {
        "shell_model": MODEL_PATH.exists(),
        "shell_classes": CLASSES_PATH.exists(),
        "map_templates": _count_files(TEMPLATES_DIR / "maps", "*.jpg"),
        "banner_templates": _count_files(TEMPLATES_DIR / "banners", "*.jpg"),
        "tab_templates": _count_files(TEMPLATES_DIR / "tabs", "*.jpg"),
        "stats_training_runs": _count_files(TRAINING_DIR / "stats", "*/ground_truth.json"),
        "damage_training_runs": _count_files(TRAINING_DIR / "stats", "*/damage_ground_truth.json"),
        "digit_training_crops": _count_files(TRAINING_DIR / "digits", "*/*.png"),
        "deploy_training_pairs": _count_files(TRAINING_DIR / "deploy", "*_truth.json"),
        "shell_training_crops": _count_files(TRAINING_DIR / "shells", "*/*.jpg"),
    }

    blockers = []
    warnings = []
    if not deps["winocr"]:
        blockers.append("winocr missing: menu/state/deploy/stat OCR is unavailable")
    if not deps["opencv"]:
        blockers.append("opencv missing: template and pixel detection is unavailable")
    if not deps["torch"] or not deps["torchvision"]:
        warnings.append("torch/torchvision missing: shell classifier is unavailable")
    if not assets["shell_model"] or not assets["shell_classes"]:
        warnings.append("shell classifier model/classes missing")
    if not deps["easyocr"]:
        warnings.append("easyocr missing: single-digit fallback is weaker")
    if not deps["pytesseract"] or not deps["tesseract_binary"]:
        warnings.append("Tesseract missing: stat row OCR and zero-vs-missing accuracy are weaker")
    if assets["map_templates"] == 0 or assets["banner_templates"] == 0:
        warnings.append("alpha templates are incomplete")

    status = "ready"
    if blockers:
        status = "degraded"
    elif warnings:
        status = "ready_with_warnings"

    return {
        "status": status,
        "ready": not blockers,
        "dependencies": deps,
        "assets": assets,
        "blockers": blockers,
        "warnings": warnings,
        "tesseract_path": _tesseract_path(),
    }


def clear_alpha_health_cache() -> None:
    alpha_health.cache_clear()

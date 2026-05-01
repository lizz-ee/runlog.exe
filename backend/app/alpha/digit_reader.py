"""
Local numeric crop reader for alpha mode.

General OCR engines are inconsistent on Marathon's tiny single-digit stat
values. This module centralizes numeric OCR attempts and adds a conservative
shape-based single-digit fallback so "missing" and "explicit zero" stay distinct.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_easyocr_reader():
    import easyocr
    return easyocr.Reader(["en"], gpu=False, verbose=False)


@lru_cache(maxsize=1)
def _configure_tesseract() -> None:
    import pytesseract
    for candidate in [
        os.environ.get("TESSERACT_CMD"),
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        shutil.which("tesseract"),
    ]:
        if candidate and Path(candidate).exists():
            pytesseract.pytesseract.tesseract_cmd = candidate
            break


@dataclass
class NumericRead:
    value: int | None
    confidence: float
    source: str
    raw_text: str = ""


def _normalize_text(text: str) -> str:
    text = text.replace("O", "0").replace("o", "0").replace("Q", "0")
    text = text.replace("I", "1").replace("l", "1").replace("|", "1")
    return text


def _parse_int(text: str) -> int | None:
    text = _normalize_text(text)
    match = re.search(r"-?\d[\d,]*", text)
    if not match:
        return None
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _preprocess(img: Image.Image) -> np.ndarray:
    arr = np.array(img.convert("L"))
    if arr.mean() < 128:
        arr = cv2.bitwise_not(arr)
    arr = cv2.resize(arr, (arr.shape[1] * 4, arr.shape[0] * 4), interpolation=cv2.INTER_LANCZOS4)
    arr = cv2.GaussianBlur(arr, (3, 3), 0)
    _, binary = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def _single_digit_shape(binary: np.ndarray) -> NumericRead:
    inv = 255 - binary
    contours, _ = cv2.findContours(inv, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    h, w = binary.shape[:2]
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw < max(3, w * 0.03) or bh < max(8, h * 0.20):
            continue
        if bw * bh < w * h * 0.003:
            continue
        boxes.append((x, y, bw, bh))

    if not boxes:
        # Empty crop: this is the only case where alpha may call a zero.
        ink_ratio = float((inv > 0).sum()) / max(1, inv.size)
        if ink_ratio < 0.002:
            return NumericRead(0, 0.48, "shape-empty-zero")
        return NumericRead(None, 0.0, "shape-empty")

    boxes.sort()
    if len(boxes) > 1:
        return NumericRead(None, 0.0, "shape-multichar")

    x, y, bw, bh = boxes[0]
    digit = inv[y:y + bh, x:x + bw]
    if digit.size == 0:
        return NumericRead(None, 0.0, "shape-empty")

    # Coarse 7-region occupancy. This is intentionally low-confidence and only
    # used after OCR engines fail.
    dh, dw = digit.shape[:2]
    top = digit[:max(1, dh // 5), :]
    mid = digit[dh * 2 // 5:dh * 3 // 5, :]
    bot = digit[dh * 4 // 5:, :]
    left_top = digit[:dh // 2, :max(1, dw // 3)]
    left_bot = digit[dh // 2:, :max(1, dw // 3)]
    right_top = digit[:dh // 2, dw * 2 // 3:]
    right_bot = digit[dh // 2:, dw * 2 // 3:]

    def occ(region: np.ndarray) -> bool:
        return (region > 0).mean() > 0.08 if region.size else False

    seg = (
        occ(top), occ(right_top), occ(right_bot), occ(bot),
        occ(left_bot), occ(left_top), occ(mid),
    )
    patterns = {
        (1, 1, 1, 1, 1, 1, 0): 0,
        (0, 1, 1, 0, 0, 0, 0): 1,
        (1, 1, 0, 1, 1, 0, 1): 2,
        (1, 1, 1, 1, 0, 0, 1): 3,
        (0, 1, 1, 0, 0, 1, 1): 4,
        (1, 0, 1, 1, 0, 1, 1): 5,
        (1, 0, 1, 1, 1, 1, 1): 6,
        (1, 1, 1, 0, 0, 0, 0): 7,
        (1, 1, 1, 1, 1, 1, 1): 8,
        (1, 1, 1, 1, 0, 1, 1): 9,
    }
    if seg in patterns:
        return NumericRead(patterns[seg], 0.44, "shape")
    return NumericRead(None, 0.0, "shape-unknown")


def read_numeric_crop(img: Image.Image) -> NumericRead:
    """Read an integer from a cropped value image."""
    # Tesseract first: best for stat rows when installed.
    try:
        import pytesseract
        _configure_tesseract()
        text = pytesseract.image_to_string(
            img.resize((img.width * 4, img.height * 4), Image.LANCZOS),
            config="--psm 7 -c tessedit_char_whitelist=0123456789,",
        ).strip()
        value = _parse_int(text)
        if value is not None:
            return NumericRead(value, 0.88, "tesseract", text)
    except Exception as e:
        logger.debug("Tesseract numeric read failed: %s", e)

    # EasyOCR second: catches some stylized value-only crops.
    try:
        reader = _get_easyocr_reader()
        arr = np.array(img.resize((img.width * 3, img.height * 3), Image.LANCZOS))
        results = reader.readtext(arr, detail=1, allowlist="0123456789,")
        text = " ".join(t for _, t, _ in results)
        value = _parse_int(text)
        if value is not None:
            conf = min((c for _, _, c in results), default=0.7)
            return NumericRead(value, round(0.72 * conf, 2), "easyocr", text)
    except Exception as e:
        logger.debug("EasyOCR numeric read failed: %s", e)

    binary = _preprocess(img)
    return _single_digit_shape(binary)

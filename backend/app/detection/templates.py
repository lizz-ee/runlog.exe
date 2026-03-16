"""
Template matching and color detection for Marathon game state recognition.

Templates are loaded once at import time and cached as numpy arrays.
All matching runs on small cropped regions for speed (~3-5ms per match).
"""

import os
import cv2
import numpy as np
from PIL import Image
import io

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'templates')


class TemplateStore:
    def __init__(self):
        self.templates: dict[str, np.ndarray] = {}
        self._load_all()

    def _load_all(self):
        if not os.path.isdir(TEMPLATES_DIR):
            print(f"[detect] Templates dir not found: {TEMPLATES_DIR}")
            return
        for fname in os.listdir(TEMPLATES_DIR):
            if fname.endswith(('.png', '.jpg')):
                name = os.path.splitext(fname)[0]
                path = os.path.join(TEMPLATES_DIR, fname)
                img = cv2.imread(path)
                if img is not None:
                    self.templates[name] = img
                    print(f"[detect] Loaded template: {name} ({img.shape[1]}x{img.shape[0]})")

    def match(self, image: np.ndarray, template_name: str, threshold: float = 0.7) -> tuple[bool, float]:
        """Match a template against an image region. Returns (matched, confidence)."""
        tpl = self.templates.get(template_name)
        if tpl is None:
            return False, 0.0

        # Scale template to match image if needed (templates are 4K, image might be different)
        th, tw = tpl.shape[:2]
        ih, iw = image.shape[:2]

        # If template is larger than image, scale it down
        if tw > iw or th > ih:
            scale = min(iw / tw, ih / th) * 0.9
            tpl = cv2.resize(tpl, (int(tw * scale), int(th * scale)), interpolation=cv2.INTER_LINEAR)
            th, tw = tpl.shape[:2]

        if tw > iw or th > ih:
            return False, 0.0

        result = cv2.matchTemplate(image, tpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)
        return max_val >= threshold, float(max_val)


def bytes_to_cv2(image_bytes: bytes) -> np.ndarray:
    """Convert image bytes (PNG/JPG) to OpenCV numpy array."""
    nparr = np.frombuffer(image_bytes, np.uint8)
    return cv2.imdecode(nparr, cv2.IMREAD_COLOR)


def analyze_color(image: np.ndarray) -> dict:
    """Analyze dominant colors in an image region."""
    b, g, r = cv2.split(image)
    return {
        "avg_r": float(np.mean(r)),
        "avg_g": float(np.mean(g)),
        "avg_b": float(np.mean(b)),
        "std_r": float(np.std(r)),
        "std_g": float(np.std(g)),
        "std_b": float(np.std(b)),
    }


def detect_loading_screen(image: np.ndarray) -> tuple[bool, float]:
    """
    Detect the Marathon loading screen: dark blue background with green/yellow text.
    Very distinctive — solid blue bg (R<50, G<30, B>100) with bright green center text.
    """
    h, w = image.shape[:2]

    # Check corners for dark blue background
    corners = [
        image[10:50, 10:50],           # top-left
        image[10:50, w-50:w-10],       # top-right
        image[h-50:h-10, 10:50],       # bottom-left
    ]

    for corner in corners:
        colors = analyze_color(corner)
        # Must be dark blue: high B, low R and G
        if not (colors["avg_b"] > 80 and colors["avg_r"] < 60 and colors["avg_g"] < 40):
            return False, 0.0

    # Check center for bright green/yellow text
    cy, cx = h // 2, w // 2
    center = image[cy-50:cy+50, cx-100:cx+100]
    center_colors = analyze_color(center)

    # Center should have some green/yellow (from the map name text)
    if center_colors["avg_g"] > 80:
        confidence = min(1.0, center_colors["avg_g"] / 200)
        return True, confidence

    return False, 0.0


def detect_banner(image: np.ndarray) -> tuple[str, float]:
    """
    Detect EXFILTRATED (green) or ELIMINATED (red) banners via color analysis.
    Checks the center strip of the region to avoid dark edges diluting the signal.

    Returns: ("exfiltrated" | "eliminated" | "none", confidence)
    """
    h, w = image.shape[:2]
    # Focus on center strip where banner color is strongest
    center = image[int(h*0.2):int(h*0.8), int(w*0.2):int(w*0.8)]
    colors = analyze_color(center)

    # EXFILTRATED: bright green/yellow banner (high G, moderate R, low B)
    if colors["avg_g"] > 100 and colors["avg_g"] > colors["avg_b"] * 2:
        return "exfiltrated", min(1.0, colors["avg_g"] / 200)

    # ELIMINATED: red banner (high R, low G, low B)
    if colors["avg_r"] > 80 and colors["avg_r"] > colors["avg_g"] * 1.5:
        return "eliminated", min(1.0, colors["avg_r"] / 200)

    return "none", 0.0


# Singleton template store — loaded once
_store: TemplateStore | None = None


def get_store() -> TemplateStore:
    global _store
    if _store is None:
        _store = TemplateStore()
    return _store

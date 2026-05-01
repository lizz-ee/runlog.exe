"""
Shell classifier inference — predicts which shell (character class) from a crop image.

Uses a MobileNetV2 fine-tuned on 7 Marathon shell classes:
  assassin, destroyer, recon, rook, thief, triage, vandal

Usage:
    from backend.app.alpha.shell_classifier import ShellClassifier

    classifier = ShellClassifier()
    name, confidence = classifier.predict("path/to/character_crop.jpg")
"""

import json
import logging
from pathlib import Path
from typing import Optional

import torch
import torch.nn as nn
from PIL import Image
from torchvision import models, transforms

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_MODULE_DIR = Path(__file__).resolve().parent
_MODEL_PATH = _MODULE_DIR / "models" / "shell_classifier.pth"
_CLASSES_PATH = _MODULE_DIR / "models" / "shell_classes.json"

# ---------------------------------------------------------------------------
# Transform (must match eval_transform from training)
# ---------------------------------------------------------------------------

_IMG_SIZE = 224

_eval_transform = transforms.Compose([
    transforms.Resize((_IMG_SIZE, _IMG_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

class ShellClassifier:
    """
    Loads the trained MobileNetV2 shell classifier and runs inference.

    Lazy-loads on first predict() call so importing is cheap.
    """

    def __init__(self):
        self._model: Optional[nn.Module] = None
        self._class_names: Optional[list[str]] = None
        self._device = torch.device("cpu")

    def _load(self):
        """Load model weights and class mapping from disk."""
        if not _MODEL_PATH.exists():
            raise FileNotFoundError(
                f"Shell classifier model not found: {_MODEL_PATH}\n"
                "Run: python -m backend.app.alpha.train_shell_classifier"
            )

        checkpoint = torch.load(_MODEL_PATH, map_location=self._device, weights_only=False)

        num_classes = checkpoint["num_classes"]
        self._class_names = checkpoint["class_names"]

        # Rebuild model architecture
        model = models.mobilenet_v2(weights=None)
        in_features = model.classifier[1].in_features
        model.classifier = nn.Sequential(
            nn.Dropout(p=0.3),
            nn.Linear(in_features, 256),
            nn.ReLU(),
            nn.Dropout(p=0.2),
            nn.Linear(256, num_classes),
        )

        model.load_state_dict(checkpoint["model_state_dict"])
        model.to(self._device)
        model.eval()
        self._model = model

        logger.info(
            "Shell classifier loaded: %d classes, model=%s",
            num_classes, _MODEL_PATH.name,
        )

    def predict_topk(self, image_path: str | Path, k: int = 3) -> list[tuple[str, float]]:
        """
        Return the top-k shell predictions for a crop image.

        The hybrid router uses these candidates to decide when a local shell
        prediction is strong enough and when it should ask Claude to repair it.
        """
        if self._model is None:
            self._load()

        img = Image.open(image_path).convert("RGB")
        tensor = _eval_transform(img).unsqueeze(0).to(self._device)

        with torch.no_grad():
            output = self._model(tensor)
            probs = torch.softmax(output, dim=1).squeeze(0)
            top_count = max(1, min(k, probs.numel()))
            confidences, indices = torch.topk(probs, top_count)

        predictions = [
            (self._class_names[idx.item()], conf.item())
            for conf, idx in zip(confidences, indices)
        ]
        logger.debug(
            "Shell top-%d from %s: %s",
            top_count,
            Path(image_path).name,
            [(name, round(conf, 3)) for name, conf in predictions],
        )
        return predictions

    def predict(self, image_path: str | Path) -> tuple[str, float]:
        """
        Predict shell class from a character crop image.

        Parameters
        ----------
        image_path : path to a character crop .jpg

        Returns
        -------
        (class_name, confidence) — e.g. ("triage", 0.97)
        """
        top = self.predict_topk(image_path, k=1)
        return top[0]


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

_default_classifier: Optional[ShellClassifier] = None


def predict_shell(image_path: str | Path) -> tuple[str, float]:
    """
    Convenience function — uses a module-level singleton.

    Returns (class_name, confidence).
    """
    global _default_classifier
    if _default_classifier is None:
        _default_classifier = ShellClassifier()
    return _default_classifier.predict(image_path)

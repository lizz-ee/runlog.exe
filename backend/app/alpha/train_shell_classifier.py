"""
Train a MobileNetV2 shell classifier for Marathon RunLog.

7-class image classifier: assassin, destroyer, recon, rook, thief, triage, vandal.
Uses heavy data augmentation + weighted sampling to handle class imbalance
(rook/destroyer have only 2 samples each).

Usage:
    python -m backend.app.alpha.train_shell_classifier
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from PIL import Image
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from torchvision import models, transforms

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "training_data" / "shells"
MODEL_DIR = SCRIPT_DIR / "models"
MODEL_PATH = MODEL_DIR / "shell_classifier.pth"
CLASSES_PATH = MODEL_DIR / "shell_classes.json"

# ---------------------------------------------------------------------------
# Hyper-parameters
# ---------------------------------------------------------------------------

IMG_SIZE = 224
BATCH_SIZE = 8
NUM_EPOCHS = 80
LEARNING_RATE = 1e-3       # For classifier head
LR_BACKBONE = 1e-5         # For backbone (fine-tuning)
WEIGHT_DECAY = 1e-4
UNFREEZE_BACKBONE_EPOCH = 20  # Unfreeze backbone after this many epochs


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

class ShellDataset(Dataset):
    """Simple image-folder dataset with per-sample transform."""

    def __init__(self, root: Path, transform=None):
        self.samples = []  # (path, class_idx)
        self.classes = sorted([
            d.name for d in root.iterdir() if d.is_dir()
        ])
        self.class_to_idx = {c: i for i, c in enumerate(self.classes)}
        self.transform = transform

        for cls_name in self.classes:
            cls_dir = root / cls_name
            for img_file in sorted(cls_dir.iterdir()):
                if img_file.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    self.samples.append((img_file, self.class_to_idx[cls_name]))

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        path, label = self.samples[idx]
        img = Image.open(path).convert("RGB")
        if self.transform:
            img = self.transform(img)
        return img, label


# ---------------------------------------------------------------------------
# Transforms
# ---------------------------------------------------------------------------

# Heavy augmentation for training — critical for 2-sample classes
train_transform = transforms.Compose([
    transforms.Resize((IMG_SIZE + 32, IMG_SIZE + 32)),
    transforms.RandomCrop(IMG_SIZE),
    transforms.RandomHorizontalFlip(p=0.5),
    transforms.RandomRotation(15),
    transforms.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.3, hue=0.1),
    transforms.RandomAffine(degrees=0, translate=(0.1, 0.1), scale=(0.85, 1.15)),
    transforms.RandomGrayscale(p=0.05),
    transforms.GaussianBlur(kernel_size=3, sigma=(0.1, 1.0)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
    transforms.RandomErasing(p=0.2, scale=(0.02, 0.15)),
])

eval_transform = transforms.Compose([
    transforms.Resize((IMG_SIZE, IMG_SIZE)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def build_model(num_classes: int) -> nn.Module:
    """MobileNetV2 with custom classifier head."""
    model = models.mobilenet_v2(weights=models.MobileNet_V2_Weights.IMAGENET1K_V1)

    # Freeze backbone initially
    for param in model.features.parameters():
        param.requires_grad = False

    # Replace classifier
    in_features = model.classifier[1].in_features
    model.classifier = nn.Sequential(
        nn.Dropout(p=0.3),
        nn.Linear(in_features, 256),
        nn.ReLU(),
        nn.Dropout(p=0.2),
        nn.Linear(256, num_classes),
    )

    return model


def unfreeze_backbone(model: nn.Module, lr_backbone: float, optimizer: optim.Optimizer):
    """Unfreeze the backbone and add its params to the optimizer."""
    for param in model.features.parameters():
        param.requires_grad = True

    # Add backbone params to optimizer with lower LR
    optimizer.add_param_group({
        "params": model.features.parameters(),
        "lr": lr_backbone,
    })
    print(f"  Backbone unfrozen (lr={lr_backbone})")


# ---------------------------------------------------------------------------
# Training loop
# ---------------------------------------------------------------------------

def train():
    print("=" * 60)
    print("Shell Classifier Training — MobileNetV2")
    print("=" * 60)

    # --- Dataset ---
    dataset = ShellDataset(DATA_DIR, transform=train_transform)
    eval_dataset = ShellDataset(DATA_DIR, transform=eval_transform)

    class_names = dataset.classes
    num_classes = len(class_names)

    print(f"\nClasses ({num_classes}): {class_names}")
    print(f"Total samples: {len(dataset)}")

    # Per-class counts
    class_counts = [0] * num_classes
    for _, label in dataset.samples:
        class_counts[label] += 1
    for i, name in enumerate(class_names):
        print(f"  {name}: {class_counts[i]}")

    # --- Weighted sampler (oversample minority classes) ---
    sample_weights = []
    for _, label in dataset.samples:
        sample_weights.append(1.0 / class_counts[label])
    sample_weights = torch.tensor(sample_weights, dtype=torch.float64)

    # Oversample so each epoch sees ~max_count * num_classes samples
    num_samples_per_epoch = max(class_counts) * num_classes
    sampler = WeightedRandomSampler(sample_weights, num_samples=num_samples_per_epoch, replacement=True)

    loader = DataLoader(dataset, batch_size=BATCH_SIZE, sampler=sampler, num_workers=0)
    eval_loader = DataLoader(eval_dataset, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    # --- Model ---
    model = build_model(num_classes)
    device = torch.device("cpu")
    model.to(device)

    # --- Loss with class weights (inverse frequency) ---
    class_weights = torch.tensor(
        [len(dataset) / (num_classes * c) for c in class_counts],
        dtype=torch.float32,
    ).to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights)

    # --- Optimizer (only classifier params initially) ---
    optimizer = optim.Adam(
        model.classifier.parameters(),
        lr=LEARNING_RATE,
        weight_decay=WEIGHT_DECAY,
    )

    # --- LR scheduler ---
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=NUM_EPOCHS, eta_min=1e-6)

    # --- Train ---
    print(f"\nTraining for {NUM_EPOCHS} epochs on {device}...")
    print(f"Samples per epoch: {num_samples_per_epoch}")
    print(f"Backbone unfreezes at epoch {UNFREEZE_BACKBONE_EPOCH}")
    print()

    best_acc = 0.0
    backbone_unfrozen = False

    for epoch in range(1, NUM_EPOCHS + 1):
        # Unfreeze backbone
        if epoch == UNFREEZE_BACKBONE_EPOCH and not backbone_unfrozen:
            unfreeze_backbone(model, LR_BACKBONE, optimizer)
            backbone_unfrozen = True

        model.train()
        running_loss = 0.0
        correct = 0
        total = 0

        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)

            optimizer.zero_grad()
            outputs = model(images)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()

            running_loss += loss.item() * images.size(0)
            _, predicted = outputs.max(1)
            total += labels.size(0)
            correct += predicted.eq(labels).sum().item()

        scheduler.step()

        epoch_loss = running_loss / total
        epoch_acc = 100.0 * correct / total

        if epoch % 10 == 0 or epoch <= 5 or epoch == NUM_EPOCHS:
            print(f"  Epoch {epoch:3d}/{NUM_EPOCHS}  loss={epoch_loss:.4f}  train_acc={epoch_acc:.1f}%")

        # Track best
        if epoch_acc > best_acc:
            best_acc = epoch_acc

    # --- Final evaluation (no augmentation) ---
    print(f"\n{'=' * 60}")
    print("Final Evaluation (no augmentation)")
    print("=" * 60)

    model.eval()
    per_class_correct = [0] * num_classes
    per_class_total = [0] * num_classes
    all_correct = 0
    all_total = 0

    with torch.no_grad():
        for images, labels in eval_loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)
            _, predicted = outputs.max(1)

            for i in range(labels.size(0)):
                label = labels[i].item()
                pred = predicted[i].item()
                per_class_total[label] += 1
                if pred == label:
                    per_class_correct[label] += 1
                    all_correct += 1
                all_total += 1

    overall_acc = 100.0 * all_correct / all_total if all_total > 0 else 0
    print(f"\nOverall accuracy: {all_correct}/{all_total} = {overall_acc:.1f}%\n")

    print("Per-class accuracy:")
    for i, name in enumerate(class_names):
        if per_class_total[i] > 0:
            acc = 100.0 * per_class_correct[i] / per_class_total[i]
            print(f"  {name:12s}: {per_class_correct[i]:2d}/{per_class_total[i]:2d} = {acc:.1f}%")
        else:
            print(f"  {name:12s}: no samples")

    # --- Confidence analysis ---
    print("\nConfidence analysis (per sample):")
    model.eval()
    misclassified = []
    with torch.no_grad():
        for path, label in eval_dataset.samples:
            img = Image.open(path).convert("RGB")
            tensor = eval_transform(img).unsqueeze(0).to(device)
            output = model(tensor)
            probs = torch.softmax(output, dim=1)
            conf, pred = probs.max(1)
            conf = conf.item()
            pred = pred.item()
            if pred != label:
                misclassified.append((
                    path.name,
                    class_names[label],
                    class_names[pred],
                    conf,
                ))

    if misclassified:
        print(f"\n  Misclassified ({len(misclassified)}):")
        for fname, true_cls, pred_cls, conf in misclassified:
            print(f"    {fname}: true={true_cls} pred={pred_cls} conf={conf:.3f}")
    else:
        print("  All samples correctly classified!")

    # --- Save ---
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    # Save model state dict
    torch.save({
        "model_state_dict": model.state_dict(),
        "num_classes": num_classes,
        "class_names": class_names,
    }, MODEL_PATH)
    print(f"\nModel saved: {MODEL_PATH}")

    # Save class mapping
    class_mapping = {str(i): name for i, name in enumerate(class_names)}
    with open(CLASSES_PATH, "w") as f:
        json.dump(class_mapping, f, indent=2)
    print(f"Classes saved: {CLASSES_PATH}")

    print(f"\nDone! Overall accuracy: {overall_acc:.1f}%")


if __name__ == "__main__":
    train()

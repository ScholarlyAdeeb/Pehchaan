"""
Train the document-type classifier (MobileNetV2, ImageNet-pretrained) on the
generated identity dataset: training/data_generated/<class>/<class>_NNNN.jpg
for Aadhaar, PAN, driving licence and passport.

The split is by person, with the same seed as the region detector, so the
same 60 people are held out of both models. Half of the training images are
turned into "photos" (card on a random background, tilted, skewed) so the
classifier does not depend on a flat, full-frame scan. Held-out accuracy is
reported on the cards as generated and on photo-style versions of them.

Usage (from backend/):
    .venv\\Scripts\\python training\\train.py [--epochs 8] [--out training/document_classifier.pth]
Outputs the weights and <out>_metrics.json (which also carries the class
list the app loads the model with).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset

HERE = Path(__file__).resolve().parent
sys.path.append(str(HERE.parent / "app" / "modules" / "classification"))
sys.path.append(str(HERE))
from model import DocumentClassifier  # noqa: E402
from train_region_detector import SEED, place_on_background  # noqa: E402

DATA = HERE / "data_generated"
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


def build_index(data_dir: Path):
    classes = sorted(d.name for d in data_dir.iterdir() if d.is_dir() and d.name != "annotations")
    samples = []
    for label, cls in enumerate(classes):
        for path in sorted((data_dir / cls).glob("*.jpg")):
            m = re.search(r"_(\d+)$", path.stem)
            samples.append((str(path), label, int(m.group(1)) if m else -1))
    return classes, samples


def split_by_person(samples, val_fraction: float):
    people = sorted({p for _, _, p in samples})
    random.Random(SEED).shuffle(people)
    val_people = set(people[: round(len(people) * val_fraction)])
    return [s for s in samples if s[2] not in val_people], [s for s in samples if s[2] in val_people]


class Cards(Dataset):
    """mode: "train" (random photo-style + colour changes on half the images),
    "clean" (as generated), "photo" (fixed photo-style distortion per card)."""

    def __init__(self, samples, mode: str):
        self.samples, self.mode = samples, mode

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, i):
        path, label, _ = self.samples[i]
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if self.mode != "clean":
            rng = np.random.default_rng() if self.mode == "train" else np.random.default_rng(SEED * 1000 + i)
            if self.mode == "photo" or rng.random() < 0.5:
                img, _ = place_on_background(img, [], rng)
            if self.mode == "train":
                img = np.clip(img.astype(np.float32) * rng.uniform(0.75, 1.25) + rng.uniform(-25, 25), 0, 255).astype(np.uint8)
                if rng.random() < 0.15:
                    img = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        # same preprocessing as the app: plain resize to 224x224, ImageNet normalisation
        img = cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2RGB), (224, 224), interpolation=cv2.INTER_AREA)
        x = (img.astype(np.float32) / 255.0 - MEAN) / STD
        return torch.from_numpy(x).permute(2, 0, 1), label


def evaluate(model, loader, device, num_classes):
    model.eval()
    confusion = [[0] * num_classes for _ in range(num_classes)]
    with torch.no_grad():
        for inputs, labels in loader:
            preds = model(inputs.to(device)).argmax(1).cpu()
            for t, p in zip(labels.tolist(), preds.tolist()):
                confusion[t][p] += 1
    correct = sum(confusion[i][i] for i in range(num_classes))
    return correct / max(sum(sum(r) for r in confusion), 1), confusion


def per_class_stats(classes, confusion):
    out = {}
    for i, name in enumerate(classes):
        support = sum(confusion[i])
        predicted = sum(confusion[r][i] for r in range(len(classes)))
        tp = confusion[i][i]
        out[name] = {"support": support, "precision": round(tp / predicted, 4) if predicted else 0.0,
                     "recall": round(tp / support, 4) if support else 0.0}
    return out


def train(epochs: int, out_path: Path, val_fraction: float, data_dir: Path, workers: int) -> None:
    torch.manual_seed(SEED)
    classes, samples = build_index(data_dir)
    train_s, val_s = split_by_person(samples, val_fraction)
    print(f"Classes: {classes} | total {len(samples)} | train {len(train_s)} | held-out {len(val_s)} (by person)")

    kw = dict(num_workers=workers, persistent_workers=workers > 0)
    train_loader = DataLoader(Cards(train_s, "train"), batch_size=32, shuffle=True, **kw)
    clean_loader = DataLoader(Cards(val_s, "clean"), batch_size=64, **kw)
    photo_loader = DataLoader(Cards(val_s, "photo"), batch_size=64, **kw)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = DocumentClassifier(num_classes=len(classes)).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    history, start = [], time.time()
    for epoch in range(1, epochs + 1):
        model.train()
        running, correct, total = 0.0, 0, 0
        for inputs, labels in train_loader:
            inputs, labels = inputs.to(device), labels.to(device)
            optimizer.zero_grad()
            outputs = model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            running += loss.item()
            correct += (outputs.argmax(1) == labels).sum().item()
            total += labels.size(0)
        scheduler.step()
        row = {"epoch": epoch, "train_loss": round(running / len(train_loader), 4),
               "train_accuracy": round(correct / total, 4),
               "val_accuracy": round(evaluate(model, clean_loader, device, len(classes))[0], 4),
               "val_accuracy_photo_style": round(evaluate(model, photo_loader, device, len(classes))[0], 4)}
        history.append(row)
        print(row, flush=True)

    clean_acc, clean_conf = evaluate(model, clean_loader, device, len(classes))
    photo_acc, photo_conf = evaluate(model, photo_loader, device, len(classes))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out_path)

    metrics = {
        "architecture": "MobileNetV2 (torchvision, ImageNet-1K pretrained), final Linear layer replaced",
        "classes": classes,
        "input_size": [224, 224],
        "optimizer": "Adam lr=0.001, cosine schedule",
        "epochs": epochs,
        "seed": SEED,
        "dataset": "training/data_generated (generated Aadhaar, PAN, driving licence and passport cards)",
        "split": "by person; the same held-out people as the region detector",
        "train_images": len(train_s),
        "validation_images": len(val_s),
        "validation_accuracy": round(clean_acc, 4),
        "validation_accuracy_photo_style": round(photo_acc, 4),
        "per_class": per_class_stats(classes, clean_conf),
        "per_class_photo_style": per_class_stats(classes, photo_conf),
        "confusion_matrix": {"rows_true_cols_pred": classes, "matrix": clean_conf},
        "confusion_matrix_photo_style": {"rows_true_cols_pred": classes, "matrix": photo_conf},
        "history": history,
        "training_seconds": round(time.time() - start, 1),
        "device": str(device),
    }
    metrics_path = out_path.with_name(out_path.stem + "_metrics.json")
    metrics_path.write_text(json.dumps(metrics, indent=2))
    print(f"Saved weights -> {out_path}\nSaved metrics -> {metrics_path}\n"
          f"Held-out accuracy: {clean_acc:.2%} as generated, {photo_acc:.2%} photo-style")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--val-fraction", type=float, default=0.2)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out", type=Path, default=HERE / "document_classifier.pth")
    args = parser.parse_args()
    train(args.epochs, args.out.resolve(), args.val_fraction, args.data, args.workers)

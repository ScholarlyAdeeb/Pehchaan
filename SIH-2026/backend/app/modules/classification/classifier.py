from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

_TORCH_AVAILABLE = False
try:
    import torch
    from torchvision import transforms
    _TORCH_AVAILABLE = True
except ImportError:
    torch = None  # type: ignore[assignment]
    transforms = None  # type: ignore[assignment]
    logger.warning("torch/torchvision not installed — document classifier will return 'unknown'")


class DocumentTypeClassifier:
    def __init__(self) -> None:
        self._model = None
        self._transform = None
        self._device = None
        self.classes = ["aadhar", "pan", "passport"]
        self._loaded = False

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return self._model is not None
        self._loaded = True

        if not _TORCH_AVAILABLE:
            return False

        try:
            import sys, os
            sys.path.append(os.path.dirname(__file__))
            from model import DocumentClassifier

            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model_path = Path(__file__).resolve().parent.parent.parent.parent / "training" / "document_classifier.pth"
            # The class list is written by training/train.py next to the weights.
            metrics_path = model_path.with_name(model_path.stem + "_metrics.json")
            if metrics_path.is_file():
                import json

                self.classes = list(json.loads(metrics_path.read_text(encoding="utf-8")).get("classes") or self.classes)
            self._model = DocumentClassifier(num_classes=len(self.classes))
            from app.modules.provenance import model_trusted

            if model_path.exists() and not model_trusted("document_classifier"):
                self._model = None
                return False
            if model_path.exists():
                # weights_only: a .pth file is a pickle; never execute code from it.
                self._model.load_state_dict(torch.load(model_path, map_location=self._device, weights_only=True))
                self._model.to(self._device).eval()  # inputs are moved to this device in predict
                logger.info("Loaded document classifier from %s", model_path)
            else:
                logger.warning("Model weights not found at %s; classifier disabled", model_path)
                self._model = None
                return False

            self._transform = transforms.Compose([
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
            ])
            return True
        except Exception as e:
            logger.error("Failed to load document classifier: %s", e)
            self._model = None
            return False

    def predict_proba(self, image_bytes: bytes) -> dict[str, float] | None:
        """Softmax probability per class, or None if the model is unavailable."""
        if not self._ensure_loaded():
            return None
        try:
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            tensor_image = self._transform(image).unsqueeze(0).to(self._device)
            with torch.no_grad():
                probs = torch.softmax(self._model(tensor_image), dim=1)[0].tolist()
            return {c: round(p, 4) for c, p in zip(self.classes, probs)}
        except Exception as e:
            logger.error("Classification error: %s", e)
            return None

    def predict(self, image_bytes: bytes) -> str:
        probs = self.predict_proba(image_bytes)
        if not probs:
            return "unknown"
        return max(probs, key=probs.get)


classifier = DocumentTypeClassifier()

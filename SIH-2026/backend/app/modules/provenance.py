"""
Provenance & model integrity.

* Every verdict records SHA-256 fingerprints of the model files and of the
  rule/scoring code that produced it, so an auditor can later prove exactly
  which AI version decided.
* Model files are checked against `backend/model_manifest.json` (committed to
  git) before they are loaded. A model whose hash does not match is refused:
  a swapped weights file could change verdicts, and PyTorch/ONNX files are
  code-adjacent (pickle / custom ops).

Regenerate the manifest after deliberately retraining a model:
    .venv\\Scripts\\python -m app.modules.provenance --write
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from functools import lru_cache
from pathlib import Path

from app.config import BACKEND_ROOT, get_settings

logger = logging.getLogger(__name__)

MANIFEST_PATH = BACKEND_ROOT / "model_manifest.json"

MODEL_FILES = {
    "document_classifier": BACKEND_ROOT / "training" / "document_classifier.pth",
    "face_recognizer_sface": BACKEND_ROOT / "models" / "face" / "face_recognition_sface_2021dec.onnx",
    "face_detector_yunet": BACKEND_ROOT / "models" / "face" / "face_detection_yunet_2023mar.onnx",
    "region_detector": BACKEND_ROOT / "models" / "localization" / "region_detector.pt",
}
RULE_FILES = [
    BACKEND_ROOT / "app" / "modules" / "validation" / "rules_engine.py",
    BACKEND_ROOT / "app" / "modules" / "risk" / "risk_engine.py",
    BACKEND_ROOT / "app" / "modules" / "tampering" / "tampering_engine.py",
    BACKEND_ROOT / "app" / "modules" / "face" / "verifier.py",
    BACKEND_ROOT / "app" / "modules" / "ocr" / "mrz_parser.py",
]


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@lru_cache
def _manifest() -> dict[str, str]:
    if not MANIFEST_PATH.is_file():
        return {}
    return json.loads(MANIFEST_PATH.read_text()).get("models", {})


@lru_cache
def model_hashes() -> dict[str, str | None]:
    return {name: sha256_file(path) for name, path in MODEL_FILES.items()}


def model_trusted(name: str) -> bool:
    """True if the model file matches the manifest (or no manifest entry exists yet)."""
    actual = model_hashes().get(name)
    expected = _manifest().get(name)
    if actual is None:
        return False
    if expected is None:
        logger.warning("No manifest entry for %s; loading unverified (run provenance --write)", name)
        return True
    if actual != expected:
        logger.error("INTEGRITY FAILURE: %s hash %s does not match manifest %s — refusing to load",
                     name, actual[:12], expected[:12])
        return False
    return True


def integrity_report() -> dict[str, str]:
    report = {}
    for name in MODEL_FILES:
        actual, expected = model_hashes().get(name), _manifest().get(name)
        report[name] = ("missing" if actual is None else "unlisted" if expected is None
                        else "verified" if actual == expected else "MISMATCH")
    return report


@lru_cache
def rules_fingerprint() -> str:
    settings = get_settings()
    h = hashlib.sha256()
    for f in RULE_FILES:
        h.update((sha256_file(f) or "").encode())
    config = {k: getattr(settings, k) for k in dir(settings)
              if k.startswith(("WEIGHT_", "RISK_", "ELA_", "COPY_MOVE", "RECORDS_", "CLASSIFIER_"))}
    h.update(json.dumps(config, sort_keys=True).encode())
    return h.hexdigest()


def provenance() -> dict:
    models = {k: v for k, v in model_hashes().items() if v}
    combined = hashlib.sha256(
        (json.dumps(models, sort_keys=True) + rules_fingerprint()).encode()
    ).hexdigest()
    return {"models": models, "rules": rules_fingerprint(), "combined": combined}


def write_manifest() -> None:
    data = {"models": {k: v for k, v in model_hashes().items() if v}}
    MANIFEST_PATH.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Wrote {MANIFEST_PATH}")
    for k, v in data["models"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    if "--write" in sys.argv:
        write_manifest()
    else:
        print(json.dumps({"integrity": integrity_report(), "provenance": provenance()}, indent=2))

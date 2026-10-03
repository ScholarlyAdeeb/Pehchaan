"""Assembles the folder to upload to a Hugging Face Space.

    python deploy/huggingface/build_space.py [output folder]

Copies the engine code, the model files, the reference data and the
issued-documents database (none of the last three are in git) next to this
folder's Space files (README, space_app.py, requirements.txt, packages.txt).
TLS certificates, .env files, uploads and
training data are left out on purpose.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1] / "backend"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE.parents[2] / "pehchaan-engine-space"

FILES = [
    "run_engine.py",
    "model_manifest.json",
    "models/face/face_detection_yunet_2023mar.onnx",
    "models/face/face_recognition_sface_2021dec.onnx",
    "models/localization/region_detector.pt",
    "training/document_classifier.pth",
    "training/document_classifier_metrics.json",
    "training/region_detector_metrics.json",
    "training/region_ocr_eval.json",
    "data/registry/issued_documents.sqlite",
]
DIRS = ["app", "data/reference"]
LARGE = ["*.pt", "*.pth", "*.onnx", "*.sqlite"]          # stored with Git LFS on the Hub


def main() -> int:
    missing = [f for f in FILES if not (BACKEND / f).is_file()]
    if missing:
        print("Missing files (train or build them first):\n  " + "\n  ".join(missing))
        return 1
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for d in DIRS:
        shutil.copytree(BACKEND / d, OUT / d, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for f in FILES:
        (OUT / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BACKEND / f, OUT / f)
    for f in ("README.md", "space_app.py", "requirements.txt", "packages.txt"):
        shutil.copy2(HERE / f, OUT / f)
    (OUT / ".gitattributes").write_text(
        "".join(f"{p} filter=lfs diff=lfs merge=lfs -text\n" for p in LARGE), encoding="utf-8")
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"Space folder ready: {OUT}  ({size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

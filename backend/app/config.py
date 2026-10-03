"""
Centralized, environment-driven configuration.

Everything that might change between a dev laptop, a CI runner, and a demo
server lives here — never hardcode paths/thresholds inside a module.
"""
from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_ROOT / ".env")


def _generate_secret(length: int = 32) -> str:
    """Generate a cryptographically strong random secret."""
    return secrets.token_urlsafe(length)


def _get_tesseract_cmd() -> str | None:
    cmd = os.getenv("TESSERACT_CMD")
    if cmd and os.path.exists(cmd):
        return cmd
    if os.name == "nt":
        default_win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        if os.path.exists(default_win_path):
            return default_win_path
    return cmd


class Settings:
    # --- General ---
    APP_NAME: str = "AI Document Screening System"
    APP_VERSION: str = "0.1.0"
    ENV: str = os.getenv("APP_ENV", "development")

    # --- CORS ---
    ALLOWED_ORIGINS: list[str] = os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")

    # --- Storage ---
    UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR") or BACKEND_ROOT / "uploads")
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "12"))

    # --- OCR ---
    TESSERACT_CMD: str | None = _get_tesseract_cmd()

    # --- Document Localization (Faster R-CNN) ---
    # Trained by training/train_region_detector.py; used automatically when the file is present.
    LOCALIZATION_MODEL_PATH: str | None = os.getenv("LOCALIZATION_MODEL_PATH") or str(
        BACKEND_ROOT / "models" / "localization" / "region_detector.pt")
    LOCALIZATION_CONFIDENCE: float = float(os.getenv("LOCALIZATION_CONFIDENCE", "0.5"))
    LOCALIZATION_DEVICE: str = os.getenv("LOCALIZATION_DEVICE", "auto")  # auto = GPU when available, else CPU
    LOCALIZATION_ENABLED: bool = os.getenv("LOCALIZATION_ENABLED", "true").lower() == "true"

    # --- Tampering detection thresholds (tunable without code changes) ---
    ELA_JPEG_QUALITY: int = int(os.getenv("ELA_JPEG_QUALITY", "90"))
    ELA_SUSPICION_THRESHOLD: float = float(os.getenv("ELA_SUSPICION_THRESHOLD", "18.0"))
    COPY_MOVE_MATCH_THRESHOLD: int = int(os.getenv("COPY_MOVE_MATCH_THRESHOLD", "100"))

    # --- Records database (prior screenings, used for cross-checks) ---
    # Same Postgres the web app writes to. Without it the cross-check falls
    # back to scans held in this process.
    DATABASE_URL: str | None = os.getenv("NEON_DATABASE_URL") or os.getenv("DATABASE_URL")
    RECORDS_NAME_MATCH_THRESHOLD: float = float(os.getenv("RECORDS_NAME_MATCH_THRESHOLD", "0.75"))

    # --- Security ---
    # Shared with the web server (Pehchaan/.env); every /api call must carry it.
    ENGINE_API_KEY: str | None = os.getenv("ENGINE_API_KEY")
    # Auto-generated if not provided; used for JWT/session tokens and audit signatures.
    AUTH_SECRET_KEY: str = os.getenv("AUTH_SECRET_KEY") or secrets.token_urlsafe(32)
    AUDIT_SIGNING_KEY: str = os.getenv("AUDIT_SIGNING_KEY") or secrets.token_urlsafe(32)
    # Keyed hash for document numbers, so the database never needs the number itself.
    PII_HASH_KEY: str | None = os.getenv("PII_HASH_KEY")
    # One-time admin bootstrap code (write once, then delete).
    ADMIN_BOOTSTRAP_CODE: str | None = os.getenv("ADMIN_BOOTSTRAP_CODE")
    MAX_IMAGE_PIXELS: int = int(os.getenv("MAX_IMAGE_PIXELS", "60000000"))

    # --- Checkpoint access control ---
    # Comma-separated list of checkpoint IDs this engine instance is allowed to serve.
    # Empty = allow all. Used when multiple engine instances serve different border posts.
    ENGINE_CHECKPOINT_IDS: list[str] = os.getenv("ENGINE_CHECKPOINT_IDS", "").split(",") if os.getenv("ENGINE_CHECKPOINT_IDS") else []

    # --- Auto-detection ---
    CLASSIFIER_MIN_CONFIDENCE: float = float(os.getenv("CLASSIFIER_MIN_CONFIDENCE", "0.60"))

    # --- Risk engine weights (renormalised over the signals that actually ran) ---
    WEIGHT_VALIDATION: float = float(os.getenv("WEIGHT_VALIDATION", "0.30"))
    WEIGHT_TAMPERING: float = float(os.getenv("WEIGHT_TAMPERING", "0.35"))
    WEIGHT_FACE: float = float(os.getenv("WEIGHT_FACE", "0.20"))
    WEIGHT_RECORDS: float = float(os.getenv("WEIGHT_RECORDS", "0.15"))

    RISK_CLEAR_MAX: int = int(os.getenv("RISK_CLEAR_MAX", "30"))
    RISK_REVIEW_MAX: int = int(os.getenv("RISK_REVIEW_MAX", "65"))

    # --- Retention & Incident ---
    SCAN_RETENTION_DAYS: int = int(os.getenv("SCAN_RETENTION_DAYS", "90"))
    INCIDENT_REPORT_WEBHOOK: str | None = os.getenv("INCIDENT_REPORT_WEBHOOK")

    # --- Timestamping ---
    TIMESTAMP_AUTHORITY_URL: str | None = os.getenv("TIMESTAMP_AUTHORITY_URL")
    TIMESTAMP_AUTHORITY_TOKEN: str | None = os.getenv("TIMESTAMP_AUTHORITY_TOKEN")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return settings
"""
Module 0 — Document Region Localization (Faster R-CNN).

Upstream localization stage that detects semantically meaningful regions
of identity documents before OCR, MRZ parsing, face detection, and
tampering analysis.
"""
from __future__ import annotations

from .detector import DocumentRegionDetector, RegionDetectionResult, DocumentRegion
from .synthetic_generator import SyntheticDocumentGenerator

__all__ = [
    "DocumentRegionDetector",
    "RegionDetectionResult", 
    "DocumentRegion",
    "SyntheticDocumentGenerator",
]
"""
EXIF / file-metadata forensics.

Scanned or photographed ID documents carry metadata that is a useful
tamper signal on its own: presence of an image-editing tool's signature
(Photoshop, GIMP, Pixelmator, remove-bg SaaS tools...), inconsistent or
missing capture timestamps, or a `Software` tag that doesn't match a
camera/scanner at all.

This is intentionally a *supporting* signal, not a standalone verdict —
metadata can be stripped or absent for entirely innocent reasons (e.g. the
officer's scanning app strips EXIF for privacy), so we surface it as
evidence rather than an automatic fail.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image
from PIL.ExifTags import TAGS

_EDITOR_SIGNATURES = [
    "photoshop", "gimp", "pixelmator", "affinity", "canva", "paint.net",
    "lightroom", "snapseed", "picsart", "remove.bg", "facetune",
]


@dataclass
class MetadataResult:
    has_exif: bool
    software_tag: str | None
    editor_signature_found: bool
    flags: list[str] = field(default_factory=list)


def analyze_metadata(image_bytes: bytes) -> MetadataResult:
    flags: list[str] = []
    img = Image.open(io.BytesIO(image_bytes))
    exif_raw = img.getexif()

    if not exif_raw:
        return MetadataResult(
            has_exif=False,
            software_tag=None,
            editor_signature_found=False,
            flags=["No EXIF metadata present (common for scans/screenshots; not conclusive on its own)."],
        )

    exif = {TAGS.get(k, k): v for k, v in exif_raw.items()}
    software = str(exif.get("Software", "")) or None

    editor_found = False
    if software:
        lowered = software.lower()
        editor_found = any(sig in lowered for sig in _EDITOR_SIGNATURES)
        if editor_found:
            flags.append(f"Image was processed with editing software: '{software}'.")

    if "DateTimeOriginal" in exif and "DateTime" in exif:
        if exif["DateTimeOriginal"] != exif["DateTime"]:
            flags.append("Capture timestamp and modification timestamp differ — image was saved after capture.")

    return MetadataResult(
        has_exif=True,
        software_tag=software,
        editor_signature_found=editor_found,
        flags=flags,
    )

"""
Personal-data minimisation for document numbers (DPDP Act 2023 principle of
storing only what is needed).

The database keeps a *keyed* hash of each document number instead of the
number: equal numbers give equal hashes, so earlier screenings can still be
found, but the hash is useless without PII_HASH_KEY (a plain SHA-256 of a
10-character PAN could be brute-forced in minutes). Screens show a masked
form like ••••••2872.
"""
from __future__ import annotations

import hashlib
import hmac
import re

from app.config import get_settings


def normalize(number: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (number or "").upper())


def hash_document_number(number: str | None) -> str | None:
    norm = normalize(number)
    key = get_settings().PII_HASH_KEY
    if len(norm) < 5 or not key:
        return None
    return hmac.new(key.encode(), norm.encode(), hashlib.sha256).hexdigest()


def mask_document_number(number: str | None) -> str | None:
    norm = normalize(number)
    if not norm:
        return None
    visible = 4 if len(norm) > 6 else 2
    return "•" * (len(norm) - visible) + norm[-visible:]

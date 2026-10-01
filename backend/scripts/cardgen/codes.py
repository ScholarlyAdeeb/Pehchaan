"""Real machine-readable codes for the card holders.

``cv2.QRCodeEncoder`` is part of the OpenCV build already in the venv, so the
dataset gets genuinely scannable QR codes with no new dependency.

Payloads
--------
Real cards do not all encode the same thing, so the payload is per card type:

* **PAN** - the QR on a PAN card carries the PAN number itself.
* **Aadhaar** - the UIDAI QR carries a payload describing the holder.  A real
  one is an opaque reference token rather than readable fields, so a compact
  structured payload is used: it is closer to the real thing *and* it stays
  inside the size this build can actually read (see below).

Readable size
-------------
``cv2.QRCodeDetector`` in this build cannot read a QR of version 8 or above
(49x49 or 53x53 modules) - a 161-character payload encodes to version 9 and
will not decode, while the same content at version 7 does.  The encoder's
correction level and version are not reachable from Python
(``QRCodeEncoder.encode`` takes at most two arguments), so the only lever is
payload length.

:data:`MAX_MODULES` therefore caps the generated matrix, and
:func:`qr_matrix` refuses to emit anything larger.  Without that a longer
payload would look like a perfectly good QR code on the card while being
unreadable - exactly the kind of defect that is invisible until someone tries
to scan it.

Not implemented
---------------
The Indian passport's observations page carries a **PDF417** 2D barcode, and
OpenCV has no PDF417 encoder.  Rather than draw something barcode-shaped that
scans to nothing, that holder is left as the labelled placeholder it already is.
See ``photo_regions.REGIONS`` and the note in ``generate.py``.
"""

from __future__ import annotations

import json

import cv2
import numpy as np

#: QR codes need a quiet zone (a blank margin) to be readable, in modules.
QUIET_ZONE = 4

#: Largest matrix this build's detector is known to read: version 7 is 45x45.
MAX_MODULES = 45


def aadhaar_payload(row: dict) -> str:
    """UIDAI-style QR payload for an Aadhaar row.

    Deliberately excludes the address - see the module docstring.  With the
    address the payload reaches version 9 and the resulting code, while looking
    entirely normal, does not decode.
    """
    return json.dumps(
        {
            "uid": row.get("Aadhaar_Number", ""),
            "name": row.get("Aadhaar_Name", ""),
            "dob": row.get("Aadhaar_DOB", ""),
            "gender": row.get("Aadhaar_Gender", ""),
        },
        separators=(",", ":"),
    )


def pan_payload(row: dict) -> str:
    """PAN card QR payload: the PAN number itself."""
    return row.get("PAN_Number", "")


def qr_matrix(payload: str) -> np.ndarray | None:
    """Encode ``payload`` as a QR module matrix, or ``None`` if it will not do.

    Returns a ``uint8`` array of 0/255 at one pixel per module, quiet zone
    already applied.  ``None`` is returned when the payload is empty, will not
    encode, or would need a matrix larger than this build's detector can read -
    a refusal rather than an unreadable code.
    """
    if not payload or not str(payload).strip():
        return None
    try:
        raw = cv2.QRCodeEncoder.create().encode(str(payload))
    except cv2.error:
        return None
    if raw is None or raw.size == 0:
        return None
    bits = (raw > 127).astype(np.uint8) * 255
    if bits.shape[0] > MAX_MODULES or bits.shape[1] > MAX_MODULES:
        # too dense to be read back; see the module docstring
        return None
    quiet = np.full(
        (bits.shape[0] + 2 * QUIET_ZONE, bits.shape[1] + 2 * QUIET_ZONE),
        255, dtype=np.uint8,
    )
    quiet[QUIET_ZONE:QUIET_ZONE + bits.shape[0],
          QUIET_ZONE:QUIET_ZONE + bits.shape[1]] = bits
    return quiet


def draw_qr(
    canvas: np.ndarray,
    box: tuple[int, int, int, int],
    payload: str,
    *,
    border: int = 0,
    border_color: tuple[int, int, int] = (200, 200, 200),
) -> bool:
    """Render ``payload`` centred in ``box`` on ``canvas``.  Returns success.

    The code is scaled with nearest-neighbour so module edges stay crisp, and
    is never enlarged past its natural module size, so it stays scannable.
    """
    matrix = qr_matrix(payload)
    if matrix is None:
        return False
    x, y, w, h = box
    if w <= 8 or h <= 8:
        return False

    mh, mw = matrix.shape
    scale = max(1, min((w - 2 * border) // mw, (h - 2 * border) // mh))
    # do not blow a small code up so far that it looks printed rather than coded
    scale = min(scale, 12)
    big = cv2.resize(matrix, (mw * scale, mh * scale), interpolation=cv2.INTER_NEAREST)

    bh, bw = big.shape
    if bh > h - 2 * border or bw > w - 2 * border:
        return False
    ox = x + (w - bw) // 2
    oy = y + (h - bh) // 2

    if border:
        cv2.rectangle(
            canvas, (x, y), (x + w - 1, y + h - 1), border_color, border
        )
    roi = canvas[oy:oy + bh, ox:ox + bw]
    if roi.shape[:2] != big.shape[:2]:
        return False
    roi[:] = cv2.cvtColor(big, cv2.COLOR_GRAY2BGR)
    return True


def payload_for(document_type: str, row: dict) -> str:
    """QR payload for a card type, or ``""`` if that card has no QR."""
    if document_type in ("aadhaar", "aadhar"):
        return aadhaar_payload(row)
    if document_type == "pan":
        return pan_payload(row)
    return ""

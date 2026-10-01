"""Small shared helpers for turning uploaded bytes into the array formats
each CV module expects, and back into a base64 payload the API can return."""
from __future__ import annotations

import base64

import cv2
import numpy as np


def bytes_to_bgr(image_bytes: bytes) -> np.ndarray:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("Could not decode image — unsupported format or corrupt file.")
    return image


def png_bytes_to_data_url(png_bytes: bytes) -> str:
    encoded = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def bgr_to_data_url(image: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("Could not encode image to PNG.")
    return png_bytes_to_data_url(buf.tobytes())

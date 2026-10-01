"""
Auto-label text-field boxes for the generated ID dataset.

The generator's annotations box only the photo / QR / barcode, but the
region detector exists to find *text fields* so OCR can read each field on
its own. Every annotation also holds the exact text printed on the card, so
we OCR each image once with Tesseract, find where each known value was
printed, and save that as a box ("weak" labels: only confident matches are
kept, fields that cannot be located are simply left out).

Usage (from backend/):
    .venv\\Scripts\\python training\\autolabel_regions.py [--workers 8]
Output: training/data_generated/regions_autolabel.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE / "data_generated"
sys.path.insert(0, str(HERE.parent))

# ground-truth key -> detector class (REGION_CLASSES in app/modules/localization/detector.py)
FIELD_CLASSES = {
    "aadhar": {"Aadhaar_Name": "name", "Aadhaar_DOB": "date_of_birth", "Aadhaar_Number": "document_number",
               "Aadhaar_Address": "address"},
    "pan": {"PAN_Name": "name", "PAN_Father_Name": "guardian_name", "PAN_DOB": "date_of_birth",
            "PAN_Number": "document_number"},
    "driving_license": {"Name": "name", "S_D_W": "guardian_name", "DOB": "date_of_birth", "DL_Number": "document_number",
                        "Date_Of_Issue": "date_of_issue", "Validity_NT": "date_of_expiry", "Address": "address"},
    "passport": {"Passport_Surname": "surname", "Passport_Given_Name": "name", "Passport_DOB": "date_of_birth",
                 "Passport_Number": "document_number", "Passport_Date_Of_Issue": "date_of_issue",
                 "Passport_Date_Of_Expiry": "date_of_expiry", "Passport_Place_Of_Birth": "place_of_birth",
                 "Passport_Father_Name": "guardian_name", "Passport_Address": "address",
                 "Passport_MRZ_Line_1": "mrz", "Passport_MRZ_Line_2": "mrz"},
}
# annotation region kind -> detector class (ghost photos are a security feature, not the portrait)
KIND_CLASSES = {"photo": "photo", "qr": "qr_code", "barcode": "barcode"}

MIN_RATIO = 0.82
MIN_RATIO_MRZ = 0.72


def norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9<]", "", s.upper())


def _tokens(image, scale: float, psm: int):
    import pytesseract

    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, config=f"--oem 3 --psm {psm}")
    toks = []
    for i, t in enumerate(data["text"]):
        t = t.strip()
        if not t or float(data["conf"][i]) < 0:
            continue
        x, y, bw, bh = (int(round(v / scale)) for v in (data["left"][i], data["top"][i], data["width"][i], data["height"][i]))
        toks.append({"t": t, "n": norm(t), "box": (x, y, x + bw, y + bh)})
    # sparse mode loses line order; rebuild reading order (top-to-bottom, left-to-right)
    toks.sort(key=lambda k: (round((k["box"][1] + k["box"][3]) / 2 / 12), k["box"][0]))
    return toks


def ocr_passes(path: Path):
    """Several OCR views of the card. Colour at native size reads these
    patterned backgrounds best; greyscale and an enlarged copy catch what it
    misses. Boxes are always returned in original-image pixels."""
    import cv2
    from app.modules.ocr.engine import _configure_tesseract

    _configure_tesseract()
    img = cv2.imread(str(path))
    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    passes = [_tokens(rgb, 1.0, 11), _tokens(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 1.0, 11)]
    if max(h, w) < 1400:
        s = 1400 / max(h, w)
        passes.append(_tokens(cv2.resize(rgb, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC), s, 11))
    return passes, (w, h)


def union(boxes):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def locate(value: str, passes, is_mrz: bool, max_span: int = 14):
    """Best match of ``value`` across all OCR passes, or None."""
    best = (0.0, None)
    for toks in passes:
        r, box = _locate_in(value, toks, is_mrz, max_span)
        if box and r > best[0]:
            best = (r, box)
    return best[1]


def _locate_in(value: str, toks, is_mrz: bool, max_span: int):
    target = norm(value)
    if len(target) < 3:
        return 0.0, None
    best = (0.0, None)
    n = len(toks)
    for i in range(n):
        if not toks[i]["n"]:
            continue
        joined = ""
        for j in range(i, min(n, i + max_span)):
            joined += toks[j]["n"]
            if len(joined) > len(target) * 1.4 + 4:
                break
            r = SequenceMatcher(None, joined, target).ratio()
            if r > best[0]:
                span = [t["box"] for t in toks[i:j + 1]]
                # a real field is compact: reject matches scattered across the card
                hgt = max(b[3] for b in span) - min(b[1] for b in span)
                line_h = max(b[3] - b[1] for b in span)
                if hgt <= line_h * (6 if len(target) > 25 and not is_mrz else 2.6):
                    best = (r, union(span))
    return best if best[0] >= (MIN_RATIO_MRZ if is_mrz else MIN_RATIO) else (0.0, None)


def label_one(job):
    doc_type, img_path, ann_path = job
    ann = json.loads(Path(ann_path).read_text(encoding="utf-8"))
    passes, (w, h) = ocr_passes(Path(img_path))
    boxes, missed = [], []
    for key, cls in FIELD_CLASSES[doc_type].items():
        value = str(ann["fields"].get(key) or "").strip()
        if not value:
            continue
        b = locate(value, passes, is_mrz=(cls == "mrz"), max_span=40 if cls in ("address", "mrz") else 14)
        if b:
            pad = 3
            boxes.append({"class": cls, "field": key,
                          "box": [max(0, b[0] - pad), max(0, b[1] - pad), min(w, b[2] + pad), min(h, b[3] + pad)]})
        else:
            missed.append(key)
    for r in ann["regions"]:
        cls = KIND_CLASSES.get(r["kind"])
        if cls:
            bb = r["bbox"]
            boxes.append({"class": cls, "field": r["name"], "box": [bb["x"], bb["y"], bb["x"] + bb["w"], bb["y"] + bb["h"]]})
    return {"image": str(Path(img_path).relative_to(ROOT)).replace("\\", "/"), "doc_type": doc_type,
            "person": ann.get("serial_number"), "size": [w, h], "boxes": boxes, "missed": missed}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    jobs = []
    for doc_type in FIELD_CLASSES:
        for ann in sorted((ROOT / "annotations" / doc_type).glob("*.json")):
            img = ROOT / doc_type / (ann.stem + ".jpg")
            if img.is_file():
                jobs.append((doc_type, str(img), str(ann)))
    if args.limit:
        jobs = [j for t in FIELD_CLASSES for j in [x for x in jobs if x[0] == t][: args.limit]]
    with ProcessPoolExecutor(args.workers) as pool:
        results = list(pool.map(label_one, jobs, chunksize=4))

    found, total = defaultdict(Counter), defaultdict(Counter)
    for r in results:
        for key in FIELD_CLASSES[r["doc_type"]]:
            total[r["doc_type"]][key] += 1
        for b in r["boxes"]:
            if b["field"] in FIELD_CLASSES[r["doc_type"]]:
                found[r["doc_type"]][b["field"]] += 1
    coverage = {t: {k: f"{found[t][k]}/{total[t][k]}" for k in total[t]} for t in total}
    out = {"images": results, "coverage": coverage,
           "method": "Tesseract psm 11 word boxes matched to ground-truth values (SequenceMatcher >= 0.82, MRZ >= 0.72)"}
    path = ROOT / "regions_autolabel.json"
    path.write_text(json.dumps(out, indent=1))
    print(json.dumps(coverage, indent=1))
    print(f"wrote {path} ({len(results)} images)")


if __name__ == "__main__":
    main()

"""
Measure what the region detector adds to field extraction.

For every card of the held-out people (the 60 never seen in training) the
fields are extracted twice: from the full-page OCR alone, and with region
readings merged in. Both are compared with the generator's ground truth.

Usage (from backend/):
    .venv\Scripts\python training\eval_region_ocr.py [--device cuda] [--workers 6]
Output: training/region_ocr_eval.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
DATA = HERE / "data_generated"
MODEL = HERE.parent / "models" / "localization" / "region_detector.pt"

# ground-truth key -> (extracted field key, kind)
TRUTH = {
    "aadhar": {"Aadhaar_Name": ("name", "text"), "Aadhaar_DOB": ("date_of_birth", "date"),
               "Aadhaar_Number": ("id_number", "text"), "Aadhaar_Gender": ("gender", "gender")},
    "pan": {"PAN_Number": ("id_number", "text"), "PAN_Name": ("name", "text"),
            "PAN_Father_Name": ("father_name", "text"), "PAN_DOB": ("date_of_birth", "date")},
    "driving_license": {"DL_Number": ("license_number", "text"), "Name": ("name", "text"),
                        "S_D_W": ("guardian_name", "text"), "DOB": ("date_of_birth", "date"),
                        "Date_Of_Issue": ("issue_date", "date"), "Validity_NT": ("valid_till", "date")},
    "passport": {"Passport_Number": ("passport_number_visual", "text"), "Passport_Surname": ("surname", "text"),
                 "Passport_Given_Name": ("given_name", "text"), "Passport_DOB": ("date_of_birth", "date"),
                 "Passport_Date_Of_Issue": ("issue_date", "date"), "Passport_Date_Of_Expiry": ("expiry_date", "date"),
                 "Passport_Place_Of_Birth": ("place_of_birth", "text"), "Passport_Father_Name": ("father_name", "text"),
                 "Passport_Country_Code": ("nationality", "text"), "Passport_Sex": ("gender", "gender")},
}


def norm(value, kind: str) -> str:
    s = str(value or "")
    if kind == "date":
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(s.strip(), fmt).date().isoformat()
            except ValueError:
                pass
        return s
    if kind == "gender":
        return s.strip().upper()[:1]
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="people to evaluate (0 = all held-out)")
    args = ap.parse_args()

    import cv2
    import torch
    from app.modules.localization.detector import create_detector
    from app.modules.ocr.engine import run_ocr
    from app.modules.ocr.field_extractors import extract_fields, extract_fields_from_readings
    from app.modules.ocr.region_fields import merge_region_fields, read_regions

    people = torch.load(MODEL, map_location="cpu", weights_only=True)["val_people"]
    if args.limit:
        people = people[: args.limit]
    detector = create_detector(MODEL, 0.5, args.device if torch.cuda.is_available() else "cpu")
    jobs = [(doc, p) for p in people for doc in TRUTH]

    # the detector is not thread-safe: detect serially, OCR in parallel
    detections = {}
    for doc, p in jobs:
        img = cv2.imread(str(DATA / doc / f"{doc}_{p:04d}.jpg"))
        detections[(doc, p)] = detector.detect(img, doc).to_dict()

    def one(job):
        doc, p = job
        ann = json.loads((DATA / "annotations" / doc / f"{doc}_{p:04d}.json").read_text(encoding="utf-8"))
        img = cv2.imread(str(DATA / doc / f"{doc}_{p:04d}.jpg"))
        ocr = run_ocr(img, doc)
        page = extract_fields_from_readings(doc, ocr.raw_text, ocr.light_text)
        reads = read_regions(img, detections[job])
        merged, sources = merge_region_fields(doc, page, reads)
        rows = []
        for gt_key, (key, kind) in TRUTH[doc].items():
            truth = norm(ann["fields"].get(gt_key), kind)
            if truth:
                rows.append({"doc": doc, "person": p, "field": key, "truth": truth,
                             "page": norm(page.get(key), kind), "merged": norm(merged.get(key), kind),
                             "source": sources.get(key, "page")})
        return rows

    with ThreadPoolExecutor(args.workers) as pool:
        rows = [r for rs in pool.map(one, jobs) for r in rs]

    table = defaultdict(lambda: [0, 0, 0])   # (doc, field) -> [n, page correct, merged correct]
    for r in rows:
        t = table[(r["doc"], r["field"])]
        t[0] += 1; t[1] += r["page"] == r["truth"]; t[2] += r["merged"] == r["truth"]
    per_field = {f"{d}.{f}": {"n": n, "page_only": round(a / n, 4), "with_regions": round(b / n, 4)}
                 for (d, f), (n, a, b) in sorted(table.items())}
    per_doc = {}
    for d in TRUTH:
        sel = [v for (dd, _), v in table.items() if dd == d]
        n = sum(v[0] for v in sel)
        per_doc[d] = {"fields": n, "page_only": round(sum(v[1] for v in sel) / n, 4),
                      "with_regions": round(sum(v[2] for v in sel) / n, 4)}
    n = len(rows)
    worse = [r for r in rows if r["page"] == r["truth"] and r["merged"] != r["truth"]]
    out = {"held_out_people": len(people), "cards": len(jobs), "fields_checked": n,
           "page_only": round(sum(r["page"] == r["truth"] for r in rows) / n, 4),
           "with_regions": round(sum(r["merged"] == r["truth"] for r in rows) / n, 4),
           "made_worse": len(worse), "per_document": per_doc, "per_field": per_field,
           "still_wrong": [r for r in rows if r["merged"] != r["truth"]][:60], "made_worse_rows": worse}
    (HERE / "region_ocr_eval.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: out[k] for k in ("cards", "fields_checked", "page_only", "with_regions", "made_worse", "per_document")}, indent=1))
    print(f"{'field':38}{'n':>5}{'page':>8}{'+regions':>10}")
    for k, v in per_field.items():
        print(f"{k:38}{v['n']:>5}{v['page_only']:>8.3f}{v['with_regions']:>10.3f}")


if __name__ == "__main__":
    main()

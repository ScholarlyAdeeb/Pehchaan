"""
Build demo images for the screening pipeline from one passport of the
generated identity dataset (training/data_generated).

  demo_passport_genuine.jpg   the passport as issued                      -> expect CLEAR
                              (valid MRZ, agrees with the issued-documents database)
  demo_passport_tampered.jpg  expiry year altered in the MRZ               -> check digits fail, HIGH RISK
  demo_passport_clone.jpg     same passport number, another holder's name  -> conflicts with the issuing
                                                                              records, HIGH RISK
  demo_aadhaar_name_swap.jpg  Aadhaar with the holder's name re-printed     -> the number belongs to someone
                                                                              else in the issuing records
  demo_dl_photo_swap.jpg      driving licence with another person's photo  -> face match fails against the
  demo_dl_live_holder.jpg     ... and the real holder's face, to upload       holder's live photo; the pasted
                              as the live photo                               photo re-compresses differently
  demo_pan_dob_altered.jpg    PAN with the birth year moved back 8 years    -> date of birth disagrees with
                                                                              the issuing records

The forgeries are made the way a forger would: the field is painted over and
re-printed in place. The exact boxes come from the generator's annotations.

Usage (from backend/):  .venv\\Scripts\\python scripts\\make_demo_samples.py [--person 1]
Output: ../sample-data/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

DATA = BACKEND / "training" / "data_generated"
OUT = BACKEND.parent / "sample-data"
CLONE_HOLDER = {"surname": "VERMA", "given": "RAKESH"}
EXPIRY_YEARS_ADDED = 5


def _font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    raise SystemExit(f"None of the fonts {names} is installed.")


def reprint(page: np.ndarray, bbox: dict, text: str, fonts: list[str], fit_width: bool) -> np.ndarray:
    """Paint over the box with the surrounding paper colour and print ``text`` in its place."""
    x, y, w, h = bbox["x"], bbox["y"], bbox["w"], bbox["h"]
    ring = np.concatenate([page[max(0, y - 6):y - 2, x:x + w].reshape(-1, 3),
                           page[y + h + 2:y + h + 6, x:x + w].reshape(-1, 3)])
    paper = tuple(int(c) for c in np.median(ring, axis=0)[::-1])
    img = Image.fromarray(cv2.cvtColor(page, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img)
    size = h + 4
    font = _font(fonts, size)
    while fit_width and size > 8 and draw.textlength(text, font=font) > w:
        size -= 1
        font = _font(fonts, size)
    width = int(max(w, draw.textlength(text, font=font)))
    draw.rectangle([x - 2, y - 2, x + width + 2, y + h + 2], fill=paper)
    top = draw.textbbox((0, 0), text, font=font)[1]
    draw.text((x, y - top + max(0, (h - (draw.textbbox((0, 0), text, font=font)[3] - top)) // 2)), text,
              fill=(20, 20, 20), font=font)
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def _card(doc: str, person: int) -> tuple[np.ndarray, dict, dict, dict]:
    stem = f"{doc}_{person:04d}"
    source, ann_path = DATA / doc / f"{stem}.jpg", DATA / "annotations" / doc / f"{stem}.json"
    if not source.is_file() or not ann_path.is_file():
        raise SystemExit(f"{source} not found; generate the dataset first (scripts/cardgen/generate.py).")
    ann = json.loads(ann_path.read_text(encoding="utf-8"))
    boxes: dict = {}
    for r in ann["text_regions"]:
        boxes.setdefault(r["field"], r["bbox"])  # first occurrence (the front of the card)
    photo = next(r["bbox"] for r in ann["regions"] if r["kind"] == "photo")
    return cv2.imread(str(source)), ann["fields"], boxes, photo


def make_card_forgeries(person: int, sans: list[str], save) -> None:
    # Aadhaar: the name is re-printed; the number still belongs to the real holder.
    page, fields, box, _ = _card("aadhar", person)
    name = f"{CLONE_HOLDER['given'].title()} {CLONE_HOLDER['surname'].title()}"
    save("demo_aadhaar_name_swap.jpg", reprint(page, box["Aadhaar_Name"], name, sans, fit_width=False))

    # Driving licence: another person's photo pasted over the holder's.
    page, _, _, photo = _card("driving_license", person)
    other, _, _, other_photo = _card("driving_license", person + 1)
    x, y, w, h = photo["x"], photo["y"], photo["w"], photo["h"]
    ox, oy, ow, oh = other_photo["x"], other_photo["y"], other_photo["w"], other_photo["h"]
    save("demo_dl_live_holder.jpg", page[y:y + h, x:x + w].copy())
    # The pasted photo went through its own JPEG round trip, as a cut-out from another file would.
    patch = cv2.resize(other[oy:oy + oh, ox:ox + ow], (w, h), interpolation=cv2.INTER_AREA)
    patch = cv2.imdecode(cv2.imencode(".jpg", patch, [cv2.IMWRITE_JPEG_QUALITY, 60])[1], cv2.IMREAD_COLOR)
    swapped = page.copy()
    swapped[y:y + h, x:x + w] = patch
    save("demo_dl_photo_swap.jpg", swapped)

    # PAN: birth year moved back so the holder appears older.
    page, fields, box, _ = _card("pan", person)
    d, m, yr = fields["PAN_DOB"].split("/")
    save("demo_pan_dob_altered.jpg", reprint(page, box["PAN_DOB"], f"{d}/{m}/{int(yr) - 8}", sans, fit_width=True))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--person", type=int, default=1, help="serial number of the dataset person to use")
    args = ap.parse_args()

    stem = f"passport_{args.person:04d}"
    source, ann_path = DATA / "passport" / f"{stem}.jpg", DATA / "annotations" / "passport" / f"{stem}.json"
    if not source.is_file() or not ann_path.is_file():
        raise SystemExit(f"{source} not found; generate the dataset first (scripts/cardgen/generate.py).")
    ann = json.loads(ann_path.read_text(encoding="utf-8"))
    fields = ann["fields"]
    box = {r["field"]: r["bbox"] for r in ann["text_regions"]}
    page = cv2.imread(str(source))
    mono, sans = ["consola.ttf", "cour.ttf", "DejaVuSansMono.ttf"], ["arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"]
    OUT.mkdir(exist_ok=True)
    save = lambda name, img: cv2.imwrite(str(OUT / name), img, [cv2.IMWRITE_JPEG_QUALITY, 95])  # noqa: E731

    save("demo_passport_genuine.jpg", page)

    # Tampered: the forger pushes the expiry year out in the MRZ but cannot recompute the check digits.
    line2 = fields["Passport_MRZ_Line_2"]
    year = f"{(int(line2[21:23]) + EXPIRY_YEARS_ADDED) % 100:02d}"
    save("demo_passport_tampered.jpg",
         reprint(page, box["Passport_MRZ_Line_2"], line2[:21] + year + line2[23:], mono, fit_width=True))

    # Clone: a real passport number re-issued to someone else (name and MRZ name line replaced).
    line1 = f"P<{fields['Passport_Country_Code']}{CLONE_HOLDER['surname']}<<{CLONE_HOLDER['given']}".ljust(44, "<")[:44]
    clone = reprint(page, box["Passport_Surname"], CLONE_HOLDER["surname"].title(), sans, fit_width=False)
    clone = reprint(clone, box["Passport_Given_Name"], CLONE_HOLDER["given"].title(), sans, fit_width=False)
    clone = reprint(clone, box["Passport_MRZ_Line_1"], line1, mono, fit_width=True)
    save("demo_passport_clone.jpg", clone)

    make_card_forgeries(args.person, sans, save)

    print(f"Source: {stem} ({fields['Passport_Given_Name']} {fields['Passport_Surname']})")
    print("Wrote:", *sorted(p.name for p in OUT.glob("demo_*.jpg")), sep="\n  ")


if __name__ == "__main__":
    main()

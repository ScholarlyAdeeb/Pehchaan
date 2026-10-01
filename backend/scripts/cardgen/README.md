# Identity-card dataset generator

Rebuilds the `sample-data` card dataset as **images with the image holders
marked**, from the one spreadsheet that holds the data:

```
sample-data/templates/mock_government_ids_300.xlsx   300 people, 8 sheets
        |
        +--> data_generated/aadhar/          300 x 768x1024
        +--> data_generated/pan/              300 x  768x 518
        +--> data_generated/driving_license/  300 x 1000x 579
        +--> data_generated/passport/         300 x 1264x1691
        +--> data_generated/annotations/<type>/<name>.json
        +--> data_generated/manifest.json
```

Every image gets a sidecar JSON carrying the holder rectangles, the person's
derived profile, and the field values that were typeset onto it.

## Run it

```bash
cd backend
python scripts/cardgen/extract_layouts.py     # once: recover the card layouts
python scripts/cardgen/faces.py               # once: harvest 300 portraits
python scripts/cardgen/preview_regions.py      # the accuracy gate (see below)
python scripts/cardgen/generate.py             # generate; opens a dashboard
```

Useful flags:

| flag | effect |
|---|---|
| `--types pan aadhar` | only these cards |
| `--limit 20` | first 20 people, for a smoke run |
| `--delay 0.03` | pause per image; the full run is ~20s unaided, too quick to watch |
| `--port 9000` | dashboard port |
| `--hold 600` | seconds to keep the dashboard up after the run |
| `--no-browser` | serve the dashboard without opening a window |
| `--out DIR` | output directory (default `training/data_generated`) |
| `--draw-boxes` | also outline the measured holders on the card |

`generate.py` opens a dark-theme dashboard at `http://127.0.0.1:8765/` showing
the current stage, per-document-type counts, elapsed time, throughput and a live
ETA, plus a strip of the most recent outputs.

## How field placement works

Nothing about the layout is guessed. `extract_layouts.py` reads page 1 of each
source PDF and recovers every text run with its exact position, font size and
colour:

* the cards are one background JPEG plus a text overlay, and the content stream
  gives the placement matrix directly;
* the fonts are CID fonts, so glyph codes go through the font's `/ToUnicode`
  CMap to recover real characters;
* positions come out in background-image pixels via a full CTM/text-matrix
  walk, so relative `Td`/`TD` positioning (the passport) is handled too;
* runs outside the background are dropped and counted - the DL page writes a
  stray `RTO Delhi` into the white space above the card.

`generate.py` then binds each run to a spreadsheet column by matching the text
against row 1, and re-wraps each field to the original line count and width.

Two things are hand-placed because the source PDF gets them wrong, both
documented at their definitions:

* `PASSPORT_SLOTS` - the passport drops Place of Birth and Place of Issue about
  150 px below their printed labels, and writes both MRZ lines into the middle
  of the data page.
* `FIELD_FIXUPS` - the DL writes a bare `1` where the licence number belongs and
  truncates `S/D/W` to the forename.

## Image holders

Holders live in `app/modules/localization/photo_regions.py` as page-relative
normalised rectangles, one source of truth shared with the rest of the app.
Portraits are drawn solid, codes dashed, so an overlay is self-describing.

| card | holders | filled with |
|---|---|---|
| aadhaar | `photo`, `ghost_photo`, `qr` | portrait, faded portrait, QR |
| pan | `photo`, `qr` | portrait, QR |
| driving_license | `photo` | portrait |
| passport | `photo`, `barcode` | portrait, *placeholder* (see below) |

Outlines are **not** drawn by default - a real card has no green box on it. Pass
`--draw-boxes` to overlay the measured geometry for review. The rectangles are
recorded in the sidecar JSON either way, so they remain ground truth.

## Where the content comes from

`python scripts/cardgen/faces.py` harvests one portrait per person into
`sample-data/templates/_face_cache`:

* source: `backend/training/data/aadhar/AADHARDATASET_Page_NNN.jpg`, which is
  1:1 with spreadsheet serial NNN, so person *n* gets face *n* on **all four**
  cards - the consistency a face verification set needs.
* the portraits are found with the project's own YuNet detector
  (`app/modules/face/detector.py`); no new dependency.
* the photo rectangle is located by segmenting the colour photo off the white
  card stock. The specimen template prints every portrait identically, so the
  rect measures as exactly `(28, 230, 420, 457)` on every page.
* those source pages are marked "SYNTHETIC / SPECIMEN - NOT A REAL DOCUMENT".

`codes.py` generates the QR codes with `cv2.QRCodeEncoder` - also already in
the venv. Payloads are per card: the PAN number for a PAN card, and
`{uid, name, dob, gender}` for Aadhaar. All 600 codes decode back to their exact
payload.

### Two deliberate limits

**The Aadhaar QR omits the address.** With it the payload reaches QR version 9
(53x53 modules), and this build's `QRCodeDetector` cannot read anything that
large - the code would look entirely normal and scan to nothing. The encoder's
version and correction level are not reachable from Python
(`QRCodeEncoder.encode` takes at most two arguments), so length is the only
lever. `qr_matrix` refuses to emit anything above version 7 rather than draw an
unreadable code, and a test pins the payload length. A real UIDAI QR is an
opaque token rather than readable fields, so a compact payload is also closer to
the real thing.

**The passport barcode is left empty.** The observations page carries a
**PDF417** 2D barcode and OpenCV has no PDF417 encoder. Drawing something
barcode-shaped that scans to nothing would be worse than an honest placeholder,
so it stays a labelled box and the sidecar records
`"filled": false, "note": "no encoder available"`. If you want it real, that
needs `pylibdmtx` or `python-barcode` added to the venv.


## The spreadsheet has no photos

There is no photo column anywhere in the workbook, so the generator takes each
person's portrait from the specimen pages in `backend/training/data` (see
above) rather than inventing one.

The generator does derive and record the demographic attributes - name,
nationality, sex, age from date of birth, and the state implied by the address
- and checks the row is internally consistent (PAN vs Aadhaar vs passport name,
gender vs sex, age bounds, DOB agreement). Disagreements are counted and
reported on the dashboard; the current workbook produces none.

## The measured rectangles still need eyeballing

**`preview_regions.py` is the accuracy gate.** Those numbers were measured off
photographic card scans and are good to roughly ±10 px, so after any edit to the
table, run it and look at the four PNGs in `preview/`. A box that looks wrong
there is a box that is wrong - and now that the boxes hold real faces and real
codes, a misaligned holder is obvious at a glance.

# PEHCHAAN — AI-Based Fake Identity & Document Screening

**SIH 2026 · Problem Statement 26188** · Ministry of Home Affairs · Sashastra Seema Bal (SSB) ·
Theme: Blockchain & Cybersecurity

An officer uploads (or photographs) a passport, Aadhaar, PAN card, driving licence, visa or
permit, optionally with a live photo of the traveller. In a few seconds PEHCHAAN:

1. **Detects the document type** — MobileNetV2 image classifier + printed-text markers
2. **Extracts the fields** — Tesseract OCR, then format-aware extractors (MRZ, Aadhaar, PAN, DL…)
3. **Checks the document** — ICAO 9303 check digits, printed-page-vs-MRZ, Verhoeff, PAN/DL formats, expiry, PIN-vs-state
4. **Looks for tampering** — Error Level Analysis, copy-move detection, metadata
5. **Matches the face** — document portrait vs live photo
6. **Compares with the database** — earlier screenings of the same document number
7. **Scores the risk** — one 0–100 score with every point traceable, then CLEAR / REVIEW / HIGH RISK

Each screening is stored in Postgres (Neon) as a SHA-256 hash-chained record with the full
analysis, and every screening and officer decision goes into an HMAC-signed audit log.

Docs: [problem statement](docs/PROBLEM_STATEMENT.md) · [architecture and measured results](docs/TECHNICAL_ARCHITECTURE.md) · [API](docs/API.md) · [Vercel deployment](docs/DEPLOYMENT_VERCEL.md)

## Repository layout

| Path | What it is |
|---|---|
| [`backend/`](backend) | Screening engine (Python, FastAPI): OCR, field detection, validation rules, forensics, face match, risk score |
| [`Pehchaan/`](Pehchaan) | Dashboard and API gateway (React, Express): sign-in, roles, storage, audit ledger |
| [`fabric/`](fabric) | Hyperledger Fabric network and chaincode that anchor sealed audit batches |
| [`docs/`](docs) | Architecture, API, deployment, slides |
| [`sample-data/`](sample-data) | Demo images (generated locally, not committed) |
| `Pehchaan/vercel.json`, `Pehchaan/api/` | Vercel build, routing and cron configuration, and the function entry |
| `start_all.bat` | One-step local launcher (Windows) |

---

## Run it

Requirements: Python 3.11, Node 18+, the **Tesseract OCR binary**, and the two OpenCV face models in `backend/models/face/` (`face_recognition_sface_2021dec.onnx`, `face_detection_yunet_2023mar.onnx` from github.com/opencv/opencv_zoo) (Windows installer:
UB-Mannheim build; include the Hindi/Nepali language packs if you want them).

```bat
start_all.bat
```

That creates the Python virtualenv, installs dependencies, generates secrets, issues the
TLS certificates for the gateway-engine link, builds the issued-documents database if the
generated dataset is present, and opens two windows:

| Service | URL | What it is |
|---|---|---|
| Web app + API gateway | http://localhost:3000 | React UI, login/roles, Neon storage, hash chain (Express, `Pehchaan/server.ts`) |
| Screening engine | https://127.0.0.1:8000 | FastAPI — all AI/OCR/forensics (`backend/app`). Mutual TLS: only the gateway can call it |

Manual start (two terminals):

```bash
# backend
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
python -m scripts.make_tls_certs      # once: certificates for the gateway-engine link
python run_engine.py                  # HTTPS + client certificate when backend/certs exists

# dashboard and gateway
cd Pehchaan
npm install
npm run dev
```

Configuration: copy `backend/.env.example` → `backend/.env` and `Pehchaan/.env.example` →
`Pehchaan/.env`. Put the same Neon connection string in both (the engine reads earlier
screenings for the records cross-check). Set `TESSERACT_CMD` if Tesseract is not on PATH.

Optional Hyperledger Fabric ledger (needs Docker): `bash fabric/network.sh up`.

Architecture and measured results: [`docs/TECHNICAL_ARCHITECTURE.md`](docs/TECHNICAL_ARCHITECTURE.md).
Hosting the dashboard and gateway on Vercel: [`docs/DEPLOYMENT_VERCEL.md`](docs/DEPLOYMENT_VERCEL.md).
Import the repository and pick the `Pehchaan` directory (Root Directory = `Pehchaan`); `vercel.json` there holds the
build settings. The engine and the Fabric network run on your own machine or VM.

**First login:** on an empty database the sign-in page offers *Create Admin Account*, which
seeds an admin, an officer and a post in-charge for checkpoint `CP-001`.

### Demo images

```bash
cd backend
.venv\Scripts\python scripts\make_demo_samples.py
```

writes three passports to `sample-data/` built from the dataset with a correct ICAO MRZ:

| File | Expected result |
|---|---|
| `demo_passport_genuine.jpg` | **CLEAR** — all check digits and printed fields agree |
| `demo_passport_tampered.jpg` | **HIGH RISK** — expiry year altered: check digit, composite and printed-vs-MRZ all fail |
| `demo_passport_clone.jpg` | **HIGH RISK** — MRZ holder differs from the printed page; once the genuine one is on file, the database check also reports *same number, different holder* |

### Tests

```bash
cd backend && .venv\Scripts\python -m pytest -q      # 111 tests
cd Pehchaan && npm run lint && npm test && npm run build
```

---

## How the risk score is calculated

Every signal produces its own risk from 0 (nothing wrong) to 100:

| Signal | Risk | Weight |
|---|---|---|
| Document validation | sum of rule penalties — critical 30, warning 10, info 2 — capped at 100 | 0.30 |
| Tampering forensics | ELA (pixel re-compression difference) × 0.7 + copy-move (keypoint displacement clusters) × 0.15 + metadata × 0.15 | 0.35 |
| Face match | different person 100 · inconclusive 60 · same person (1 − similarity) × 20 · no face found 40 | 0.20 |
| Records history | identity conflict 100 · previously flagged 50 · consistent 0 | 0.15 |

```
score = Σ (risk × weight) / Σ (weights of the signals that actually ran)
```

Signals that did not run (no live photo; document never screened before) are left out and the
remaining weights are rescaled, so absence of evidence does not lower the score.

**Hard floor:** any critical rule failure, a "tampered" forensics verdict, or an identity
conflict with earlier records raises the score to at least **66** — a good face match cannot
wash out a forged check digit.

**Face floor:** once a live photo is given it outweighs everything else. A face that is clearly a
different person lifts the score to at least **85** (**90** when far below the line); an
inconclusive match to at least **45**, so it can never be cleared automatically.

**Bands:** 0–30 CLEAR · 31–65 REVIEW · 66–100 HIGH RISK.

Every scan also carries an **evaluation matrix** — one line per check with how it was measured
(arithmetic check digit, entry comparison, pixel re-compression, keypoint displacement, face
similarity, database comparison), the value found, the value needed, and a one-sentence result.
The same lines are written into the HMAC-signed audit entry for the scan.

Worked example — tampered demo passport (no live photo, number seen once before and consistent):

| Signal | Risk | Effective weight | Points |
|---|---|---|---|
| Validation: 3 critical × 30 = 90 | 90 | 0.30 / 0.80 = 37.5% | 33.8 |
| Tampering: ELA 2×0.5 + … = ~31 | 31 | 0.35 / 0.80 = 43.8% | 13.6 |
| Records: consistent | 0 | 0.15 / 0.80 = 18.8% | 0.0 |
| **Weighted** | | | **47** → floor → **66 HIGH RISK** |

The report screen shows this table for every scan.

---

## ML models and engines — what is actually used

| Component | What it is | Status |
|---|---|---|
| Document-type classifier | MobileNetV2 (ImageNet-pretrained), last layer retrained on 4 classes (Aadhaar, driving licence, PAN, passport); 960 training / 240 held-out images split by person, 8 epochs, Adam 1e-3, 224×224 | **Active.** 100% on the held-out split — but that split comes from the same generated templates, so real-world accuracy is unmeasured. Metrics: `backend/training/document_classifier_metrics.json` |
| Region detector | Faster R-CNN ResNet-50 FPN, 17 field classes, trained on the generated cards | **Active, gated.** Held-out mAP50 1.000, mAP75 0.998 on one template per document type. Its boxes are used only when the layout is recognised; on any other layout the full-page reading is kept. Metrics: `backend/training/region_detector_metrics.json` |
| OCR | Tesseract 5 LSTM (eng/hin/nep) + orientation detection | Active |
| Face detector | OpenCV **YuNet** neural detector (Haar cascade fallback); the portrait is chosen by photo quality so ghost images/watermarks are skipped | Active |
| Face matcher | OpenCV **SFace** face-recognition network (128-D embedding, cosine similarity). Bands measured on 1,770 different-person dataset pairs: same person ≥ 0.45 (~0.6% of different people pass), different person < 0.30. Histogram+ORB fallback if the model file is missing | Active |
| Tampering | ELA, copy-move (ORB displacement clustering; ignores face-to-face and same-line text matches; alarm at 100 pairs because printed documents reach ~80 naturally), EXIF | Active |

Admins can see this live on **System health & models** in the app (from `GET /api/system/models`).

---

## Datasets

| Data | Used for |
|---|---|
| `backend/training/data_generated/` — 1,200 generated cards for 300 invented people (not committed; rebuilt by `backend/scripts/cardgen`) | Training and validating the classifier and the region detector; the issued-documents database; demo images |
| `backend/data/reference/pincodes_sample.json` | PIN-code ↔ state check (sample, not the full directory) |
| `psk_directory.json` | Passport issuing-office check |
| `evisa_countries.json`, `visa_nationality_matrix.json` | e-Visa eligibility, unusual visa/nationality combinations |
| `border_threats.json` | Border threat context |
| `datasets_catalog.json` | Catalogue of 45 data.gov.in datasets (7 seeded) for admin analytics |
| Neon `pehchaan_scans` | Records cross-check against earlier screenings |

---

## Project layout

```
backend/                     FastAPI screening engine
  app/api/                   routes_documents (scan), routes_health (/health, /system/models), …
  app/modules/classification auto_detect.py, classifier.py, model.py
  app/modules/ocr            engine.py, preprocessing.py, mrz_parser.py, indian_extractors.py
  app/modules/validation     rules_engine.py
  app/modules/tampering      ela.py, copy_move.py, metadata_analysis.py, tampering_engine.py
  app/modules/face           detector.py, verifier.py
  app/modules/localization   detector.py          (field region detector)
  app/modules/records        crosscheck.py        (earlier screenings), issued_documents.py
  app/modules/risk           risk_engine.py       (score + full breakdown)
  app/modules/security       audit signing, sealed batches, retention
  training/                  train.py, train_region_detector.py, metrics
  scripts/                   cardgen/ (dataset generator), make_demo_samples.py, make_tls_certs.py, …
  run_engine.py              starts the engine (mutual TLS when backend/certs exists)
  tests/
Pehchaan/
  server.ts                  Express: auth, roles, /api/screenings → engine → Neon
  server/                    neon.ts (storage, hash chain), session.ts, outbox.ts, fabric.ts, trust.ts, …
  src/components/            NewScanView, ScreeningReportView, OverviewView, SystemHealthDocsView, …
  api/index.js               Vercel function entry (loads dist-server/app.cjs)
  vercel.json                Vercel build, routing and cron settings
fabric/
  network.sh                 up | deploy | status | down | destroy
  chaincode/auditledger/     Go chaincode that stores batch roots
sample-data/                 demo images (generated, not committed)
```

---

## Known limitations

- The classifier knows Aadhaar, PAN, driving licence and passport; visa and permit are recognised from printed text.
- The classifier and region detector were trained and measured on generated cards (one template per document type), not on real documents.
- The Fabric network has one organisation and one orderer; it shows the anchoring flow, not multi-party trust.
- Copy-move detection is deliberately conservative: it catches large clones and misses small ones.
- Field extraction is tuned to the dataset layouts; unusual layouts may leave fields "Not read".
- New screens (scan, report, system health) are English-only; the rest of the UI has Hindi/Nepali.

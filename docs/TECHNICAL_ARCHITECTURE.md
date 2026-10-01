# PEHCHAAN — Technical Architecture, Security and Execution Flow

Smart India Hackathon 2026, problem statement 26188. This document describes
what the code in this repository does today. Every figure in it is measured
by a script in the repository; section 11 lists what is not built.

## 1. System overview

PEHCHAAN screens identity documents at a border checkpoint: passport,
Aadhaar, PAN, driving licence, and (by text rules only) visa and permit. An
officer uploads a document image and optionally a live photo of the holder;
the system returns a 0–100 risk score, a verdict and the evidence behind it.

Two services run on the checkpoint machine:

| Service | Port | Stack | Owns |
|---|---|---|---|
| Screening engine | 8000 | Python 3.11, FastAPI | OCR, field location, validation rules, forensics, face match, issuing-records check, risk score |
| Gateway + dashboard | 3000 | Express, TypeScript, React 19, Vite 6, Tailwind 4 | Login, roles, checkpoint scope, storage in PostgreSQL (Neon), hash chain, audit log, offline outbox, UI |

The gateway never runs model code. It forwards the upload to
`POST /api/documents/scan` over mutual TLS with a shared `x-engine-key`,
stores the result and serves the UI. All models run locally; no external API
is called during a scan.

A third, optional component is a Hyperledger Fabric network (one peer, one
orderer) that records the root of every sealed batch of screenings.

The gateway and dashboard can also be hosted on Vercel, with the engine and
Fabric on a machine you control: see `docs/DEPLOYMENT_VERCEL.md`.

## 2. Request flow

1. The officer signs in. The gateway checks the bcrypt hash (cost 12) and
   sets two HttpOnly cookies: a 15-minute access token and a 12-hour refresh
   token, both bound to a session fingerprint (section 9.1). Roles: `OFFICER`,
   `POST_INCHARGE`, `ADMIN`. The checkpoint is resolved from the device
   location against the officer's assigned checkpoints.
2. New Scan: document type (or auto-detect), document image (JPEG/PNG, up to
   12 MB, up to 60 megapixels) and an optional live photo.
3. The gateway verifies the officer's checkpoint scope and calls the engine.
4. The engine runs the classifier, OCR with field location, forensics and
   face detection in parallel, then validation, the two records checks and
   the risk engine.
5. The gateway stores the result as a hash-chained row plus a signed audit
   entry, or queues both on disk if the database is unreachable (section 8).

## 3. Models and data

### 3.1 Dataset

`backend/scripts/cardgen` renders 1,200 cards for 300 synthetic people
(Aadhaar, PAN, driving licence, passport) from a workbook. Identifiers follow
the real rules: Aadhaar passes Verhoeff, PAN follows the holder-type and
surname-initial rules, the passport MRZ has correct ICAO 9303 check digits,
and licence dates respect the minimum age. Each card has an annotation file
with the printed values and the exact pixel box of every value, photo, QR
code and barcode.

Both models below hold out the same 60 people (240 cards); neither saw any
of their documents in training.

### 3.2 Document-type classifier

MobileNetV2, four classes (Aadhaar, driving licence, PAN, passport), trained
by `backend/training/train.py`. Held-out accuracy: 100% on cards as
generated and 100% on photo-style versions (card on a random background,
tilted, skewed).

Auto-detect combines the classifier with printed text markers; visa and
permit are recognised by text markers only.

### 3.3 Field (region) detector

Faster R-CNN, ResNet-50 FPN, anchors widened for long thin text lines,
trained on the RTX 4070 by `backend/training/train_region_detector.py`.
15 field classes: photo, name, surname, guardian name, date of birth, date of
issue, date of expiry, document number, nationality, gender, address, place
of birth, MRZ, QR code, barcode.

Held-out people, photo-style images: mAP@0.5 1.000, mAP@0.75 0.998, mean IoU
0.955. About 110 ms per image on the GPU, about 2 s on CPU.

### 3.4 What these scores do and do not mean

Every card of a type comes from one template. The held-out scores show the
models handle unseen people, faces, values and photo-style distortion on
*these* layouts. They are not a measurement on real documents or other
layouts. On an older-style passport the detector returned confident boxes on
the wrong text; section 4.2 describes the check that stops that from
affecting a scan.

## 4. OCR and field extraction

### 4.1 Full-page reading

Preprocessing: orientation from Tesseract OSD, deskew, denoise, contrast
enhancement. Tesseract 5 (LSTM) reads the page with a page-segmentation mode
chosen per document type. Passports get a second MRZ-tuned pass on the band
where MRZ fragments were found. Format-aware extractors then pick fields out
of the text by label and pattern.

### 4.2 Region-assisted reading

The field detector locates each field, and each text box is cropped and read
on its own in single-line mode (`app/modules/ocr/region_fields.py`).

- A box reading is accepted only if it parses as its class: a real calendar
  date, a PAN-shaped string, a Verhoeff-valid Aadhaar number, and so on.
  Letter/digit look-alikes (O/0, S/5, ...) are corrected only where the
  format fixes which one is expected.
- Accepted readings fill fields the page reading missed, replace page values
  that fail the same check, and replace a differing page value when both the
  detection and the reading are confident.
- **Layout check.** Region readings are used only if the detections look
  like a known card: at least 75% of the boxes parse as their class and no
  field appears more often than the template prints it. Otherwise the
  full-page reading is used alone and the report says so.

Measured on the 240 held-out cards (`training/eval_region_ocr.py`), 1,440
fields compared with ground truth:

| Document | Full page only | With located fields |
|---|---|---|
| Aadhaar | 91.3% | 100% |
| PAN | 0% | 100% |
| Driving licence | 17.8% | 99.7% |
| Passport | 68.0% | 99.3% |
| **All** | **48.0%** | **99.65%** |

No field that was right from the full page became wrong.

### 4.3 MRZ

TD3 (2 x 44) and TD1 (3 x 30) are parsed per ICAO 9303. Each field's check
digit and the composite are recomputed with the 7-3-1 weighting.

## 5. Validation rules

Deterministic and explainable (`app/modules/validation/rules_engine.py`).
Each finding has a severity and a penalty: info 2, warning 10, critical 30.

- Passport: MRZ present, every check digit, composite, expiry, plausible age,
  known country code, MRZ name vs printed name, MRZ vs printed dates and
  number, Passport Seva Kendra code.
- Aadhaar Verhoeff checksum; PAN format; driving-licence number format.
- Required fields per type, issue date before expiry, PIN code vs state,
  e-Visa eligibility, visa type vs nationality plausibility.

Reference tables are in `backend/data/reference/`. The catalogue lists 45
data.gov.in datasets, of which 7 are loaded and 38 are pending.

## 6. Forensics, face match and records

### 6.1 Tampering

Run on the uploaded bytes, not the preprocessed image.

- Error Level Analysis: recompress at JPEG quality 90 and measure where the
  image disagrees with its own recompression.
- Copy-move: ORB keypoints matched against themselves and clustered by
  displacement; pairs inside the portrait and along a text line are
  discarded; 100 pairs in one cluster is the alarm level.
- Metadata: editing-software signatures and inconsistent timestamps in EXIF.

Sub-score: 0.7 ELA + 0.15 copy-move + 0.15 metadata.

### 6.2 Face

OpenCV YuNet finds faces; the holder's portrait is chosen by tonal range and
sharpness so ghost images and watermarks are skipped. OpenCV SFace compares
the portrait with the live photo: match at cosine similarity 0.45 or above,
different person below 0.30, inconclusive in between. dlib and a
histogram + ORB comparison are fallbacks when the SFace model is absent.

### 6.3 Issued-documents database

`backend/data/registry/issued_documents.sqlite`, built from the dataset by
`python -m scripts.build_issued_documents_db`: one row per issued document
(1,200) with holder name, date of birth and expiry. Document numbers are
stored only as keyed hashes (`PII_HASH_KEY`) plus a masked form.

A scanned document is looked up by number and its name, date of birth and
expiry are compared with what was issued:

- all agree: match, records risk 0;
- any differ: identity conflict, records risk 100 and the score floor of 66;
- number not in the database: reported as not found, no effect on the score
  (the database covers only the documents it was built from).

It is a local file, so the check works with no network.

### 6.4 Earlier screenings

The same number is looked up (by keyed hash) among earlier scans. A different
name or date of birth is an identity conflict; an earlier HIGH RISK verdict
adds risk 50. A separate registry of perceptual fingerprints recognises
images of documents already rejected as forged.

## 7. Risk score

Weights: validation 0.30, tampering 0.35, face 0.20, records 0.15. A signal
that did not run (no live photo, number unknown to both records checks) is
left out and the remaining weights are renormalised, so missing evidence
never lowers a score.

Floors applied after weighting:

| Condition | Minimum score |
|---|---|
| Any critical validation failure, forensics verdict "tampered", or a records conflict | 66 |
| Face is a different person | 85 (90 when far below the threshold) |
| Face inconclusive | 45 |

Bands: 0–30 CLEAR, 31–65 REVIEW, 66–100 HIGH RISK.

Every scan carries an evaluation table: one row per check with the method,
the value measured, the value expected and a one-sentence result. The same
table is written into the signed audit entry.

## 8. Storage, ledger and offline operation

### 8.1 Hash chain, signed batches and the Fabric ledger

Each scan row stores `SHA-256(previous row hash + this record)`, so altering
or removing a row breaks every later link; an administrator can re-verify the
chain. Scans are sealed every 10 minutes into Merkle batches whose roots are
signed with Ed25519, and a scan's receipt can be verified without database
access. Overrides of a verdict need a second officer's co-signature.

**Hyperledger Fabric.** Every sealed batch's Merkle root is then submitted to
the `auditledger` chaincode on a Fabric 2.5 channel (`fabric/`):

- `AnchorBatch` stores the root, record count, first and last record ids and
  the gateway's signature. It accepts a batch id once; a second write with any
  content is rejected by the chaincode.
- No personal data goes on chain.
- The gateway (`frontend/server/fabric.ts`, official `@hyperledger/fabric-gateway`
  client) waits for the transaction to be committed in a block and stores the
  transaction id with the batch. Batches sealed before Fabric was configured,
  or while the peer was unreachable, are anchored by the next maintenance run.
- "Compare database with ledger" on the admin Security screen checks every
  batch root in PostgreSQL against the ledger. A difference means the
  database copy was rewritten after sealing.

`bash fabric/network.sh up` creates the network with Docker: identities
(cryptogen), a Raft orderer, one peer for the organisation `SSBMSP`, the
channel `pehchaan`, and the chaincode, with TLS on every link. Measured on
the development machine: a root is committed in about 2 seconds.

What this network is and is not: it is a real Fabric ledger, and the database
administrator does not hold its keys. It has **one organisation and one
orderer**, so today a single party endorses and orders every transaction.
The value of a permissioned blockchain comes from several organisations each
running a peer (for example the border force and the immigration authority);
adding one is a configuration change in `fabric/network/`, not a code change,
but it has not been done.

### 8.2 Audit log

Every screening and decision is an audit entry signed with HMAC-SHA256 over
its content and timestamp. Verification reports each entry as valid, legacy
(pre-signing) or invalid.

### 8.3 Offline operation

The engine and gateway run on the checkpoint machine, so screening itself
needs no network; only the write to the cloud database can fail.

`frontend/server/outbox.ts`: when that write fails, the scan, its signed
audit entry and its system log are saved as files in `frontend/data/outbox/`.
They survive a restart. Every 30 seconds (`OUTBOX_SYNC_SECONDS`) the gateway
checks the database and replays the queue in its original order; a scan joins
the hash chain at that point. A record the database rejects is moved to
`outbox/failed/` so it cannot block the rest. After one failed write the
database is treated as down for 30 seconds, so offline scans are not held up
by connection timeouts. Queued scans are listed with a "queued" status, and
the admin bar shows the count.

Signing in offline: each successful online sign-in stores the account on the
checkpoint machine (`frontend/server/offline-auth.ts`): the same bcrypt hash
the database holds, the role and the checkpoints, sealed with an HMAC. When
the database cannot be reached, the password is checked against that copy and
the session is marked "Offline sign-in". An edited file is rejected whole; an
entry is honoured for 7 days after the last online sign-in
(`OFFLINE_LOGIN_DAYS`); accounts that must change their password, and
accounts that never signed in on that machine, cannot sign in offline.
Deactivating an account or resetting its password removes the copy on the
gateway that handled the change.

Still not available offline: the earlier-screenings lookup (reported as
unavailable) and administration (users, checkpoints). The issued-documents
check, all models and all rules work offline.

## 9. Security and privacy

- Passwords: bcrypt cost 12, forced change of temporary passwords.
- Role and checkpoint checks are enforced in the gateway on every route.
- Engine accepts requests only with the shared `ENGINE_API_KEY`.
- Document numbers: keyed hash plus masked form in the database, the audit
  log and the stored analysis; the full number is never stored.
- Model files are loaded only if their SHA-256 matches
  `backend/model_manifest.json`; PyTorch checkpoints load with
  `weights_only=True`.
- Retention: raw text and images are removed from scans older than
  `SCAN_RETENTION_DAYS` (default 90).
- Insider-activity analytics and a CERT-In style incident report for admins.
- Secrets are generated on first start into git-ignored `.env` files.

### 9.1 Sessions

- The access token (15 minutes) and refresh token (12 hours) are HttpOnly,
  `SameSite=Strict` cookies, `Secure` over HTTPS. Page scripts cannot read
  them, and nothing is kept in `localStorage`.
- Every refresh issues a new refresh token and retires the old one; token ids
  are recorded in PostgreSQL. Presenting an already used token (a stolen
  copy) revokes every session from that sign-in.
- A refresh re-reads the account, so a role change or deactivation takes
  effect within 15 minutes.
- State-changing requests must echo a CSRF value in `X-CSRF-Token`
  (double-submit check).
- Scripts and API clients may still send an access token as a Bearer header.

### 9.2 Gateway to engine: mutual TLS

`python -m scripts.make_tls_certs` creates a private certificate authority, a
server certificate for the engine and a client certificate for the gateway.
With them in place `run_engine.py` serves HTTPS only and requires a client
certificate signed by that authority; the gateway verifies the engine the
same way. The API key is still required on top. Verified: a caller without a
client certificate, a caller that does not trust the authority, and plain
HTTP are all refused, and a valid certificate without the API key gets 401.
Without certificates the engine serves plain HTTP on loopback only and
refuses to bind any other address.

The connection to the cloud database is TLS.

## 10. Running it

`start_all.bat` creates the virtual environment, installs dependencies,
generates secrets, issues the TLS certificates and builds the issued-documents
database if they are missing, and starts both services. Fabric is started
separately with `bash fabric/network.sh up` (needs Docker).

| Check | Command | Result |
|---|---|---|
| Engine tests | `backend`: `python -m pytest -q` | 111 pass |
| Gateway checks | `frontend`: `npm test` | 7 queue checks, offline path check, 12 session and offline sign-in checks |
| Engine link | `frontend`: `npx tsx server/tls.check.ts` (engine running) | mutual TLS verified |
| Fabric | `bash fabric/network.sh up`, then `frontend`: `npx tsx server/fabric.check.ts` | anchor committed; rewrite rejected |
| Field extraction | `backend`: `python training/eval_region_ocr.py` | table in 4.2 |
| Demo images | `backend`: `python scripts/make_demo_samples.py` | genuine CLEAR; tampered and clone HIGH RISK |

Model files are not in the repository (`*.pt`, `*.pth`, `*.onnx` are
git-ignored): the classifier and region detector are produced by the two
training scripts, and the two face models come from the OpenCV model zoo.

## 11. Not built

| Earlier claim | Actual state |
|---|---|
| A multi-organisation Fabric network | The Fabric ledger is real but has one organisation and one orderer (8.1). |
| The gateway deployed on Vercel | Packaged and exercised locally (`docs/DEPLOYMENT_VERCEL.md`); not yet deployed. |
| Offline administration and earlier-screenings lookup | Need the database (8.3). |
| Accuracy on real documents | Not measured. All figures are on generated cards (3.4). |
| Watchlist / Interpol / immigration lookups | Not built. Records checks cover the issued-documents database and earlier PEHCHAAN scans. |
| Hindi and Nepali throughout | Navigation, login and overview only; working screens are English. |
| External timestamping of the ledger | Code paths exist for an RFC 3161 authority and for OpenTimestamps anchoring of batch roots; neither is configured (both off by default). |
| Multiple engine instances | Single engine process per checkpoint. |

# Backend — AI Document Screening API

FastAPI service implementing all four pipeline modules. See
[../docs/TECHNICAL_ARCHITECTURE.md](../docs/TECHNICAL_ARCHITECTURE.md) for the design rationale.

## Setup

```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # optional — defaults work out of the box
```

### OCR setup (Module 1)

`pytesseract` is a thin wrapper — it needs the actual **Tesseract-OCR
binary** installed separately:

- **Windows**: `winget install --id UB-Mannheim.TesseractOCR -e` (accept the
  UAC prompt), then set `TESSERACT_CMD` in `.env` to the installed
  `tesseract.exe` path (typically `C:\Program Files\Tesseract-OCR\tesseract.exe`).
- **macOS**: `brew install tesseract`
- **Linux**: `sudo apt-get install tesseract-ocr`

Without it, the API still runs — OCR-dependent fields come back empty with
a clear warning (`ocr.warning` in the response, and the "OCR: offline"
badge in the frontend), and every other module still works normally.

### Face verification backend (Module 4)

Works out of the box with a lightweight OpenCV-only comparator (no extra
install). For meaningfully better accuracy, install `face_recognition`
(needs CMake + a C++ toolchain for its `dlib` dependency) — uncomment it in
`requirements.txt`. The system auto-detects which backend is available; no
code changes needed either way.

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

- API docs (Swagger UI): http://127.0.0.1:8000/docs
- Health check: http://127.0.0.1:8000/api/health

## Test

```bash
pytest tests/ -v
```

11 tests cover the ICAO 9303 MRZ check-digit algorithm against the
canonical worked example (including a deliberately tampered field to prove
forgery detection), the validation rule engine, and the face-similarity
math.

## Folder map

```
backend/
├── app/
│   ├── main.py              FastAPI app + CORS + router wiring
│   ├── config.py            All tunable settings, env-driven
│   ├── api/                 HTTP route handlers (thin orchestration only)
│   ├── modules/
│   │   ├── ocr/             Module 1 — text + MRZ extraction
│   │   ├── validation/      Module 2 — rule-based document validation
│   │   ├── tampering/       Module 3 — ELA, copy-move, metadata forensics
│   │   ├── face/             Module 4 — face detection + similarity
│   │   └── risk/             Combines all of the above into one verdict
│   ├── models/               API-facing Pydantic response schemas
│   ├── storage/               In-memory audit trail (swap for Postgres later)
│   └── utils/                 Shared image/logging helpers
└── tests/                     pytest suite
```

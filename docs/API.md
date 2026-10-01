# API Reference

Base URL: `http://127.0.0.1:8000`. Interactive Swagger docs at `/docs`.

## `GET /api/health`

System status — which OCR/face backends are actually live. Used by the
frontend's topbar badges.

```json
{
  "status": "ok",
  "engines": { "ocr": "tesseract", "face_verification": "histogram+ORB (lightweight)" }
}
```

## `POST /api/documents/scan`

The main pipeline endpoint. `multipart/form-data`:

| Field | Type | Required | Notes |
|---|---|---|---|
| `document_type` | string | yes | `passport` \| `visa` \| `national_id` \| `driving_license` \| `permit` |
| `document` | file | yes | The document image |
| `live_face` | file | no | A live capture, for Module 4 face verification |

Returns a `ScanResponse` (see `backend/app/models/schemas.py` for the exact
shape) containing the OCR text/fields, MRZ breakdown (passports/visas),
validation issues, tampering evidence + ELA heatmap, face match, and the
final risk score/verdict. Every scan is also persisted to the audit trail.

## `GET /api/documents/scans?limit=50`

List recent scans (id, timestamp, document type, risk score, verdict) —
powers the Audit Log page.

## `GET /api/documents/scans/{id}`

Fetch one full scan report by id.

## `GET /api/documents/stats`

Aggregate counts by verdict — powers the Overview page's stat tiles.

## `POST /api/face/verify`

Standalone face check, independent of a full document scan.
`multipart/form-data` with `document_photo` and `live_photo`.

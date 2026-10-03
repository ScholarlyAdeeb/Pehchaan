---
title: PEHCHAAN Screening Engine
emoji: 🛂
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 6.29.1
python_version: "3.11"
app_file: space_app.py
pinned: false
---

# PEHCHAAN screening engine

The document-screening engine of PEHCHAAN (SIH 2026, PS 26188): OCR, field
detection, validation rules, tampering forensics, face match and risk score.
It is called by the PEHCHAAN gateway, not by browsers. Every `/api` request
must carry the engine API key in the `x-engine-key` header.

Space secrets (Settings → Variables and secrets):

| Secret | Value |
|---|---|
| `ENGINE_API_KEY` | same value as the gateway's `ENGINE_API_KEY` |
| `PII_HASH_KEY` | same value as the gateway's `PII_HASH_KEY`; the issued-documents database was built with it |
| `NEON_DATABASE_URL` | the gateway's PostgreSQL connection string (earlier-screenings check) |

Source: https://github.com/ScholarlyAdeeb/Pehchaan

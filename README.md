# PEHCHAAN

AI-based identity and document screening for border checkpoints
(Smart India Hackathon 2026, problem statement 26188).

The project lives in [`SIH-2026/`](SIH-2026/):

| Folder | What it is |
|---|---|
| [`SIH-2026/backend`](SIH-2026/backend) | Screening engine (Python, FastAPI): OCR, field detection, validation rules, forensics, face match, risk score |
| [`SIH-2026/frontend`](SIH-2026/frontend) | Dashboard and API gateway (React, Express): sign-in, roles, storage, audit ledger |
| [`SIH-2026/fabric`](SIH-2026/fabric) | Hyperledger Fabric network and chaincode that anchor sealed audit batches |
| [`SIH-2026/docs`](SIH-2026/docs) | Architecture, API, deployment |

Start here:

- Run it locally: [`SIH-2026/README.md`](SIH-2026/README.md)
- How it works and what was measured: [`SIH-2026/docs/TECHNICAL_ARCHITECTURE.md`](SIH-2026/docs/TECHNICAL_ARCHITECTURE.md)
- Deploy the dashboard and gateway on Vercel: [`SIH-2026/docs/DEPLOYMENT_VERCEL.md`](SIH-2026/docs/DEPLOYMENT_VERCEL.md).
  Set the Vercel project's **Root Directory** to `SIH-2026/frontend`; the engine and the Fabric network run on your own machine or VM.

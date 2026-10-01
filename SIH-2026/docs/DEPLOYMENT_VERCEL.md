# Deploying PEHCHAAN with the gateway on Vercel

Vercel runs static sites and short-lived serverless functions. That fits the
dashboard and the gateway. It does not fit the screening engine or a Fabric
network, which must run on a machine you control.

| Part | Runs on | Why |
|---|---|---|
| React dashboard | Vercel (static) | Plain build output. |
| Gateway (Express API) | Vercel (one serverless function) | Stateless: sessions are JWT cookies, all state is in PostgreSQL. |
| PostgreSQL | Neon | Already a hosted service. |
| Screening engine (Python) | A VM or the checkpoint machine | PyTorch, Tesseract and a 166 MB model exceed Vercel's 250 MB function limit; it also wants a GPU. |
| Fabric peer and orderer | A VM or the checkpoint machine | Long-running nodes with a ledger on disk. |

Status: the function entry was exercised locally against the bundled gateway
(health, auth, 404 fallback, cron secret). It has **not** been deployed to
Vercel from this repository; the first deployment is the real test.

## 1. Engine host

On the machine that will run the engine (public name `engine.example.org`
below):

```bash
cd backend
python -m scripts.make_tls_certs --host engine.example.org --print-env
ENGINE_HOST=0.0.0.0 python run_engine.py
```

`run_engine.py` then serves HTTPS only and requires a client certificate
signed by the authority just created. It refuses to bind a public address
without TLS. Keep `backend/.env` there with `ENGINE_API_KEY`, `PII_HASH_KEY`
and (for the earlier-screenings check) `DATABASE_URL`. Open port 8000 only to
the internet-facing firewall rule you need; the certificate requirement is
what keeps other callers out.

`--print-env` prints `ENGINE_CA_CERT`, `ENGINE_CLIENT_CERT` and
`ENGINE_CLIENT_KEY` for step 3.

## 2. Fabric (optional)

```bash
bash fabric/network.sh up
```

For a hosted gateway the peer's port 7051 must be reachable from Vercel, and
its TLS certificate must carry the public name (add it under `SANS` in
`fabric/network/crypto-config.yaml` before the first `up`). Collect, as
base64:

- `FABRIC_TLS_CERT`: `organizations/peerOrganizations/ssb.pehchaan.local/peers/peer0.ssb.pehchaan.local/tls/ca.crt`
- `FABRIC_CLIENT_CERT`: `.../users/User1@ssb.pehchaan.local/msp/signcerts/*.pem`
- `FABRIC_CLIENT_KEY`: `.../users/User1@ssb.pehchaan.local/msp/keystore/priv_sk`

Without these variables the hosted gateway simply does not anchor; sealing
and the PostgreSQL chain work as before.

## 3. Vercel project

- Root directory: `SIH-2026/frontend` (it contains `vercel.json`).
- Build: `npm run build` produces `dist/` (dashboard) and
  `dist-server/app.cjs` (the bundled gateway that `api/index.js` loads).
- Environment variables (Production):

| Variable | Value |
|---|---|
| `NEON_DATABASE_URL` | Neon connection string |
| `JWT_SECRET`, `HMAC_SECRET` | long random strings |
| `ENGINE_API_KEY`, `PII_HASH_KEY` | the same values as the engine's `backend/.env` |
| `ANCHOR_SIGNING_KEY` | base64 of an Ed25519 private key in PEM |
| `PYTHON_API_URL` | `https://engine.example.org:8000` |
| `ENGINE_CA_CERT`, `ENGINE_CLIENT_CERT`, `ENGINE_CLIENT_KEY` | from step 1 |
| `CRON_SECRET` | long random string |
| `FABRIC_*` | from step 2, if used |

Mark `ENGINE_CLIENT_KEY`, `FABRIC_CLIENT_KEY`, `ANCHOR_SIGNING_KEY` and the
secrets as sensitive. The gateway exits at start if a secret is missing.

## 4. What behaves differently on Vercel

| Behaviour | Checkpoint machine | Vercel |
|---|---|---|
| Batch sealing, Fabric anchoring, retention | Timer, every 10 minutes | `vercel.json` cron calls `/api/cron/maintenance` once a day (the Hobby plan allows daily crons only; Pro can use `*/10 * * * *`). Admins can also seal on demand. |
| Database unreachable during a scan | Scan, audit entry and log are queued on disk and synced later | The request fails with an error. There is no durable disk to queue on. |
| Sign-in while the database is unreachable | Verified against the sealed local cache | Refused. |
| Session renewal while the database is unreachable | Session kept until it expires | Refused. |
| Login rate limiting | One counter for the process | Per function instance, so the limit is looser under load. |
| Request size | 32 MB | 4.5 MB. The dashboard shrinks the document image and live photo to fit. |
| Engine link | Loopback, or mutual TLS when certificates exist | Mutual TLS required. |

A scan takes about 5 to 10 seconds with a GPU engine; the function's
`maxDuration` is 60 seconds. A CPU-only engine is slower and may need Vercel
Pro's longer limit.

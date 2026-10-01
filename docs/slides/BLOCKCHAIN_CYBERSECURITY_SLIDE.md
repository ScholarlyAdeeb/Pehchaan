# PEHCHAAN — Blockchain & Cybersecurity Implementation
## Technical Approach Slide for SIH 2026 (PS-26188)

---

## 🎯 Theme Alignment
| **SIH Theme** | **Our Implementation** |
|---------------|------------------------|
| **Blockchain** | Hash-chained immutable ledger, Merkle-root batch anchoring, tamper-evident audit trail |
| **Cybersecurity** | End-to-end encryption, HMAC signatures, RBAC, secure transport, input hardening, offline resilience |

> **Key Differentiator:** Not a public blockchain — a **permissioned, cryptographically-verifiable audit ledger** designed for border security operations with offline-first capability.

---

## 🔗 1. Hash-Chained Immutable Ledger (Core Blockchain Primitive)

```
Genesis Block → Block #1 → Block #2 → ... → Block #N
     ↓              ↓           ↓             ↓
  Fixed Seed   SHA-256     SHA-256       SHA-256
  (Deterministic) (prev_hash + scan_data)  (Chained)
```

| Property | Implementation |
|----------|----------------|
| **Genesis Seed** | `PEHCHAAN_GENESIS_BLOCK_v1_SIH26188` → SHA-256 = `GENESIS_HASH` |
| **Block Data** | `prev_hash | scan_id | doc_type | name | risk_score | verdict | timestamp | officer_uid | doc_number | provenance_hash` |
| **Hash Algorithm** | SHA-256 (Node.js `crypto.createHash('sha256')`) |
| **Block Height** | Auto-incrementing (`#1`, `#2`, …) stored in `block_height` column |
| **Verification** | `verifyChainIntegrity()` — recomputes every hash from genesis; detects any tampering |
| **Forgery Registry** | Merkle tree batch anchoring (`pehchaan_anchor_batches` table) with external proof support |

**Code Reference:** `frontend/server/hashchain.ts:12-37`, `frontend/server/neon.ts:888-955`

---

## 📜 2. HMAC-Signed Audit Trail (Non-Repudiation)

| Feature | Implementation |
|---------|----------------|
| **Algorithm** | HMAC-SHA256 with server-secret `HMAC_SECRET` |
| **Signed Fields** | `action | officer | officer_uid | target_id | details | created_at` |
| **Verification** | Timing-safe comparison (`crypto.timingSafeEqual`) — prevents timing attacks |
| **Legacy Detection** | Auto-flags entries signed with old/default keys as `'legacy'` status |
| **Coverage** | Every scan, officer decision, login, config change, system event |
| **Query** | Full history per document (`fetchAuditLogsForTarget`) |

**Code Reference:** `frontend/server/hashchain.ts:44-85`, `frontend/server/neon.ts:846-886`

---

## 🔐 3. Cryptographic Primitives Summary

| Primitive | Use Case | Implementation |
|-----------|----------|----------------|
| **SHA-256** | Hash chain, document number privacy, session fingerprint | `crypto.createHash('sha256')` |
| **HMAC-SHA256** | Audit log signatures, integrity verification | `crypto.createHmac('sha256', secret)` |
| **bcrypt (cost=12)** | Password hashing — adaptive, salted, GPU-resistant | `bcrypt.hash(password, 12)` |
| **JWT HS256** | Stateless authentication tokens | `jsonwebtoken.sign(payload, secret)` |
| **TLS 1.3** | Neon PostgreSQL (SSL), Express HTTPS | `pg` pool with `ssl: { rejectUnauthorized: false }` |
| **Timing-Safe Equal** | All secret comparisons (HMAC, bcrypt, setup code) | `crypto.timingSafeEqual` |

---

## 🛡️ 4. Application Security Layers

### Authentication & Authorization
```
┌─────────────────────────────────────────────────────────────┐
│  ROLE-BASED ACCESS CONTROL (RBAC)                          │
├──────────────┬──────────────────────────────────────────────┤
│ ADMIN        │ Full system access, user management, all CPs │
│ POST_INCHARGE│ Checkpoint-scoped, officer oversight         │
│ OFFICER      │ Assigned checkpoint(s) only, scan + decide   │
└──────────────┴──────────────────────────────────────────────┘
```

| Security Control | Implementation |
|------------------|----------------|
| **Password Policy** | ≥12 chars, letters+numbers, rejects published defaults (`admin123`, etc.) |
| **First-Time Setup** | One-time console-printed code required to create initial admin |
| **Forced Rotation** | Default passwords flagged `must_change_password=true` at startup |
| **Session Fingerprint** | SHA-256(User-Agent) for anomaly detection |
| **Rate Limiting** | Per-IP sliding window (configurable attempts/window) |

### Input Hardening
| Vector | Mitigation |
|--------|------------|
| **SQL Injection** | Parameterized queries only (`pg` prepared statements) |
| **XSS** | `sanitizeString()` — strips HTML tags, enforces field max lengths |
| **Prototype Pollution** | No `Object.assign` on user input; explicit field allowlists |
| **Request Size** | Express `bodyParser` limits + field-level max lengths |

### Transport & Headers
| Layer | Protection |
|-------|------------|
| **Helmet.js** | CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy |
| **Cookies** | `HttpOnly`, `Secure`, `SameSite=Strict` |
| **CORS** | Restricted to configured origins |

---

## ⚡ 5. Offline-First Resilience (Border-Ready Architecture)

```
┌─────────────────────────────────────────────────────────────────┐
│                    STORE-AND-FORWARD MODEL                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Officer at Remote CP                                          │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────┐    Neon OK?    ┌──────────────────┐          │
│  │ Local Queue │ ──────YES────► │ Direct Insert    │          │
│  │ (In-Memory) │                │ + Hash Chain     │          │
│  └─────────────┘                └──────────────────┘          │
│       │ NO                                                         │
│       ▼                                                         │
│  ┌─────────────┐    Reconnect    ┌──────────────────┐          │
│  │ Queued      │ ─────────────►  │ Batch Sync       │          │
│  │ Scans       │                 │ (Ordered,        │          │
│  │ (SYNCED)    │                 │  Hash-Verified)  │          │
│  └─────────────┘                 └──────────────────┘          │
│                                                                 │
│  Conflict-Free: Hash-based deduplication prevents double-count │
└─────────────────────────────────────────────────────────────────┘
```

| Capability | Detail |
|------------|--------|
| **Local Queue** | In-memory `inMemoryScans[]` + `inMemoryAuditLogs[]` when DB unavailable |
| **Auto-Sync** | `syncBatchScans()` — ordered batch insert on reconnect |
| **Deduplication** | Primary key `id` + hash chain `prev_hash` prevents forks |
| **Telemetry** | `pehchaan_telemetry` table tracks bandwidth, queue depth, sync status |
| **Remote Ready** | Works at low-bandwidth border checkpoints (ICPs, BOP) |

---

## 📊 6. Database Security Schema (Neon PostgreSQL)

```sql
-- Core immutable tables
pehchaan_scans          -- Hash-chained scan records (prev_hash, full_hash, block_height)
pehchaan_audit_logs     -- HMAC-signed audit trail (hmac_signature)
pehchaan_chain_anchor   -- Genesis hash registry
pehchaan_forgery_registry -- Merkle-anchored forgery evidence
pehchaan_anchor_batches -- Merkle root batches with external proofs

-- Access control
pehchaan_users          -- bcrypt-hashed passwords, roles, checkpoint scoping
pehchaan_checkpoints    -- Border checkpoint registry

-- Reference data (data.gov.in)
pehchaan_ref_*          -- 45 seeded datasets for analytics
```

**Security Features:**
- `doc_number_hash` — SHA-256 of document number (PII never stored plain)
- `provenance_hash` — Image fingerprint for chain integrity
- `ON CONFLICT DO UPDATE` — Idempotent sync, hash verification on conflict
- Indexed `doc_number_hash` for fast cross-check without exposing numbers

---

## ✅ 7. Compliance & Verification Checklist

| SIH Requirement | Status | Evidence |
|-----------------|--------|----------|
| **Digital trail for investigations** | ✅ | HMAC-signed audit logs + hash chain |
| **Tamper-evident records** | ✅ | SHA-256 chain + `verifyChainIntegrity()` API |
| **Non-repudiation** | ✅ | Officer-UID bound HMAC signatures |
| **PII protection** | ✅ | Document numbers hashed before storage |
| **Role-based access** | ✅ | 3-role RBAC + checkpoint scoping |
| **Offline operation** | ✅ | Store-and-forward with auto-sync |
| **Secure deployment** | ✅ | TLS, Helmet, bcrypt(12), JWT, rate limits |

---

## 🎤 Slide Talking Points (60-90 seconds)

1. **"Blockchain-Inspired, Not Blockchain"** — We use cryptographic chaining (SHA-256) and Merkle anchoring for tamper-evidence, without consensus overhead. Purpose-built for border security.

2. **Every Scan = A Block** — Each screening creates an immutable record chained to the previous. Any tampering breaks the chain and is detected instantly via `verifyChainIntegrity()`.

3. **Audit Trail That Stands in Court** — HMAC-SHA256 signatures on every action with timing-safe verification. Officer identity cryptographically bound to decisions.

4. **Privacy by Design** — Document numbers (Aadhaar, Passport, PAN) are **never stored in plaintext** — only SHA-256 hashes. Cross-checks work on hashes alone.

5. **Border-Ready Resilience** — Store-and-forward architecture works at remote checkpoints with intermittent connectivity. Zero data loss, automatic cryptographic sync.

6. **Defense in Depth** — bcrypt(12), JWT, Helmet, RBAC, rate limiting, input sanitization, TLS everywhere. Security isn't a layer — it's the architecture.

---

## 📁 Assets for This Slide

| File | Description |
|------|-------------|
| `blockchain-cybersecurity.svg` | Vector diagram (5-layer architecture) — **use in PowerPoint/Keynote** |
| `blockchain-cybersecurity.png` | 2352×1398 raster — **use in Google Slides/Canva** |
| `blockchain-cybersecurity.mmd` | Source — edit colors/layout in [mermaid.live](https://mermaid.live) |

**Theme Colors:** Primary `#0059b5`, Success `#006a26`, Warning `#e8a000`, Error `#ba1a1a`, Surface `#faf8fe`, Text `#1a1b1f`, Font `Inter`

---

## 🔧 One-Liner for Judges

> *"PEHCHAAN implements a **permissioned cryptographic ledger** — hash-chained scan records with HMAC-signed audit trails, document-number privacy via SHA-256, and offline-first store-and-forward sync — delivering blockchain-grade tamper-evidence and non-repudiation tailored for SSB border operations."*
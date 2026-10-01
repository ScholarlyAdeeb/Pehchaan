import crypto from 'crypto';
import { anchorBatch, fabricEnabled, fabricStatus, listAnchors } from './fabric.ts';
import { getNeonPool, initNeonSchema, insertAuditLog, insertSystemLog, verifyChainIntegrity } from './neon.ts';
import type { AuthPayload } from './security.ts';
import { inScope, scopeOf } from './security.ts';

const sha256 = (s: string | Buffer) => crypto.createHash('sha256').update(s).digest('hex');

async function db() {
  const pool = getNeonPool();
  if (!pool) throw Object.assign(new Error('Database not connected'), { status: 503 });
  await initNeonSchema();
  return pool;
}

function fail(status: number, message: string): never {
  throw Object.assign(new Error(message), { status });
}

// =====================================================================
// Officer decisions — two-person rule
// =====================================================================
// Clearing a traveller the system did NOT rate CLEAR needs a second person
// (Post In-Charge or Admin, not the same user) to co-sign before it takes
// effect. Every step is written to the HMAC-signed audit log.

type Decision = 'clear' | 'secondary' | 'reject';
const DECISION_ACTIONS: Record<Decision, string> = {
  clear: 'OFFICER_DECISION_CLEAR',
  secondary: 'OFFICER_DECISION_SECONDARY',
  reject: 'OFFICER_DECISION_REJECT',
};

export async function recordDecision(user: AuthPayload, scanId: string, body: any) {
  const decision = String(body?.decision || '') as Decision;
  const notes = String(body?.notes || '').trim().slice(0, 2000);
  if (!DECISION_ACTIONS[decision]) fail(400, 'Unknown decision.');
  const pool = await db();
  const scan = (await pool.query(
    'SELECT id, risk_verdict, risk_score, checkpoint_id, presenter_name, hash_proof, analysis, image_fingerprint FROM pehchaan_scans WHERE id = $1',
    [scanId],
  )).rows[0];
  if (!scan) fail(404, 'Scan not found.');
  if (!inScope(user, scan.checkpoint_id)) fail(403, 'This record belongs to another checkpoint.');
  const override = decision === 'clear' && scan.risk_verdict !== 'CLEAR';
  if (override && !notes) fail(400, 'Clearing a flagged traveller needs a written reason.');

  const status = override ? 'pending_cosign' : 'final';
  const row = (await pool.query(
    `INSERT INTO pehchaan_decisions (scan_id, decision, status, officer, officer_uid, notes, system_verdict, system_score, checkpoint_id)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *`,
    [scanId, decision, status, user.name, user.userId, notes, scan.risk_verdict, scan.risk_score, scan.checkpoint_id],
  )).rows[0];

  await insertAuditLog({
    action: override ? 'OFFICER_OVERRIDE_REQUESTED' : DECISION_ACTIONS[decision],
    officer: user.name, officer_uid: user.userId, target_id: scanId, remote_station: scan.checkpoint_id || '',
    details: `${override ? 'Requested to clear a ' + scan.risk_verdict + ' traveller — awaiting In-Charge co-signature' : decision.toUpperCase()}` +
      ` (system ${scan.risk_verdict} ${scan.risk_score}/100). Decision #${row.id}.${notes ? ' Reason: ' + notes : ''}`,
    hash_proof: scan.hash_proof,
  });

  let registered = false;
  if (decision === 'reject') registered = await registerForgery(user, scan);
  return { ...row, registered };
}

export async function pendingCosigns(user: AuthPayload) {
  if (user.role === 'OFFICER') fail(403, 'Only a Post In-Charge or Admin can co-sign.');
  const pool = await db();
  const scope = scopeOf(user);
  const rows = (await pool.query(
    `SELECT d.*, s.presenter_name, s.doc_code, s.lane FROM pehchaan_decisions d
     JOIN pehchaan_scans s ON s.id = d.scan_id
     WHERE d.status = 'pending_cosign' ${scope ? 'AND d.checkpoint_id = ANY($1)' : ''}
     ORDER BY d.created_at DESC LIMIT 100`,
    scope ? [scope] : [],
  )).rows;
  return rows;
}

export async function decisionsForScan(user: AuthPayload, scanId: string) {
  const pool = await db();
  const rows = (await pool.query('SELECT * FROM pehchaan_decisions WHERE scan_id = $1 ORDER BY created_at', [scanId])).rows;
  if (rows[0] && !inScope(user, rows[0].checkpoint_id)) fail(403, 'This record belongs to another checkpoint.');
  return rows;
}

export async function cosign(user: AuthPayload, decisionId: number, body: any) {
  if (user.role === 'OFFICER') fail(403, 'Only a Post In-Charge or Admin can co-sign.');
  const approve = body?.approve === true;
  const notes = String(body?.notes || '').trim().slice(0, 2000);
  if (!notes) fail(400, 'Co-signing needs a note on what you checked.');
  const pool = await db();
  const d = (await pool.query('SELECT * FROM pehchaan_decisions WHERE id = $1', [decisionId])).rows[0];
  if (!d) fail(404, 'Decision not found.');
  if (d.status !== 'pending_cosign') fail(409, 'This decision is not waiting for a co-signature.');
  if (!inScope(user, d.checkpoint_id)) fail(403, 'This decision belongs to another checkpoint.');
  if (d.officer_uid === user.userId) fail(403, 'The same person cannot request and co-sign an override.');

  const status = approve ? 'cosigned' : 'cosign_refused';
  const updated = (await pool.query(
    `UPDATE pehchaan_decisions SET status = $1, cosigner = $2, cosigner_uid = $3, cosign_notes = $4, cosigned_at = NOW()
     WHERE id = $5 AND status = 'pending_cosign' RETURNING *`,
    [status, user.name, user.userId, notes, decisionId],
  )).rows[0];
  if (!updated) fail(409, 'Someone else acted on this decision first.');
  await insertAuditLog({
    action: approve ? 'OVERRIDE_COSIGNED' : 'OVERRIDE_REFUSED',
    officer: user.name, officer_uid: user.userId, target_id: d.scan_id, remote_station: d.checkpoint_id || '',
    details: `${approve ? 'Co-signed' : 'Refused'} ${d.officer}'s request to clear a ${d.system_verdict} traveller (decision #${d.id}). Note: ${notes}`,
    hash_proof: '',
  });
  return updated;
}

// =====================================================================
// Shared forged-document registry (no personal data), hash-chained
// =====================================================================

async function registerForgery(user: AuthPayload, scan: any): Promise<boolean> {
  const fp = scan.analysis?.image_fingerprint;
  if (!fp?.page) return false;
  const failed = (scan.analysis?.evaluation || []).filter((r: any) => r.status === 'fail').map((r: any) => r.check);
  if (!failed.length) return false; // only documents with evidence of forgery, not e.g. identity mismatches
  const pool = await db();
  const prev = (await pool.query('SELECT entry_hash FROM pehchaan_forgery_registry ORDER BY id DESC LIMIT 1')).rows[0];
  const prevHash = prev?.entry_hash || sha256('PEHCHAAN_FORGERY_REGISTRY_GENESIS');
  const types = failed.join(', ');
  const docType = scan.analysis?.document_type || '';
  const entryHash = sha256([prevHash, fp.page, fp.portrait || '', types, docType, scan.checkpoint_id || ''].join('|'));
  await pool.query(
    `INSERT INTO pehchaan_forgery_registry (page_hash, portrait_hash, tamper_types, doc_type, checkpoint_id, source_scan, prev_hash, entry_hash)
     VALUES ($1,$2,$3,$4,$5,$6,$7,$8)`,
    [fp.page, fp.portrait || null, types, docType, scan.checkpoint_id || null, scan.id, prevHash, entryHash],
  );
  await insertSystemLog({
    actor: user.name, role: user.role, checkpoint: scan.checkpoint_id || '',
    event: 'forgery_registered', status: 'success', reference_id: scan.id,
  });
  return true;
}

export async function listRegistry() {
  const pool = await db();
  const rows = (await pool.query('SELECT * FROM pehchaan_forgery_registry ORDER BY id')).rows;
  let expected = sha256('PEHCHAAN_FORGERY_REGISTRY_GENESIS');
  let valid = true;
  for (const r of rows) {
    const h = sha256([expected, r.page_hash, r.portrait_hash || '', r.tamper_types || '', r.doc_type || '', r.checkpoint_id || ''].join('|'));
    if (r.prev_hash !== expected || r.entry_hash !== h) { valid = false; break; }
    expected = r.entry_hash;
  }
  return { valid, entries: rows.reverse() };
}

// =====================================================================
// Merkle batching + signed roots + per-scan receipts
// =====================================================================
// Scans are sealed in batches: the batch's Merkle root is signed with the
// server's Ed25519 key (and optionally timestamped by OpenTimestamps). Each
// scan gets a receipt — its hash plus the sibling hashes up to the root — so
// anyone can prove the record existed, unchanged, when the batch was sealed,
// without seeing any other record.

const hashPair = (a: string, b: string) => sha256(Buffer.from(a + b, 'hex'));

function merkleLevels(leaves: string[]): string[][] {
  const levels = [leaves];
  while (levels[levels.length - 1].length > 1) {
    const cur = levels[levels.length - 1];
    const next: string[] = [];
    for (let i = 0; i < cur.length; i += 2) next.push(hashPair(cur[i], cur[i + 1] ?? cur[i]));
    levels.push(next);
  }
  return levels;
}

function signingKey() {
  const pem = Buffer.from(process.env.ANCHOR_SIGNING_KEY || '', 'base64').toString('utf8');
  const privateKey = crypto.createPrivateKey(pem);
  const publicKey = crypto.createPublicKey(privateKey).export({ type: 'spki', format: 'pem' }).toString();
  return { privateKey, publicKey };
}

const batchMessage = (b: { merkle_root: string; leaf_count: number; first_scan: string; last_scan: string }) =>
  `PEHCHAAN-BATCH|${b.merkle_root}|${b.leaf_count}|${b.first_scan}|${b.last_scan}`;

async function timestampExternally(root: string): Promise<string | null> {
  if (process.env.ANCHOR_OPENTIMESTAMPS !== 'true') return null;
  try {
    const res = await fetch('https://a.pool.opentimestamps.org/digest', {
      method: 'POST',
      body: Buffer.from(root, 'hex'),
      signal: AbortSignal.timeout(10_000),
    });
    if (!res.ok) return null;
    return `opentimestamps:${Buffer.from(await res.arrayBuffer()).toString('base64')}`;
  } catch {
    return null;
  }
}

export async function sealBatch(actor = 'system'): Promise<any | null> {
  const pool = await db();
  const rows = (await pool.query(
    "SELECT id, full_hash FROM pehchaan_scans WHERE batch_id IS NULL AND full_hash IS NOT NULL AND full_hash <> '' ORDER BY created_at ASC LIMIT 1024",
  )).rows;
  if (!rows.length) return null;
  const root = merkleLevels(rows.map((r: any) => r.full_hash)).pop()![0];
  const { privateKey, publicKey } = signingKey();
  const draft = { merkle_root: root, leaf_count: rows.length, first_scan: rows[0].id, last_scan: rows[rows.length - 1].id };
  const signature = crypto.sign(null, Buffer.from(batchMessage(draft)), privateKey).toString('base64');
  const external = await timestampExternally(root);
  const batch = (await pool.query(
    `INSERT INTO pehchaan_anchor_batches (merkle_root, leaf_count, first_scan, last_scan, signature, public_key, external_proof)
     VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *`,
    [root, rows.length, draft.first_scan, draft.last_scan, signature, publicKey, external],
  )).rows[0];
  await pool.query('UPDATE pehchaan_scans SET batch_id = $1 WHERE id = ANY($2)', [batch.id, rows.map((r: any) => r.id)]);
  await insertSystemLog({ actor, role: 'SYSTEM', checkpoint: '', event: 'batch_sealed', status: 'success', reference_id: `batch ${batch.id}` });
  // Sealing must not depend on the ledger being reachable: a batch that could
  // not be anchored now is picked up by anchorPendingBatches() later.
  const anchored = await anchorOnFabric(batch).catch((err) => {
    console.warn(`Batch #${batch.id} sealed but not yet anchored on Fabric: ${(err as Error).message}`);
    return null;
  });
  return anchored ? { ...batch, ...anchored } : batch;
}

async function anchorOnFabric(batch: any): Promise<{ fabric_tx: string; fabric_anchored_at: string } | null> {
  if (!fabricEnabled()) return null;
  const anchor = await anchorBatch(batch);
  const pool = await db();
  await pool.query('UPDATE pehchaan_anchor_batches SET fabric_tx = $1, fabric_anchored_at = $2 WHERE id = $3',
    [anchor.txId, anchor.anchoredAt, batch.id]);
  await insertSystemLog({ actor: 'system', role: 'SYSTEM', checkpoint: '', event: 'batch_anchored_fabric', status: 'success', reference_id: `batch ${batch.id}` });
  return { fabric_tx: anchor.txId, fabric_anchored_at: anchor.anchoredAt };
}

/** Anchors batches sealed before Fabric was configured, or while the peer was unreachable. */
export async function anchorPendingBatches(limit = 25): Promise<number> {
  if (!fabricEnabled()) return 0;
  const pool = await db();
  const pendingRows = (await pool.query(
    'SELECT * FROM pehchaan_anchor_batches WHERE fabric_tx IS NULL ORDER BY id ASC LIMIT $1', [limit])).rows;
  let done = 0;
  for (const batch of pendingRows) {
    await anchorOnFabric(batch); // stops at the first failure; the next run retries from there
    done++;
  }
  return done;
}

/**
 * Compares every batch root in the database with the root the Fabric ledger
 * recorded when the batch was sealed. A difference means the database copy
 * of that batch was rewritten after sealing.
 */
export async function verifyAgainstFabric() {
  const status = await fabricStatus();
  if (!status.enabled || !status.reachable) return { ...status, checked: 0, mismatched: [], missing: [] };
  const pool = await db();
  const batches = (await pool.query('SELECT id, merkle_root, fabric_tx FROM pehchaan_anchor_batches ORDER BY id ASC')).rows;
  const onLedger = new Map((await listAnchors()).map((a) => [a.batchId, a]));
  const mismatched: { batch: number; database: string; ledger: string }[] = [];
  const missing: number[] = [];
  for (const b of batches) {
    const anchor = onLedger.get(String(b.id));
    if (!anchor) missing.push(b.id);
    else if (anchor.merkleRoot !== b.merkle_root) mismatched.push({ batch: b.id, database: b.merkle_root, ledger: anchor.merkleRoot });
  }
  return { ...status, checked: batches.length, mismatched, missing };
}

export async function listBatches() {
  const pool = await db();
  const batches = (await pool.query('SELECT * FROM pehchaan_anchor_batches ORDER BY id DESC LIMIT 100')).rows;
  const unsealed = Number((await pool.query('SELECT COUNT(*) FROM pehchaan_scans WHERE batch_id IS NULL')).rows[0].count);
  return {
    batches, unsealed, publicKey: signingKey().publicKey, openTimestamps: process.env.ANCHOR_OPENTIMESTAMPS === 'true',
    fabric: await fabricStatus(),
  };
}

export async function receiptFor(user: AuthPayload, scanId: string) {
  const pool = await db();
  const scan = (await pool.query('SELECT id, full_hash, batch_id, checkpoint_id FROM pehchaan_scans WHERE id = $1', [scanId])).rows[0];
  if (!scan) fail(404, 'Scan not found.');
  if (!inScope(user, scan.checkpoint_id)) fail(403, 'This record belongs to another checkpoint.');
  if (!scan.batch_id) return { sealed: false, scanId };
  const batch = (await pool.query('SELECT * FROM pehchaan_anchor_batches WHERE id = $1', [scan.batch_id])).rows[0];
  const members = (await pool.query('SELECT id, full_hash FROM pehchaan_scans WHERE batch_id = $1 ORDER BY created_at ASC', [scan.batch_id])).rows;
  const levels = merkleLevels(members.map((m: any) => m.full_hash));
  let index = members.findIndex((m: any) => m.id === scanId);
  const path: { hash: string; side: 'left' | 'right' }[] = [];
  for (let l = 0; l < levels.length - 1; l++) {
    const level = levels[l];
    const sibling = index % 2 === 0 ? (level[index + 1] ?? level[index]) : level[index - 1];
    path.push({ hash: sibling, side: index % 2 === 0 ? 'right' : 'left' });
    index = Math.floor(index / 2);
  }
  return {
    sealed: true,
    scanId,
    leaf: scan.full_hash,
    path,
    batch: {
      id: batch.id, merkle_root: batch.merkle_root, leaf_count: batch.leaf_count,
      first_scan: batch.first_scan, last_scan: batch.last_scan, sealed_at: batch.created_at,
      signature: batch.signature, public_key: batch.public_key, external_proof: batch.external_proof,
    },
  };
}

/** Stateless check anyone can run on a receipt: recomputes the root and checks the signature. */
export function verifyReceipt(receipt: any) {
  try {
    let h = String(receipt.leaf);
    for (const step of receipt.path || []) h = step.side === 'right' ? hashPair(h, step.hash) : hashPair(step.hash, h);
    const b = receipt.batch;
    const rootMatches = h === b.merkle_root;
    const signatureValid = crypto.verify(null, Buffer.from(batchMessage(b)), crypto.createPublicKey(b.public_key), Buffer.from(b.signature, 'base64'));
    const trustedKey = b.public_key.trim() === signingKey().publicKey.trim();
    return { rootMatches, signatureValid, trustedKey, computedRoot: h, valid: rootMatches && signatureValid };
  } catch (err: any) {
    return { valid: false, error: err?.message || 'Malformed receipt' };
  }
}

// =====================================================================
// Insider-threat analytics (UEBA) over data the system already records
// =====================================================================

export async function insiderAlerts(days = 30) {
  const pool = await db();
  const since = `NOW() - INTERVAL '${Math.max(1, Math.min(365, Math.floor(days)))} days'`;
  const scans = (await pool.query(
    `SELECT officer, officer_uid, risk_verdict, doc_number_hash, checkpoint_id,
            EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Kolkata')::int AS hour, created_at
     FROM pehchaan_scans WHERE created_at > ${since} AND officer_uid IS NOT NULL`,
  )).rows;
  const decisions = (await pool.query(`SELECT * FROM pehchaan_decisions WHERE created_at > ${since}`)).rows;
  const failures = (await pool.query(
    `SELECT actor, COUNT(*)::int AS n FROM pehchaan_system_logs
     WHERE event = 'authentication_failure' AND timestamp > ${since} GROUP BY actor`,
  )).rows;

  type Stat = { officer: string; uid: string; scans: number; flagged: number; overrides: number; refused: number; offHours: number; repeats: number };
  const stats = new Map<string, Stat>();
  const get = (uid: string, officer: string) => {
    if (!stats.has(uid)) stats.set(uid, { officer, uid, scans: 0, flagged: 0, overrides: 0, refused: 0, offHours: 0, repeats: 0 });
    return stats.get(uid)!;
  };
  const seen = new Map<string, number>();
  for (const s of scans) {
    const st = get(s.officer_uid, s.officer);
    st.scans++;
    if (s.risk_verdict !== 'CLEAR') st.flagged++;
    if (s.hour >= 22 || s.hour < 5) st.offHours++;
    if (s.doc_number_hash) {
      const k = `${s.officer_uid}|${s.doc_number_hash}`;
      seen.set(k, (seen.get(k) || 0) + 1);
    }
  }
  for (const [k, n] of seen) if (n >= 3) get(k.split('|')[0], '').repeats += 1;
  for (const d of decisions) {
    if (d.decision === 'clear' && d.system_verdict !== 'CLEAR') get(d.officer_uid, d.officer).overrides++;
    if (d.status === 'cosign_refused') get(d.officer_uid, d.officer).refused++;
  }

  const alerts: { severity: 'high' | 'medium' | 'low'; officer: string; rule: string; detail: string }[] = [];
  for (const s of stats.values()) {
    const rate = s.flagged ? s.overrides / s.flagged : 0;
    if (s.overrides >= 3 && rate >= 0.3) alerts.push({ severity: 'high', officer: s.officer, rule: 'Frequent overrides', detail: `Asked to clear ${s.overrides} of ${s.flagged} flagged travellers (${Math.round(rate * 100)}%).` });
    else if (s.overrides >= 2) alerts.push({ severity: 'medium', officer: s.officer, rule: 'Repeated overrides', detail: `${s.overrides} requests to clear flagged travellers.` });
    if (s.refused >= 1) alerts.push({ severity: 'medium', officer: s.officer, rule: 'Override refused by In-Charge', detail: `${s.refused} override request(s) were refused on review.` });
    if (s.offHours >= 5 && s.offHours / s.scans >= 0.4) alerts.push({ severity: 'low', officer: s.officer, rule: 'Off-hours activity', detail: `${s.offHours} of ${s.scans} screenings between 22:00 and 05:00 IST.` });
    if (s.repeats >= 1) alerts.push({ severity: 'medium', officer: s.officer, rule: 'Same document screened repeatedly', detail: `${s.repeats} document number(s) screened 3+ times by this officer.` });
  }
  for (const f of failures) {
    if (f.n >= 5) alerts.push({ severity: f.n >= 10 ? 'high' : 'medium', officer: f.actor, rule: 'Failed sign-ins', detail: `${f.n} failed sign-in attempts.` });
  }
  const order = { high: 0, medium: 1, low: 2 };
  return {
    windowDays: days,
    officers: [...stats.values()].sort((a, b) => b.overrides - a.overrides || b.scans - a.scans),
    alerts: alerts.sort((a, b) => order[a.severity] - order[b.severity]),
  };
}

// =====================================================================
// Incident report (CERT-In directions: report within 6 hours, keep logs 180 days)
// =====================================================================

export async function incidentReport(user: AuthPayload, from?: string, to?: string) {
  const pool = await db();
  const start = from ? new Date(from) : new Date(Date.now() - 24 * 3600 * 1000);
  const end = to ? new Date(to) : new Date();
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) fail(400, 'Invalid date range.');
  const range = [start.toISOString(), end.toISOString()];
  const [systemLogs, auditLogs, decisions, registry] = await Promise.all([
    pool.query('SELECT * FROM pehchaan_system_logs WHERE timestamp BETWEEN $1 AND $2 ORDER BY timestamp', range),
    pool.query('SELECT * FROM pehchaan_audit_logs WHERE created_at BETWEEN $1 AND $2 ORDER BY created_at', range),
    pool.query('SELECT * FROM pehchaan_decisions WHERE created_at BETWEEN $1 AND $2 ORDER BY created_at', range),
    pool.query('SELECT * FROM pehchaan_forgery_registry WHERE created_at BETWEEN $1 AND $2 ORDER BY created_at', range),
  ]);
  const report = {
    title: 'PEHCHAAN security incident report',
    generated_at: new Date().toISOString(),
    generated_by: `${user.name} (${user.userId})`,
    window: { from: range[0], to: range[1] },
    reporting_note: 'CERT-In Directions (28 Apr 2022): report cyber incidents to CERT-In within 6 hours of noticing them; retain logs for 180 days.',
    chain_integrity: await verifyChainIntegrity(),
    insider_alerts: (await insiderAlerts(30)).alerts,
    counts: {
      system_events: systemLogs.rowCount, audit_entries: auditLogs.rowCount,
      decisions: decisions.rowCount, forgeries_registered: registry.rowCount,
      failed_sign_ins: systemLogs.rows.filter((r: any) => r.event === 'authentication_failure').length,
    },
    system_logs: systemLogs.rows,
    audit_logs: auditLogs.rows,
    decisions: decisions.rows,
    forgery_registry: registry.rows,
  };
  const body = JSON.stringify(report);
  return { ...report, report_sha256: sha256(body) };
}

// =====================================================================
// Retention: raw OCR text and images are personal data; drop them from
// stored analyses after RETENTION_DAYS. Verdicts, evaluations, hashes and
// logs are kept (logs >= 180 days as CERT-In requires).
// =====================================================================

export async function applyRetention(): Promise<number> {
  const days = Math.max(1, Number(process.env.RETENTION_DAYS || 30));
  const pool = getNeonPool();
  if (!pool) return 0;
  await initNeonSchema();
  const res = await pool.query(
    `UPDATE pehchaan_scans SET analysis = jsonb_set(
        jsonb_set(jsonb_set(jsonb_set(analysis,
          '{ocr,raw_text}', '"[removed after retention period]"'),
          '{tampering,ela_heatmap}', 'null'),
          '{face,document_face_thumb}', 'null'),
          '{face,live_face_thumb}', 'null')
     WHERE analysis IS NOT NULL AND created_at < NOW() - ($1 || ' days')::interval
       AND analysis->'ocr'->>'raw_text' IS DISTINCT FROM '[removed after retention period]'`,
    [String(days)],
  );
  if (res.rowCount) {
    await insertSystemLog({ actor: 'system', role: 'SYSTEM', checkpoint: '', event: 'retention_applied', status: 'success', reference_id: `${res.rowCount} scans` });
  }
  return res.rowCount || 0;
}

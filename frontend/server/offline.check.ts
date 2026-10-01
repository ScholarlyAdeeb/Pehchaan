// Manual check of the gateway's offline path:  npx tsx server/offline.check.ts
// Points the database at a dead local port, so nothing can reach the real one.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const DEAD = 'postgres://nobody:nothing@127.0.0.1:9/none';
process.env.NEON_DATABASE_URL = DEAD;
process.env.DATABASE_URL = DEAD;
process.env.OUTBOX_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'pehchaan-offline-'));
process.env.HMAC_SECRET ||= 'offline-check-only'; // signing key for this check; never a real one

const neon = await import('./neon.ts');
const { pending } = await import('./outbox.ts');
assert.equal(neon.getNeonConnectionString(), DEAD, 'refusing to run against a real database');

const scan = (id: string) => ({
  id, document_type: 'passport', doc_code: 'Passport', country_code: 'IND', country_name: 'India',
  presenter_name: 'Test Holder', risk_score: 0, risk_verdict: 'CLEAR', checksum_status: 'PASS',
  findings: 'No risk indicators found.', timestamp: 'now', local_time: new Date().toISOString(),
  lane: 'CP-TEST', officer: 'Tester', officer_uid: 'USR-TEST', hash_proof: '', full_hash: '', block_height: '',
  checkpoint_id: 'CP-TEST',
} as any);

let t = Date.now();
const first = await neon.insertScan(scan('SCN-OFFLINE-1'));
const firstMs = Date.now() - t;
assert.equal(first.sync_status, 'QUEUED_LOCAL');
assert.ok(first.full_hash, 'queued scan still carries a provisional hash');

await neon.insertAuditLog({
  action: 'SCREENING_CLEAR', officer: 'Tester', officer_uid: 'USR-TEST', target_id: 'SCN-OFFLINE-1',
  remote_station: 'CP-TEST', details: 'offline check', hash_proof: first.hash_proof,
} as any);
await neon.insertSystemLog({ actor: 'Tester', role: 'OFFICER', checkpoint: 'CP-TEST', event: 'screening_completed', status: 'CLEAR', reference_id: 'SCN-OFFLINE-1' } as any);

t = Date.now();
const second = await neon.insertScan(scan('SCN-OFFLINE-2'));
const secondMs = Date.now() - t;
assert.equal(second.sync_status, 'QUEUED_LOCAL');
assert.ok(secondMs < 500, `second offline scan should not wait for a connection timeout (took ${secondMs} ms)`);

const kinds = pending().map((i) => i.kind);
assert.deepEqual(kinds, ['scan', 'audit', 'system', 'scan']);
const audit = pending().find((i) => i.kind === 'audit')!.payload;
assert.ok(audit.hmac_signature && audit.created_at, 'audit entry is signed and timestamped when queued, not when synced');

const listed = await neon.fetchAllScans();
assert.deepEqual(listed.map((s: any) => s.id), ['SCN-OFFLINE-2', 'SCN-OFFLINE-1'], 'queued scans are listed while offline');
assert.equal((await neon.fetchScanById('SCN-OFFLINE-1'))?.id, 'SCN-OFFLINE-1');

const sync = await neon.syncOutboxToNeon();
assert.equal(sync.skipped, 'offline');
assert.equal(sync.remaining, 4);

console.log(`offline path ok: first write ${firstMs} ms, next ${secondMs} ms; queued ${kinds.join(', ')}; sync -> ${sync.skipped}, ${sync.remaining} kept`);
fs.rmSync(process.env.OUTBOX_DIR!, { recursive: true, force: true });
process.exit(0);

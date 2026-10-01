// Run with: npm test   (tsx server/outbox.check.ts; "*.test.ts" is git-ignored in this repo)
// Exercises the store-and-forward queue against fake database writers, so it
// never touches the real database.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

process.env.OUTBOX_DIR = fs.mkdtempSync(path.join(os.tmpdir(), 'pehchaan-outbox-'));
const { enqueue, pending, pendingCount, syncOutbox, outboxDir } = await import('./outbox.ts');

function fakeDatabase() {
  const db = { online: true, rejectScanId: '', written: [] as string[] };
  const write = (kind: string) => async (payload: any) => {
    if (!db.online) throw new Error('connect ETIMEDOUT');
    if (kind === 'scan' && payload.id === db.rejectScanId) throw new Error('value too long for type');
    db.written.push(`${kind}:${payload.id ?? payload.target_id ?? payload.event}`);
  };
  return { db, writers: { reachable: async () => db.online, scan: write('scan'), audit: write('audit'), system: write('system') } };
}

const reset = () => fs.rmSync(outboxDir(), { recursive: true, force: true });
let passed = 0;
async function test(name: string, fn: () => Promise<void> | void) {
  reset();
  await fn();
  passed++;
  console.log(`ok - ${name}`);
}

await test('nothing queued: sync is a no-op', async () => {
  const { writers } = fakeDatabase();
  assert.deepEqual(await syncOutbox(writers), { synced: 0, failed: 0, remaining: 0, skipped: 'empty' });
});

await test('records queued offline survive on disk and stay queued while the database is down', async () => {
  const { db, writers } = fakeDatabase();
  db.online = false;
  enqueue('scan', { id: 'SCN-1' });
  enqueue('audit', { target_id: 'SCN-1' });
  enqueue('system', { event: 'screening_completed' });
  assert.equal(pendingCount(), 3);
  assert.equal(fs.readdirSync(outboxDir()).filter((f) => f.endsWith('.json')).length, 3);
  const r = await syncOutbox(writers);
  assert.equal(r.skipped, 'offline');
  assert.equal(r.remaining, 3);
  assert.deepEqual(db.written, []);
});

await test('when the database returns, everything is written in the original order and the queue empties', async () => {
  const { db, writers } = fakeDatabase();
  enqueue('scan', { id: 'SCN-1' });
  enqueue('audit', { target_id: 'SCN-1' });
  enqueue('scan', { id: 'SCN-2' });
  enqueue('audit', { target_id: 'SCN-2' });
  const r = await syncOutbox(writers);
  assert.deepEqual([r.synced, r.failed, r.remaining], [4, 0, 0]);
  assert.deepEqual(db.written, ['scan:SCN-1', 'audit:SCN-1', 'scan:SCN-2', 'audit:SCN-2']);
});

await test('the same scan is not queued twice', () => {
  assert.equal(enqueue('scan', { id: 'SCN-1' }), true);
  assert.equal(enqueue('scan', { id: 'SCN-1' }), false);
  assert.equal(pendingCount(), 1);
});

await test('link dropping mid-sync keeps the unsent records queued, in order', async () => {
  const { db, writers } = fakeDatabase();
  for (const id of ['SCN-1', 'SCN-2', 'SCN-3']) enqueue('scan', { id });
  const scan = writers.scan;
  writers.scan = async (payload: any) => {
    if (payload.id === 'SCN-2') db.online = false; // connection lost before the second write
    return scan(payload);
  };
  const first = await syncOutbox(writers);
  assert.deepEqual([first.synced, first.failed, first.remaining], [1, 0, 2]);
  assert.deepEqual(pending().map((i) => i.payload.id), ['SCN-2', 'SCN-3']);
  db.online = true;
  writers.scan = scan;
  const second = await syncOutbox(writers);
  assert.deepEqual([second.synced, second.remaining], [2, 0]);
  assert.deepEqual(db.written, ['scan:SCN-1', 'scan:SCN-2', 'scan:SCN-3']);
});

await test('a record the database rejects is set aside and does not block the rest', async () => {
  const { db, writers } = fakeDatabase();
  db.rejectScanId = 'SCN-BAD';
  for (const id of ['SCN-1', 'SCN-BAD', 'SCN-3']) enqueue('scan', { id });
  const r = await syncOutbox(writers);
  assert.deepEqual([r.synced, r.failed, r.remaining], [2, 1, 0]);
  assert.deepEqual(db.written, ['scan:SCN-1', 'scan:SCN-3']);
  assert.equal(fs.readdirSync(path.join(outboxDir(), 'failed')).length, 1);
});

await test('a corrupt file is set aside instead of stopping the queue', async () => {
  const { db, writers } = fakeDatabase();
  enqueue('scan', { id: 'SCN-1' });
  fs.writeFileSync(path.join(outboxDir(), '000000000000001-000000-scan.json'), '{not json');
  const r = await syncOutbox(writers);
  assert.deepEqual([r.synced, r.remaining], [1, 0]);
  assert.deepEqual(db.written, ['scan:SCN-1']);
});

reset();
console.log(`\n${passed} outbox tests passed`);

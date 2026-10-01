// Store-and-forward outbox for the gateway.
//
// A checkpoint keeps screening when the link to the cloud database is down:
// the engine runs on the same machine, so only the *write* to Postgres fails.
// Every record that could not be written (scan, audit entry, system log) is
// saved here as one small JSON file and replayed, in the original order, as
// soon as the database answers again. Files survive a restart or power cut.
//
// Scans are added to the hash chain when they are synced, not when they are
// queued: the chain head lives in the database, so that is the only moment a
// record can be linked to its true predecessor.
import fs from 'fs';
import path from 'path';

export type OutboxKind = 'scan' | 'audit' | 'system';

export interface OutboxItem {
  file: string;
  kind: OutboxKind;
  queued_at: string;
  payload: any;
}

export interface OutboxWriters {
  /** True when the database answers. */
  reachable: () => Promise<boolean>;
  /** Each writer must throw if the record was not stored. */
  scan: (payload: any) => Promise<void>;
  audit: (payload: any) => Promise<void>;
  system: (payload: any) => Promise<void>;
}

export interface SyncResult {
  synced: number;
  failed: number;
  remaining: number;
  skipped?: 'empty' | 'busy' | 'offline';
}

let counter = 0;
let draining = false;

export function outboxDir(): string {
  return process.env.OUTBOX_DIR || path.join(process.cwd(), 'data', 'outbox');
}

function ensureDir(dir: string): void {
  fs.mkdirSync(dir, { recursive: true });
}

/** Persist one record. Returns false when an identical scan is already queued. */
export function enqueue(kind: OutboxKind, payload: any): boolean {
  const dir = outboxDir();
  ensureDir(dir);
  if (kind === 'scan' && payload?.id && pending().some((i) => i.kind === 'scan' && i.payload?.id === payload.id)) {
    return false;
  }
  counter = (counter + 1) % 1_000_000;
  // zero-padded time + counter keeps the directory listing in queue order
  const name = `${String(Date.now()).padStart(15, '0')}-${String(counter).padStart(6, '0')}-${kind}.json`;
  const body = JSON.stringify({ kind, queued_at: new Date().toISOString(), payload });
  const tmp = path.join(dir, `${name}.tmp`);
  fs.writeFileSync(tmp, body, 'utf8');
  fs.renameSync(tmp, path.join(dir, name)); // a half-written file is never visible under its final name
  return true;
}

export function pending(): OutboxItem[] {
  const dir = outboxDir();
  if (!fs.existsSync(dir)) return [];
  const items: OutboxItem[] = [];
  for (const file of fs.readdirSync(dir).filter((f) => f.endsWith('.json')).sort()) {
    try {
      const parsed = JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8'));
      items.push({ file, kind: parsed.kind, queued_at: parsed.queued_at, payload: parsed.payload });
    } catch {
      quarantine(file); // unreadable: keep it for inspection, do not block the queue
    }
  }
  return items;
}

export function pendingCount(): number {
  const dir = outboxDir();
  return fs.existsSync(dir) ? fs.readdirSync(dir).filter((f) => f.endsWith('.json')).length : 0;
}

function remove(file: string): void {
  fs.rmSync(path.join(outboxDir(), file), { force: true });
}

function quarantine(file: string): void {
  const failedDir = path.join(outboxDir(), 'failed');
  ensureDir(failedDir);
  try {
    fs.renameSync(path.join(outboxDir(), file), path.join(failedDir, file));
  } catch { /* already moved */ }
}

/**
 * Replay queued records oldest first. Stops at the first record that fails
 * while the database is unreachable (so order is kept for the next attempt);
 * a record the database itself rejects is moved to outbox/failed/ so one bad
 * record cannot block everything behind it.
 */
export async function syncOutbox(writers: OutboxWriters): Promise<SyncResult> {
  if (draining) return { synced: 0, failed: 0, remaining: pendingCount(), skipped: 'busy' };
  const items = pending();
  if (items.length === 0) return { synced: 0, failed: 0, remaining: 0, skipped: 'empty' };
  draining = true;
  let synced = 0;
  let failed = 0;
  try {
    if (!(await writers.reachable())) return { synced: 0, failed: 0, remaining: items.length, skipped: 'offline' };
    for (const item of items) {
      try {
        await writers[item.kind](item.payload);
        remove(item.file);
        synced++;
      } catch (err) {
        if (!(await writers.reachable())) break; // link dropped mid-sync: keep the rest queued, in order
        console.error(`Outbox: database rejected ${item.kind} record ${item.file}:`, (err as Error).message);
        quarantine(item.file);
        failed++;
      }
    }
    return { synced, failed, remaining: pendingCount() };
  } finally {
    draining = false;
  }
}

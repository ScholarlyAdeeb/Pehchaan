import crypto from 'crypto';
import bcrypt from 'bcryptjs';
import { getNeonPool, initNeonSchema } from './neon.ts';

export interface AuthPayload {
  userId: string;
  email: string;
  name: string;
  role: string;
  checkpointIds: string[];
  fp?: string;
  mustChangePassword?: boolean;
  /** signed in from this machine's cache while the database was unreachable */
  offline?: boolean;
}

// Passwords the old "Create Admin Account" button set. Any account still
// using one is forced to choose a new password at its next sign-in.
const PUBLISHED_DEFAULTS = ['admin123', 'officer123', 'incharge123'];

export const MIN_PASSWORD_LENGTH = 12;

// Shared demo accounts, published on the sign-in page for evaluators. They are
// never forced to change their password, and nobody can change, reset or
// deactivate them, so one visitor cannot lock out the next. DEMO_ACCOUNTS
// overrides the list (comma-separated emails); DEMO_ACCOUNTS=none turns it off.
const DEFAULT_DEMO_ACCOUNTS = 'officer@pehchaan.gov.in,incharge@pehchaan.gov.in,admin@pehchaan.gov.in';
const demoAccounts = () => {
  const raw = process.env.DEMO_ACCOUNTS ?? DEFAULT_DEMO_ACCOUNTS;
  if (raw.trim().toLowerCase() === 'none') return new Set<string>();
  return new Set(raw.split(',').map((e) => e.trim().toLowerCase()).filter(Boolean));
};
export const isDemoAccount = (email?: string | null) => !!email && demoAccounts().has(email.toLowerCase());

async function refuseIfDemo(userId: string, what: string) {
  if (demoAccounts().size === 0) return;
  const pool = await db();
  const row = (await pool.query('SELECT email FROM pehchaan_users WHERE id = $1', [userId])).rows[0];
  if (row && isDemoAccount(row.email)) {
    throw Object.assign(new Error(`This is a shared demo account; its ${what} cannot be changed.`), { status: 403 });
  }
}

let setupCode: string | null = null;

async function db() {
  const pool = getNeonPool();
  if (!pool) throw new Error('Database not connected');
  await initNeonSchema();
  return pool;
}

export function passwordProblem(password: unknown): string | null {
  if (typeof password !== 'string' || password.length < MIN_PASSWORD_LENGTH) {
    return `Password must be at least ${MIN_PASSWORD_LENGTH} characters.`;
  }
  if (PUBLISHED_DEFAULTS.includes(password.toLowerCase())) return 'That password is published; choose another.';
  if (!/[A-Za-z]/.test(password) || !/[0-9]/.test(password)) return 'Use both letters and numbers.';
  return null;
}

/** Runs at start-up: issues a one-time setup code on an empty database and
 *  flags any account that still uses a published default password. */
export async function securityStartup(): Promise<void> {
  const pool = getNeonPool();
  if (!pool) return;
  try {
    await initNeonSchema();
    const users = (await pool.query('SELECT id, email, password_hash, must_change_password FROM pehchaan_users')).rows;
    if (users.length === 0) {
      setupCode = crypto.randomBytes(6).toString('hex').toUpperCase().match(/.{4}/g)!.join('-');
      console.log('\n==================================================================');
      console.log(`  FIRST-TIME SETUP CODE: ${setupCode}`);
      console.log('  Enter it on the sign-in page ("First-time setup") to create the admin.');
      console.log('==================================================================\n');
      return;
    }
    for (const u of users) {
      if (isDemoAccount(u.email)) {
        if (u.must_change_password) await pool.query('UPDATE pehchaan_users SET must_change_password = false WHERE id = $1', [u.id]);
        continue;
      }
      if (u.must_change_password) continue;
      for (const weak of PUBLISHED_DEFAULTS) {
        if (await bcrypt.compare(weak, u.password_hash)) {
          await pool.query('UPDATE pehchaan_users SET must_change_password = true WHERE id = $1', [u.id]);
          console.warn(`Account ${u.email} uses a published default password; it must be changed at next sign-in.`);
          break;
        }
      }
    }
  } catch (err) {
    console.error('Security start-up checks failed:', err);
  }
}

export function setupAvailable(): boolean {
  return setupCode !== null;
}

export async function completeSetup(body: any): Promise<{ email: string }> {
  if (!setupCode) throw Object.assign(new Error('Setup has already been completed.'), { status: 409 });
  const code = String(body?.setupCode || '').trim().toUpperCase();
  if (code.length !== setupCode.length || !crypto.timingSafeEqual(Buffer.from(code), Buffer.from(setupCode))) {
    throw Object.assign(new Error('Setup code is incorrect. It is printed in the server console.'), { status: 403 });
  }
  const email = String(body?.email || '').trim().toLowerCase();
  const name = String(body?.name || '').trim();
  if (!/^[^@\s]+@[^@\s]+$/.test(email) || !name) throw Object.assign(new Error('Name and a valid email are required.'), { status: 400 });
  const problem = passwordProblem(body?.password);
  if (problem) throw Object.assign(new Error(problem), { status: 400 });

  const pool = await db();
  await pool.query(
    `INSERT INTO pehchaan_checkpoints (id, name, location, type) VALUES ('CP-001', 'Checkpoint 1', NULL, 'ICP')
     ON CONFLICT (id) DO NOTHING`,
  );
  await pool.query(
    `INSERT INTO pehchaan_users (id, email, name, password_hash, role, checkpoint_ids)
     VALUES ($1, $2, $3, $4, 'ADMIN', '{}')`,
    [`USR-${crypto.randomBytes(4).toString('hex').toUpperCase()}`, email, name, await bcrypt.hash(body.password, 12)],
  );
  setupCode = null;
  return { email };
}

export async function changePassword(userId: string, current: string, next: string): Promise<void> {
  await refuseIfDemo(userId, 'password');
  const pool = await db();
  const row = (await pool.query('SELECT password_hash FROM pehchaan_users WHERE id = $1', [userId])).rows[0];
  if (!row || !(await bcrypt.compare(String(current || ''), row.password_hash))) {
    throw Object.assign(new Error('Current password is incorrect.'), { status: 403 });
  }
  const problem = passwordProblem(next);
  if (problem) throw Object.assign(new Error(problem), { status: 400 });
  if (await bcrypt.compare(next, row.password_hash)) throw Object.assign(new Error('Choose a password you have not used here.'), { status: 400 });
  await pool.query('UPDATE pehchaan_users SET password_hash = $1, must_change_password = false WHERE id = $2', [await bcrypt.hash(next, 12), userId]);
}

// ---- User management (ADMIN) ----

export async function listUsers() {
  const pool = await db();
  return (await pool.query(
    'SELECT id, email, name, role, checkpoint_ids, must_change_password, COALESCE(active, true) AS active, created_at FROM pehchaan_users ORDER BY created_at',
  )).rows;
}

const ROLES = ['OFFICER', 'POST_INCHARGE', 'ADMIN'];

/** Creates a user with a random one-time password they must change at first sign-in. */
export async function createUser(body: any): Promise<{ id: string; email: string; temporaryPassword: string }> {
  const email = String(body?.email || '').trim().toLowerCase();
  const name = String(body?.name || '').trim();
  const role = String(body?.role || '');
  const checkpointIds: string[] = Array.isArray(body?.checkpointIds) ? body.checkpointIds.map(String) : [];
  if (!/^[^@\s]+@[^@\s]+$/.test(email) || !name) throw Object.assign(new Error('Name and a valid email are required.'), { status: 400 });
  if (!ROLES.includes(role)) throw Object.assign(new Error('Unknown role.'), { status: 400 });
  if (role !== 'ADMIN' && checkpointIds.length === 0) throw Object.assign(new Error('Assign at least one checkpoint.'), { status: 400 });
  const pool = await db();
  const temporaryPassword = crypto.randomBytes(9).toString('base64url');
  const id = `USR-${crypto.randomBytes(4).toString('hex').toUpperCase()}`;
  try {
    await pool.query(
      `INSERT INTO pehchaan_users (id, email, name, password_hash, role, checkpoint_ids, must_change_password)
       VALUES ($1, $2, $3, $4, $5, $6, true)`,
      [id, email, name, await bcrypt.hash(temporaryPassword, 12), role, checkpointIds],
    );
  } catch (err: any) {
    if (err?.code === '23505') throw Object.assign(new Error('A user with that email already exists.'), { status: 409 });
    throw err;
  }
  return { id, email, temporaryPassword };
}

export async function setUserActive(id: string, active: boolean) {
  await refuseIfDemo(id, 'status');
  const pool = await db();
  await pool.query('UPDATE pehchaan_users SET active = $1 WHERE id = $2', [active, id]);
}

export async function resetUserPassword(id: string): Promise<string> {
  await refuseIfDemo(id, 'password');
  const pool = await db();
  const temporaryPassword = crypto.randomBytes(9).toString('base64url');
  const res = await pool.query(
    'UPDATE pehchaan_users SET password_hash = $1, must_change_password = true WHERE id = $2',
    [await bcrypt.hash(temporaryPassword, 12), id],
  );
  if (!res.rowCount) throw Object.assign(new Error('User not found.'), { status: 404 });
  return temporaryPassword;
}

export async function addCheckpoint(body: any) {
  const id = String(body?.id || '').trim().toUpperCase();
  const name = String(body?.name || '').trim();
  if (!/^[A-Z0-9-]{2,32}$/.test(id) || !name) throw Object.assign(new Error('Checkpoint ID (A-Z, 0-9, -) and name are required.'), { status: 400 });
  const num = (v: unknown) => (v === '' || v === null || v === undefined ? null : Number(v));
  const lat = num(body?.latitude), lng = num(body?.longitude), radius = num(body?.radiusKm) ?? 5;
  if ((lat !== null && (!Number.isFinite(lat) || Math.abs(lat) > 90)) || (lng !== null && (!Number.isFinite(lng) || Math.abs(lng) > 180))) {
    throw Object.assign(new Error('Latitude must be −90…90 and longitude −180…180.'), { status: 400 });
  }
  if (!Number.isFinite(radius) || radius <= 0 || radius > 200) throw Object.assign(new Error('Radius must be 0–200 km.'), { status: 400 });
  const pool = await db();
  await pool.query(
    `INSERT INTO pehchaan_checkpoints (id, name, location, type, latitude, longitude, radius_km) VALUES ($1,$2,$3,$4,$5,$6,$7)
     ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, location = EXCLUDED.location,
       latitude = EXCLUDED.latitude, longitude = EXCLUDED.longitude, radius_km = EXCLUDED.radius_km`,
    [id, name, body?.location || null, body?.type || null, lat, lng, radius],
  );
}

// ---- Automatic checkpoint from device location ----

function distanceKm(aLat: number, aLng: number, bLat: number, bLng: number): number {
  const rad = (d: number) => (d * Math.PI) / 180;
  const h = Math.sin(rad(bLat - aLat) / 2) ** 2 +
    Math.cos(rad(aLat)) * Math.cos(rad(bLat)) * Math.sin(rad(bLng - aLng) / 2) ** 2;
  return 6371 * 2 * Math.asin(Math.sqrt(h));
}

export interface ResolvedCheckpoint {
  id: string;
  name: string;
  location?: string | null;
  method: 'gps' | 'gps-outside-radius' | 'only-assignment' | 'global' | 'fallback';
  distanceKm?: number;
  accuracyM?: number;
  note: string;
}

/**
 * Picks the user's checkpoint from the device location. The location comes
 * from the browser and can be spoofed, so the choice is always limited to
 * checkpoints the account is already assigned to; the device only decides
 * *which* of those. Every resolution is written to the system log.
 */
export async function resolveCheckpoint(user: AuthPayload, body: any): Promise<ResolvedCheckpoint> {
  const pool = await db();
  const all = (await pool.query('SELECT id, name, location, latitude, longitude, COALESCE(radius_km, 5) AS radius_km FROM pehchaan_checkpoints')).rows;
  const scope = scopeOf(user);
  const allowed = scope === null ? all : all.filter((c: any) => scope.includes(c.id));
  const lat = Number(body?.latitude), lng = Number(body?.longitude);
  const accuracyM = Number.isFinite(Number(body?.accuracy)) ? Math.round(Number(body.accuracy)) : undefined;
  const hasFix = Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 90 && Math.abs(lng) <= 180;

  if (hasFix) {
    const located = allowed
      .filter((c: any) => c.latitude !== null && c.longitude !== null)
      .map((c: any) => ({ c, d: distanceKm(lat, lng, c.latitude, c.longitude) }))
      .sort((a: any, b: any) => a.d - b.d);
    const nearest = located[0];
    if (nearest && nearest.d <= nearest.c.radius_km) {
      return { id: nearest.c.id, name: nearest.c.name, location: nearest.c.location, method: 'gps',
        distanceKm: Math.round(nearest.d * 10) / 10, accuracyM, note: `Detected from device location (${nearest.d.toFixed(1)} km away).` };
    }
    if (user.role !== 'ADMIN' && allowed.length === 1) {
      const c = allowed[0];
      return { id: c.id, name: c.name, location: c.location, method: 'gps-outside-radius', accuracyM,
        distanceKm: nearest ? Math.round(nearest.d * 10) / 10 : undefined,
        note: nearest ? `You appear to be ${nearest.d.toFixed(1)} km from your assigned checkpoint.` : 'Your assigned checkpoint has no coordinates set.' };
    }
  }
  if (user.role === 'ADMIN') {
    return { id: 'GLOBAL', name: 'Global Scope', method: 'global', accuracyM,
      note: hasFix ? 'Not at a checkpoint — admin working in global scope.' : 'Location unavailable — admin working in global scope.' };
  }
  if (allowed.length === 1) {
    const c = allowed[0];
    return { id: c.id, name: c.name, location: c.location, method: 'only-assignment', note: 'Your only assigned checkpoint.' };
  }
  if (allowed.length === 0) throw Object.assign(new Error('No checkpoint is assigned to your account. Ask an administrator.'), { status: 403 });
  const c = allowed[0];
  return { id: c.id, name: c.name, location: c.location, method: 'fallback',
    note: hasFix ? 'You are not within range of any assigned checkpoint; confirm the checkpoint in the header.' : 'Location unavailable; confirm the checkpoint in the header.' };
}

// ---- Checkpoint scoping ----

/** Checkpoints a user may see; null means all (ADMIN). */
export function scopeOf(user: AuthPayload): string[] | null {
  return user.role === 'ADMIN' ? null : user.checkpointIds || [];
}

export function inScope(user: AuthPayload, checkpointId?: string | null): boolean {
  const scope = scopeOf(user);
  return scope === null || (!!checkpointId && scope.includes(checkpointId));
}

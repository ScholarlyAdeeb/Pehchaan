// Offline sign-in for a checkpoint that has lost its link to the database.
//
// Accounts live in the cloud database, so normally nobody can sign in during
// an outage. Each time an officer signs in successfully while online, this
// module remembers the account on the checkpoint machine: the same bcrypt
// hash the database holds (never the password), plus role and checkpoints.
// During an outage the password is checked against that copy.
//
// Guard rails:
//   * the file is sealed with an HMAC; an edited file (say, a role changed to
//     ADMIN) is rejected whole;
//   * an entry is honoured for OFFLINE_LOGIN_DAYS (default 7) after the last
//     online sign-in, so a revoked account cannot be used offline for long;
//   * accounts that must change their password cannot sign in offline;
//   * disabled on serverless hosting (no durable disk, and no outage to bridge).
import crypto from 'crypto';
import fs from 'fs';
import path from 'path';
import bcrypt from 'bcryptjs';

export interface CachedUser {
  id: string;
  email: string;
  name: string;
  role: string;
  checkpoint_ids: string[];
  password_hash: string;
  must_change_password: boolean;
  cached_at: string;
}

type Cache = Record<string, CachedUser>;

const cacheFile = () => process.env.OFFLINE_AUTH_FILE || path.join(process.cwd(), 'data', 'auth-cache.json');
const maxAgeMs = () => Number(process.env.OFFLINE_LOGIN_DAYS || 7) * 24 * 60 * 60 * 1000;

/** Durable local state exists only on a checkpoint machine, not on serverless hosting. */
export function localStateEnabled(): boolean {
  return !process.env.VERCEL && process.env.OFFLINE_MODE !== 'false';
}

function seal(users: Cache): string {
  const body = JSON.stringify(Object.keys(users).sort().map((k) => users[k]));
  return crypto.createHmac('sha256', process.env.HMAC_SECRET as string).update(`offline-auth|${body}`).digest('hex');
}

function load(): Cache {
  const file = cacheFile();
  if (!fs.existsSync(file)) return {};
  try {
    const { users, mac } = JSON.parse(fs.readFileSync(file, 'utf8'));
    const expected = seal(users);
    if (typeof mac !== 'string' || mac.length !== expected.length
      || !crypto.timingSafeEqual(Buffer.from(mac), Buffer.from(expected))) {
      console.error('Offline sign-in cache failed its integrity check and was ignored.');
      return {};
    }
    return users;
  } catch {
    return {};
  }
}

function save(users: Cache): void {
  const file = cacheFile();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify({ users, mac: seal(users) }), { encoding: 'utf8', mode: 0o600 });
  fs.renameSync(tmp, file);
}

/** Call after a successful online sign-in. */
export function rememberUser(user: { id: string; email: string; name: string; role: string; checkpoint_ids?: string[] | null; password_hash: string; must_change_password?: boolean }): void {
  if (!localStateEnabled()) return;
  const users = load();
  users[user.email.toLowerCase()] = {
    id: user.id, email: user.email, name: user.name, role: user.role,
    checkpoint_ids: user.checkpoint_ids || [], password_hash: user.password_hash,
    must_change_password: Boolean(user.must_change_password), cached_at: new Date().toISOString(),
  };
  save(users);
}

/** Call when an account is deactivated, deleted or has its password reset. */
export function forgetUser(match: { id?: string; email?: string }): void {
  if (!localStateEnabled()) return;
  const users = load();
  const before = Object.keys(users).length;
  for (const [key, u] of Object.entries(users)) {
    if ((match.id && u.id === match.id) || (match.email && key === match.email.toLowerCase())) delete users[key];
  }
  if (Object.keys(users).length !== before) save(users);
}

export function cachedUserById(id: string): CachedUser | null {
  if (!localStateEnabled()) return null;
  const hit = Object.values(load()).find((u) => u.id === id) || null;
  return hit && Date.now() - Date.parse(hit.cached_at) <= maxAgeMs() ? hit : null;
}

let dummy: string | null = null;
const dummyHash = () => (dummy ??= bcrypt.hashSync(crypto.randomBytes(16).toString('hex'), 12));

export type OfflineLogin = { ok: true; user: CachedUser } | { ok: false; error: string };

export async function verifyOffline(email: string, password: string): Promise<OfflineLogin> {
  const unavailable = 'The database is unreachable and this account has not signed in on this machine recently, so it cannot be verified offline.';
  if (!localStateEnabled()) return { ok: false, error: 'Database unreachable. Try again shortly.' };
  const user = load()[String(email).trim().toLowerCase()];
  if (!user) {
    await bcrypt.compare(password, dummyHash()); // same work as a real check, so timing does not reveal who is cached
    return { ok: false, error: unavailable };
  }
  if (Date.now() - Date.parse(user.cached_at) > maxAgeMs()) return { ok: false, error: unavailable };
  if (!(await bcrypt.compare(password, user.password_hash))) return { ok: false, error: 'Invalid credentials' };
  if (user.must_change_password) {
    return { ok: false, error: 'This account must change its password, which needs the database. Sign in again when the link is back.' };
  }
  return { ok: true, user };
}

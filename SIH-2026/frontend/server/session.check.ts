// Run with: npm test
// Session cookies, refresh-token rotation and offline sign-in, against an
// in-memory token store and a temp cache file (never the real database).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import bcrypt from 'bcryptjs';

process.env.JWT_SECRET ||= 'check-only-jwt-secret';
process.env.HMAC_SECRET ||= 'check-only-hmac-secret';
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'pehchaan-session-'));
process.env.OFFLINE_AUTH_FILE = path.join(dir, 'auth-cache.json');
delete process.env.VERCEL;

const session = await import('./session.ts');
const offline = await import('./offline-auth.ts');
type Store = import('./session.ts').RefreshStore;

function memoryStore() {
  const rows = new Map<string, { family: string; used: boolean; revoked: boolean }>();
  const state = { online: true };
  const guard = () => { if (!state.online) throw new Error('connect ETIMEDOUT'); };
  const store: Store = {
    async save(rec) { guard(); rows.set(rec.jti, { family: rec.family, used: false, revoked: false }); },
    async consume(jti) {
      guard();
      const row = rows.get(jti);
      if (!row) return 'unknown';
      if (row.revoked) return 'unknown';
      if (row.used) return 'reused';
      row.used = true;
      return 'ok';
    },
    async revokeFamily(family) { for (const r of rows.values()) if (r.family === family) r.revoked = true; },
  };
  return { store, state, rows };
}

async function signIn(store: Store, off = false) {
  const t = session.signRefresh({ sub: 'USR-1', fam: 'FAM-1', fp: 'fp-A', off });
  if (!off) await store.save({ jti: t.jti, family: 'FAM-1', userId: 'USR-1', expiresAt: t.expiresAt });
  return t.token;
}

const req = (over: any = {}) => ({ method: 'POST', headers: {}, secure: false, ...over }) as any;
const res = () => { const h: Record<string, any> = {}; return { setHeader: (k: string, v: any) => { h[k] = v; }, h } as any; };

let passed = 0;
async function test(name: string, fn: () => Promise<void> | void) {
  await fn();
  passed++;
  console.log(`ok - ${name}`);
}

await test('a refresh token is not accepted as an access token, nor the reverse', () => {
  const access = session.signAccess({ userId: 'USR-1', email: 'a@b', name: 'A', role: 'OFFICER', checkpointIds: [] });
  const refresh = session.signRefresh({ sub: 'USR-1', fam: 'F' }).token;
  assert.equal(session.verifyAccess(access).userId, 'USR-1');
  assert.throws(() => session.verifyAccess(refresh));
  assert.throws(() => session.verifyRefresh(access));
});

await test('each refresh hands out a new token and retires the old one', async () => {
  const { store } = memoryStore();
  const first = await signIn(store);
  const r1 = await session.rotateRefresh(first, 'fp-A', store, true);
  assert.ok(r1.ok === true && r1.next && r1.next !== first && !r1.degraded);
  const r2 = await session.rotateRefresh((r1 as any).next, 'fp-A', store, true);
  assert.equal(r2.ok, true);
});

await test('replaying a used refresh token closes every session from that sign-in', async () => {
  const { store } = memoryStore();
  const first = await signIn(store);
  const r1 = await session.rotateRefresh(first, 'fp-A', store, true);
  const stolenReplay = await session.rotateRefresh(first, 'fp-A', store, true);
  assert.deepEqual([stolenReplay.ok, (stolenReplay as any).status], [false, 401]);
  const legitimate = await session.rotateRefresh((r1 as any).next, 'fp-A', store, true);
  assert.equal(legitimate.ok, false, 'the family is revoked, so the newer token is dead too');
});

await test('a refresh token presented from another device is refused', async () => {
  const { store } = memoryStore();
  const r = await session.rotateRefresh(await signIn(store), 'fp-OTHER', store, true);
  assert.deepEqual([r.ok, (r as any).status], [false, 401]);
});

await test('database down: a checkpoint keeps the session, serverless hosting refuses', async () => {
  const { store, state } = memoryStore();
  const token = await signIn(store);
  state.online = false;
  const checkpoint = await session.rotateRefresh(token, 'fp-A', store, true);
  assert.ok(checkpoint.ok === true && checkpoint.degraded && checkpoint.next === null, 'kept, not rotated');
  const serverless = await session.rotateRefresh(token, 'fp-A', store, false);
  assert.deepEqual([serverless.ok, (serverless as any).status], [false, 503]);
  state.online = true;
  assert.equal((await session.rotateRefresh(token, 'fp-A', store, true)).ok, true, 'still usable once the link is back');
});

await test('a session started offline continues online; an unknown online token does not', async () => {
  const { store } = memoryStore();
  const offlineToken = await signIn(store, true);
  const r = await session.rotateRefresh(offlineToken, 'fp-A', store, true);
  assert.ok(r.ok === true && r.next);
  const forged = session.signRefresh({ sub: 'USR-1', fam: 'FAM-X', fp: 'fp-A' }).token; // signed, but never issued by a sign-in
  assert.equal((await session.rotateRefresh(forged, 'fp-A', store, true)).ok, false);
});

await test('cookies are HttpOnly, SameSite=Strict, scoped, and Secure over https', () => {
  const out = res();
  session.setSessionCookies(req({ headers: { 'x-forwarded-proto': 'https' } }), out, 'ACCESS', 'REFRESH');
  const [at, csrf, rt] = out.h['Set-Cookie'] as string[];
  assert.match(at, /^pehchaan_at=ACCESS; Max-Age=900; Path=\/api; SameSite=Strict; HttpOnly; Secure$/);
  assert.match(rt, /^pehchaan_rt=REFRESH; Max-Age=43200; Path=\/api\/auth; SameSite=Strict; HttpOnly; Secure$/);
  assert.ok(csrf.startsWith('pehchaan_csrf=') && !csrf.includes('HttpOnly'), 'the page must be able to read the CSRF value');
  const plain = res();
  session.setSessionCookies(req(), plain, 'A', null);
  assert.ok(!(plain.h['Set-Cookie'] as string[]).some((c) => c.includes('Secure')), 'http://localhost development');
  assert.equal((plain.h['Set-Cookie'] as string[]).length, 2, 'refresh cookie untouched when not rotated');
});

await test('CSRF: reads pass, writes need the header to match the cookie', () => {
  const cookie = 'pehchaan_at=x; pehchaan_csrf=tok123';
  assert.equal(session.csrfOk(req({ method: 'GET', headers: { cookie } })), true);
  assert.equal(session.csrfOk(req({ headers: { cookie } })), false);
  assert.equal(session.csrfOk(req({ headers: { cookie, 'x-csrf-token': 'wrong!!' } })), false);
  assert.equal(session.csrfOk(req({ headers: { cookie, 'x-csrf-token': 'tok123' } })), true);
});

// ---- offline sign-in ---------------------------------------------------------
const passwordHash = bcrypt.hashSync('correct horse 42', 4);
const account = { id: 'USR-1', email: 'Officer@Post.in', name: 'Officer One', role: 'OFFICER', checkpoint_ids: ['CP-1'], password_hash: passwordHash };

await test('offline: an account that signed in here can be verified without the database', async () => {
  offline.rememberUser(account);
  const ok = await offline.verifyOffline('officer@post.in', 'correct horse 42');
  assert.ok(ok.ok === true && ok.user.role === 'OFFICER' && ok.user.checkpoint_ids[0] === 'CP-1');
  const bad = await offline.verifyOffline('officer@post.in', 'wrong password');
  assert.deepEqual([bad.ok, (bad as any).error], [false, 'Invalid credentials']);
  assert.equal((await offline.verifyOffline('stranger@post.in', 'x')).ok, false);
  assert.ok(!fs.readFileSync(process.env.OFFLINE_AUTH_FILE!, 'utf8').includes('correct horse'), 'only the hash is stored');
});

await test('offline: an edited cache (role raised to ADMIN) is rejected whole', async () => {
  const file = process.env.OFFLINE_AUTH_FILE!;
  const original = fs.readFileSync(file, 'utf8');
  fs.writeFileSync(file, original.replace('"OFFICER"', '"ADMIN"'));
  assert.equal((await offline.verifyOffline('officer@post.in', 'correct horse 42')).ok, false);
  fs.writeFileSync(file, original);
  assert.equal((await offline.verifyOffline('officer@post.in', 'correct horse 42')).ok, true);
});

await test('offline: stale entries, forced password changes and removed accounts are refused', async () => {
  process.env.OFFLINE_LOGIN_DAYS = '0';
  assert.equal((await offline.verifyOffline('officer@post.in', 'correct horse 42')).ok, false, 'older than the allowed window');
  assert.equal(offline.cachedUserById('USR-1'), null);
  delete process.env.OFFLINE_LOGIN_DAYS;

  offline.rememberUser({ ...account, must_change_password: true });
  assert.equal((await offline.verifyOffline('officer@post.in', 'correct horse 42')).ok, false);

  offline.rememberUser(account);
  offline.forgetUser({ id: 'USR-1' });
  assert.equal((await offline.verifyOffline('officer@post.in', 'correct horse 42')).ok, false);
});

await test('offline: switched off on serverless hosting', async () => {
  process.env.VERCEL = '1';
  offline.rememberUser(account);
  assert.equal(offline.localStateEnabled(), false);
  assert.equal((await offline.verifyOffline('officer@post.in', 'correct horse 42')).ok, false);
  delete process.env.VERCEL;
});

fs.rmSync(dir, { recursive: true, force: true });
console.log(`\n${passed} session tests passed`);
process.exit(0);

// Browser sessions: short-lived access token + rotating refresh token, both in
// HttpOnly cookies so page scripts (and anything injected into the page)
// can never read them.
//
//   pehchaan_at    access JWT, 15 min, sent to /api
//   pehchaan_rt    refresh JWT, 12 h (one shift), sent only to /api/auth
//   pehchaan_csrf  random value readable by the page; state-changing requests
//                  must echo it in X-CSRF-Token (double-submit check)
//
// Every refresh replaces the refresh token. Each one is recorded in Postgres by
// its id, so presenting an already used token (a stolen copy) is detected and
// the whole login family is revoked. Tokens are stateless JWTs plus one table,
// which also works on serverless hosting.
import crypto from 'crypto';
import jwt from 'jsonwebtoken';
import type { Request, Response } from 'express';
import type { AuthPayload } from './security.ts';

export const ACCESS_TTL_SECONDS = 15 * 60;
export const REFRESH_TTL_SECONDS = 12 * 60 * 60;
export const ACCESS_COOKIE = 'pehchaan_at';
export const REFRESH_COOKIE = 'pehchaan_rt';
export const CSRF_COOKIE = 'pehchaan_csrf';

export interface RefreshClaims {
  sub: string;      // user id
  jti: string;      // this token's id
  fam: string;      // login family: every token descended from one sign-in
  fp?: string;      // session fingerprint
  off?: boolean;    // issued while the database was unreachable (never recorded)
  typ: 'refresh';
}

export type RotateOutcome = 'ok' | 'reused' | 'unknown';

/** Where refresh-token ids are recorded. Methods throw if the store is unreachable. */
export interface RefreshStore {
  save(rec: { jti: string; family: string; userId: string; expiresAt: Date }): Promise<void>;
  /** Marks `jti` as used if it is still valid, atomically. */
  consume(jti: string): Promise<RotateOutcome>;
  revokeFamily(family: string): Promise<void>;
}

const secret = () => process.env.JWT_SECRET as string;

export function signAccess(payload: AuthPayload): string {
  const { iat, exp, ...claims } = payload as AuthPayload & { iat?: number; exp?: number };
  return jwt.sign({ ...claims, typ: 'access' }, secret(), { expiresIn: ACCESS_TTL_SECONDS });
}

export function verifyAccess(token: string): AuthPayload {
  const decoded = jwt.verify(token, secret()) as AuthPayload & { typ?: string };
  if (decoded.typ === 'refresh') throw new Error('refresh token used as access token');
  return decoded;
}

export function signRefresh(claims: Omit<RefreshClaims, 'typ' | 'jti'> & { jti?: string }): { token: string; jti: string; expiresAt: Date } {
  const jti = claims.jti || crypto.randomBytes(18).toString('base64url');
  const token = jwt.sign({ ...claims, jti, typ: 'refresh' }, secret(), { expiresIn: REFRESH_TTL_SECONDS });
  return { token, jti, expiresAt: new Date(Date.now() + REFRESH_TTL_SECONDS * 1000) };
}

export function verifyRefresh(token: string): RefreshClaims {
  const decoded = jwt.verify(token, secret()) as RefreshClaims;
  if (decoded.typ !== 'refresh' || !decoded.jti || !decoded.fam) throw new Error('not a refresh token');
  return decoded;
}

// ---- cookies ---------------------------------------------------------------

export function readCookies(req: Request): Record<string, string> {
  const out: Record<string, string> = {};
  for (const part of (req.headers.cookie || '').split(';')) {
    const i = part.indexOf('=');
    if (i > 0) out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
  }
  return out;
}

function isHttps(req: Request): boolean {
  return req.secure || req.headers['x-forwarded-proto'] === 'https';
}

function cookie(name: string, value: string, opts: { maxAge: number; path: string; httpOnly: boolean; secure: boolean }): string {
  return [
    `${name}=${encodeURIComponent(value)}`,
    `Max-Age=${opts.maxAge}`,
    `Path=${opts.path}`,
    'SameSite=Strict',
    opts.httpOnly ? 'HttpOnly' : '',
    opts.secure ? 'Secure' : '',   // browsers treat http://localhost as secure enough to omit this in development
  ].filter(Boolean).join('; ');
}

export function setSessionCookies(req: Request, res: Response, access: string, refresh: string | null): void {
  const secure = isHttps(req);
  const cookies = [
    cookie(ACCESS_COOKIE, access, { maxAge: ACCESS_TTL_SECONDS, path: '/api', httpOnly: true, secure }),
    cookie(CSRF_COOKIE, crypto.randomBytes(24).toString('base64url'), { maxAge: REFRESH_TTL_SECONDS, path: '/', httpOnly: false, secure }),
  ];
  if (refresh) cookies.push(cookie(REFRESH_COOKIE, refresh, { maxAge: REFRESH_TTL_SECONDS, path: '/api/auth', httpOnly: true, secure }));
  res.setHeader('Set-Cookie', cookies);
}

export function clearSessionCookies(req: Request, res: Response): void {
  const secure = isHttps(req);
  res.setHeader('Set-Cookie', [
    cookie(ACCESS_COOKIE, '', { maxAge: 0, path: '/api', httpOnly: true, secure }),
    cookie(REFRESH_COOKIE, '', { maxAge: 0, path: '/api/auth', httpOnly: true, secure }),
    cookie(CSRF_COOKIE, '', { maxAge: 0, path: '/', httpOnly: false, secure }),
  ]);
}

/** Double-submit check for a cookie-authenticated, state-changing request. */
export function csrfOk(req: Request): boolean {
  if (['GET', 'HEAD', 'OPTIONS'].includes(req.method)) return true;
  const sent = req.headers['x-csrf-token'];
  const expected = readCookies(req)[CSRF_COOKIE];
  if (typeof sent !== 'string' || !expected || sent.length !== expected.length) return false;
  return crypto.timingSafeEqual(Buffer.from(sent), Buffer.from(expected));
}

// ---- refresh rotation ------------------------------------------------------

export type RefreshResult =
  | { ok: true; claims: RefreshClaims; next: string | null; degraded: boolean }
  | { ok: false; status: number; error: string };

/**
 * Validates a refresh token and rotates it.
 *
 * `allowOfflineGrace`: when the store cannot be reached (checkpoint without a
 * network link) the signed token is accepted as it is and not rotated, so an
 * officer's session survives an outage; it still expires on schedule. On
 * hosting where the database is the only state, pass false and the request
 * fails instead.
 */
export async function rotateRefresh(token: string | undefined, fingerprint: string, store: RefreshStore, allowOfflineGrace: boolean): Promise<RefreshResult> {
  if (!token) return { ok: false, status: 401, error: 'No session' };
  let claims: RefreshClaims;
  try {
    claims = verifyRefresh(token);
  } catch {
    return { ok: false, status: 401, error: 'Session expired' };
  }
  if (claims.fp && claims.fp !== fingerprint) return { ok: false, status: 401, error: 'Session belongs to another device' };

  let outcome: RotateOutcome;
  try {
    outcome = await store.consume(claims.jti);
  } catch {
    if (!allowOfflineGrace) return { ok: false, status: 503, error: 'Session store unreachable' };
    return { ok: true, claims, next: null, degraded: true };
  }

  if (outcome === 'reused') {
    // An already-used token came back: someone holds a copy. End every session from that sign-in.
    await store.revokeFamily(claims.fam).catch(() => undefined);
    return { ok: false, status: 401, error: 'Session was used elsewhere and has been closed. Sign in again.' };
  }
  if (outcome === 'unknown' && !claims.off) return { ok: false, status: 401, error: 'Session expired' };

  // 'ok', or a token issued offline that the store has never seen: continue the family online.
  const next = signRefresh({ sub: claims.sub, fam: claims.fam, fp: claims.fp });
  try {
    await store.save({ jti: next.jti, family: claims.fam, userId: claims.sub, expiresAt: next.expiresAt });
  } catch {
    if (!allowOfflineGrace) return { ok: false, status: 503, error: 'Session store unreachable' };
    return { ok: true, claims, next: null, degraded: true };
  }
  return { ok: true, claims, next: next.token, degraded: false };
}

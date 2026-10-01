import './server/bootstrap-secrets.ts';
import express, { Request, Response, NextFunction } from 'express';
import http from 'http';
import path from 'path';
import crypto from 'crypto';
import bcrypt from 'bcryptjs';
import helmet from 'helmet';
import {
  fetchAllScans,
  insertScan,
  syncBatchScans,
  fetchAllAuditLogs,
  insertAuditLog,
  getNeonStatus,
  lookupUser,
  refreshStore,
  loadOutboxIntoMemory,
  outboxPending,
  syncOutboxToNeon,
  findUserByEmail,
  countUsers,
  createUser,
  fetchCheckpoints,
  insertCheckpoint,
  insertSystemLog,
  fetchSystemLogs,
  verifyChainIntegrity,
  fetchRefDatasets,
  seedRefDatasets,
  fetchRefDatasetStats,
  fetchScanById,
  fetchAuditLogsForTarget,
} from './server/neon.ts';
import { EngineError, analysisToRecord, fetchEngine, runEngineScan, screeningAuditDetails } from './server/screening.ts';
import {
  RateLimiter,
  computeSessionFingerprint,
  sanitizeScanInput,
  auditSignatureStatus,
} from './server/hashchain.ts';
import {
  AuthPayload,
  addCheckpoint,
  changePassword,
  completeSetup,
  createUser as createManagedUser,
  inScope,
  listUsers,
  resetUserPassword,
  resolveCheckpoint,
  scopeOf,
  securityStartup,
  setUserActive,
  setupAvailable,
} from './server/security.ts';
import {
  applyRetention,
  cosign,
  decisionsForScan,
  incidentReport,
  insiderAlerts,
  listBatches,
  listRegistry,
  pendingCosigns,
  receiptFor,
  recordDecision,
  sealBatch,
  anchorPendingBatches,
  verifyAgainstFabric,
  verifyReceipt,
} from './server/trust.ts';
import { describeEngineLink } from './server/engine-transport.ts';
import {
  ACCESS_COOKIE, REFRESH_COOKIE, clearSessionCookies, csrfOk, readCookies, rotateRefresh,
  setSessionCookies, signAccess, signRefresh, verifyAccess, verifyRefresh,
} from './server/session.ts';
import { cachedUserById, forgetUser, localStateEnabled, rememberUser, verifyOffline } from './server/offline-auth.ts';


const loginLimiter = new RateLimiter(5, 15 * 60 * 1000);
setInterval(() => loginLimiter.cleanup(), 60 * 1000).unref();

// Routes a user who must change their password may still reach.
const PASSWORD_CHANGE_ALLOWED = new Set(['/api/auth/me', '/api/auth/change-password']);

// Wraps async handlers: errors with a .status become that HTTP status.
const handle = (fn: (req: Request, res: Response) => Promise<unknown>) => async (req: Request, res: Response) => {
  try {
    const out = await fn(req, res);
    if (!res.headersSent) res.json(out);
  } catch (err: any) {
    res.status(err?.status || 500).json({ error: err?.message || 'Request failed' });
  }
};

declare global {
  namespace Express {
    interface Request {
      authUser?: AuthPayload;
    }
  }
}

function authMiddleware(req: Request, res: Response, next: NextFunction) {
  // Browsers authenticate with the HttpOnly session cookie. A Bearer access
  // token is still accepted for scripts and API clients, which have no cookies.
  const fromCookie = readCookies(req)[ACCESS_COOKIE];
  const header = req.headers.authorization;
  const bearer = header?.startsWith('Bearer ') && header.length > 20 ? header.slice(7) : null;
  const token = fromCookie || bearer;
  if (!token) {
    return res.status(401).json({ error: 'Authentication required' });
  }
  try {
    const decoded = verifyAccess(token);
    if (decoded.fp) {
      const currentFp = computeSessionFingerprint(req.headers['user-agent'] || '');
      if (decoded.fp !== currentFp) {
        return res.status(401).json({ error: 'Session fingerprint mismatch — token may have been replayed from another device' });
      }
    }
    // A cookie is sent by the browser on its own, so a state-changing request
    // must also prove it came from our page.
    if (fromCookie && !csrfOk(req)) {
      return res.status(403).json({ error: 'Request blocked: missing or wrong CSRF token. Reload the page.' });
    }
    if (decoded.mustChangePassword && !PASSWORD_CHANGE_ALLOWED.has(req.path)) {
      return res.status(403).json({ error: 'Change your password before continuing.', mustChangePassword: true });
    }
    req.authUser = decoded;
    next();
  } catch {
    return res.status(401).json({ error: 'Invalid or expired token' });
  }
}

function requireRole(...roles: string[]) {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!req.authUser || !roles.includes(req.authUser.role)) {
      return res.status(403).json({ error: 'Forbidden: insufficient role' });
    }
    next();
  };
}

// Sealing, Fabric anchoring and retention. On a checkpoint machine this runs
// on a timer; on serverless hosting a scheduled request calls it (see
// /api/cron/maintenance and vercel.json).
async function runMaintenance(): Promise<Record<string, unknown>> {
  const done: Record<string, unknown> = {};
  try {
    const batch = await sealBatch();
    if (batch) {
      done.sealedBatch = batch.id;
      console.log(`Sealed batch #${batch.id} (${batch.leaf_count} scans), root ${batch.merkle_root.slice(0, 12)}…`);
    }
    const anchoredNow = await anchorPendingBatches();
    if (anchoredNow) {
      done.anchoredOnFabric = anchoredNow;
      console.log(`Fabric: anchored ${anchoredNow} batch root(s) on the ledger`);
    }
    const purged = await applyRetention();
    if (purged) {
      done.retentionPurged = purged;
      console.log(`Retention: removed raw text/images from ${purged} old scans`);
    }
  } catch (err) {
    done.error = (err as Error).message;
    console.warn('Maintenance run failed:', (err as Error).message);
  }
  return done;
}

/** Builds the Express app with every API route. Does not listen. */
export async function createApp() {
  const app = express();
  // Behind a hosting proxy the client address and protocol arrive in forwarded headers.
  if (process.env.VERCEL || process.env.TRUST_PROXY === 'true') app.set('trust proxy', 1);

  // Screening uploads carry a document image and a live photo as base64.
  app.use(express.json({ limit: '32mb' }));

  if (process.env.NODE_ENV === 'production') {
    app.use((req, res, next) => {
      if (req.headers['x-forwarded-proto'] !== 'https') {
        return res.redirect(301, `https://${req.hostname}${req.url}`);
      }
      next();
    });
  }

  app.use(helmet({
    contentSecurityPolicy: {
      directives: {
        defaultSrc: ["'self'"],
        scriptSrc: ["'self'", "'unsafe-inline'", "'unsafe-eval'"],
        styleSrc: ["'self'", "'unsafe-inline'", 'https://fonts.googleapis.com'],
        fontSrc: ["'self'", 'https://fonts.gstatic.com'],
        imgSrc: ["'self'", 'data:', 'blob:'],
        connectSrc: ["'self'", 'ws:', 'wss:'],
      },
    },
    crossOriginEmbedderPolicy: false,
  }));

  app.use((req, res, next) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
    res.setHeader('Permissions-Policy', 'camera=(self), microphone=(), geolocation=(self)');
    next();
  });

  // ---- Analytics (beacon) ----

  app.post('/api/analytics/pageview', (req, res) => {
    res.status(204).end();
  });

  // ---- Auth routes (public) ----

  app.post('/api/auth/login', async (req, res) => {
    const clientIp = req.ip || req.socket.remoteAddress || 'unknown';
    const rateCheck = loginLimiter.check(clientIp);
    if (!rateCheck.allowed) {
      await insertSystemLog({
        actor: clientIp, role: 'unknown', checkpoint: '',
        event: 'rate_limit_exceeded', status: 'blocked',
      });
      return res.status(429).json({
        error: 'Too many login attempts. Try again later.',
        retryAfterMs: rateCheck.retryAfterMs,
      });
    }

    const { email, password } = req.body;
    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password required' });
    }
    try {
      const fp = computeSessionFingerprint(req.headers['user-agent'] || '');
      const family = crypto.randomBytes(18).toString('base64url');
      const { reachable, user } = await lookupUser({ email: String(email).trim() });

      if (!reachable) {
        // Database link is down: check the password against this machine's sealed cache.
        const offline = await verifyOffline(String(email), String(password));
        if (offline.ok === false) {
          await insertSystemLog({ actor: String(email), role: 'unknown', checkpoint: '', event: 'authentication_failure_offline', status: 'failed' });
          return res.status(offline.error === 'Invalid credentials' ? 401 : 503).json({ error: offline.error });
        }
        const u = offline.user;
        const payload: AuthPayload = {
          userId: u.id, email: u.email, name: u.name, role: u.role, checkpointIds: u.checkpoint_ids,
          fp, mustChangePassword: false, offline: true,
        };
        const refresh = signRefresh({ sub: u.id, fam: family, fp, off: true });
        setSessionCookies(req, res, signAccess(payload), refresh.token);
        await insertSystemLog({ actor: u.name, role: u.role, checkpoint: '', event: 'login_offline', status: 'success', reference_id: u.id });
        return res.json({ user: payload, offline: true });
      }

      const valid = user ? await bcrypt.compare(password, user.password_hash) : false;
      if (!user || !valid || (user as any).active === false) {
        if (user && (user as any).active === false) forgetUser({ id: user.id });
        await insertSystemLog({
          actor: email, role: 'unknown', checkpoint: '',
          event: 'authentication_failure', status: 'failed',
        });
        return res.status(401).json({ error: 'Invalid credentials' });
      }

      const payload: AuthPayload = {
        userId: user.id,
        email: user.email,
        name: user.name,
        role: user.role,
        checkpointIds: user.checkpoint_ids || [],
        fp,
        mustChangePassword: Boolean((user as any).must_change_password),
      };
      let refresh = signRefresh({ sub: user.id, fam: family, fp });
      try {
        await refreshStore.save({ jti: refresh.jti, family, userId: user.id, expiresAt: refresh.expiresAt });
      } catch (err) {
        if (!localStateEnabled()) throw err;
        refresh = signRefresh({ sub: user.id, fam: family, fp, off: true }); // link dropped between the two queries
      }
      rememberUser({ ...user, must_change_password: (user as any).must_change_password });
      setSessionCookies(req, res, signAccess(payload), refresh.token);
      await insertSystemLog({
        actor: user.name, role: user.role, checkpoint: '',
        event: 'login', status: 'success', reference_id: user.id,
      });
      res.json({ user: payload });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Login failed' });
    }
  });

  // Exchanges the refresh cookie for a new access token and a new refresh
  // token. The account is re-read so a role change or deactivation applies
  // within one access-token lifetime.
  app.post('/api/auth/refresh', async (req, res) => {
    try {
      const fp = computeSessionFingerprint(req.headers['user-agent'] || '');
      const result = await rotateRefresh(readCookies(req)[REFRESH_COOKIE], fp, refreshStore, localStateEnabled());
      if (result.ok === false) {
        clearSessionCookies(req, res);
        return res.status(result.status).json({ error: result.error });
      }
      const { reachable, user } = await lookupUser({ id: result.claims.sub });
      let payload: AuthPayload;
      if (reachable) {
        if (!user || (user as any).active === false) {
          await refreshStore.revokeFamily(result.claims.fam).catch(() => undefined);
          forgetUser({ id: result.claims.sub });
          clearSessionCookies(req, res);
          return res.status(401).json({ error: 'Account is no longer active.' });
        }
        payload = {
          userId: user.id, email: user.email, name: user.name, role: user.role,
          checkpointIds: user.checkpoint_ids || [], fp,
          mustChangePassword: Boolean((user as any).must_change_password),
        };
      } else {
        const cached = cachedUserById(result.claims.sub);
        if (!cached) {
          return res.status(503).json({ error: 'Database unreachable; the session cannot be renewed yet.' });
        }
        payload = {
          userId: cached.id, email: cached.email, name: cached.name, role: cached.role,
          checkpointIds: cached.checkpoint_ids, fp, mustChangePassword: false, offline: true,
        };
      }
      setSessionCookies(req, res, signAccess(payload), result.next);
      res.json({ user: payload });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Could not renew the session' });
    }
  });

  app.post('/api/auth/logout', async (req, res) => {
    try {
      const claims = verifyRefresh(readCookies(req)[REFRESH_COOKIE] || '');
      await refreshStore.revokeFamily(claims.fam).catch(() => undefined);
    } catch { /* no valid session: nothing to revoke */ }
    clearSessionCookies(req, res);
    res.json({ ok: true });
  });

  app.get('/api/auth/me', authMiddleware, (req, res) => {
    res.json({ user: req.authUser });
  });

  // First-time setup: needs the one-time code printed in the server console.
  app.get('/api/auth/setup', (req, res) => res.json({ available: setupAvailable() }));
  app.post('/api/auth/setup', handle(async (req) => {
    const out = await completeSetup(req.body);
    await insertSystemLog({ actor: out.email, role: 'ADMIN', checkpoint: '', event: 'setup_completed', status: 'success' });
    return { message: 'Admin account created. Sign in with it.' };
  }));

  app.post('/api/auth/change-password', authMiddleware, handle(async (req, res) => {
    const user = req.authUser!;
    await changePassword(user.userId, req.body?.currentPassword, req.body?.newPassword);
    await insertSystemLog({ actor: user.name, role: user.role, checkpoint: '', event: 'password_changed', status: 'success', reference_id: user.userId });
    const payload: AuthPayload = { ...user, mustChangePassword: false };
    delete (payload as any).iat; delete (payload as any).exp;
    forgetUser({ id: user.userId }); // the cached hash is now stale; it is refreshed at the next online sign-in
    setSessionCookies(req, res, signAccess(payload), null);
    return { user: payload };
  }));

  // ---- Public routes ----

  app.get('/api/health', (req, res) => {
    res.json({ status: 'ok', timestamp: new Date().toISOString() });
  });

  app.get('/api/neon/status', async (req, res) => {
    try {
      const status = await getNeonStatus();
      res.json({ ...status, pendingOutbox: outboxPending() });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Failed to check Neon status' });
    }
  });

  // ---- Protected routes ----

  // Checkpoints
  app.get('/api/checkpoints', authMiddleware, async (req, res) => {
    try {
      const allCheckpoints = await fetchCheckpoints();
      const user = req.authUser!;
      if (user.role === 'ADMIN') {
        return res.json(allCheckpoints);
      }
      const assigned = new Set(user.checkpointIds || []);
      const filtered = allCheckpoints.filter(cp => assigned.has(cp.id));
      res.json(filtered);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Failed to fetch checkpoints' });
    }
  });

  // Automatic checkpoint from the device location (limited to the user's assignments)
  app.post('/api/checkpoints/resolve', authMiddleware, handle(async (req) => {
    const user = req.authUser!;
    const out = await resolveCheckpoint(user, req.body);
    await insertSystemLog({
      actor: user.name, role: user.role, checkpoint: out.id, event: 'checkpoint_resolved', status: out.method,
      reference_id: out.distanceKm !== undefined ? `${out.distanceKm} km` : undefined,
    });
    return out;
  }));

  // System Logs (ADMIN only)
  app.get('/api/system-logs', authMiddleware, requireRole('ADMIN'), async (req, res) => {
    try {
      const { search, event, limit } = req.query;
      const logs = await fetchSystemLogs({
        search: search as string,
        event: event as string,
        limit: limit ? parseInt(limit as string, 10) : 100,
      });
      res.json(logs);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Failed to fetch system logs' });
    }
  });

  // Scans: Fetch from Neon
  app.get('/api/scans', authMiddleware, async (req, res) => {
    try {
      const scope = scopeOf(req.authUser!);
      const scans = await fetchAllScans();
      res.json(scope === null ? scans : scans.filter((s: any) => s.checkpoint_id && scope.includes(s.checkpoint_id)));
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Failed to fetch scans' });
    }
  });

  // Screening: send images to the AI engine, store the real result in the hash chain
  app.post('/api/screenings', authMiddleware, requireRole('OFFICER', 'ADMIN'), async (req, res) => {
    const user = req.authUser!;
    const { documentType, documentImage, liveImage, checkpointId } = req.body || {};
    if (!documentImage) return res.status(400).json({ error: 'A document image is required.' });
    try {
      const isGlobal = checkpointId === 'GLOBAL' && user.role === 'ADMIN';
      const checkpoints = await fetchCheckpoints();
      const checkpoint = isGlobal
        ? { id: 'GLOBAL', name: 'Global Scope (admin)' }
        : checkpoints.find((cp) => cp.id === checkpointId);
      const allowed = user.role === 'ADMIN' || (user.checkpointIds || []).includes(checkpointId);
      if (!checkpoint && checkpoints.length) {
        return res.status(400).json({ error: `Checkpoint '${checkpointId}' does not exist. Pick a checkpoint again from the header.` });
      }
      if (!allowed) return res.status(403).json({ error: 'You are not assigned to this checkpoint.' });

      const analysis = await runEngineScan(documentType || 'auto', documentImage, liveImage);
      const record = analysisToRecord(analysis, {
        officer: user.name,
        officerUid: user.userId,
        checkpointId: checkpointId || '',
        checkpointName: checkpoint?.name || checkpointId || '',
      });
      const saved = await insertScan(record);

      await insertAuditLog({
        action: saved.risk_verdict === 'CLEAR' ? 'SCREENING_CLEAR' : saved.risk_verdict === 'REVIEW' ? 'SCREENING_REVIEW' : 'SCREENING_HIGH_RISK',
        officer: user.name,
        officer_uid: user.userId,
        target_id: saved.id,
        remote_station: checkpointId || '',
        details: screeningAuditDetails(saved, analysis),
        hash_proof: saved.hash_proof,
      });
      await insertSystemLog({
        actor: user.name, role: user.role, checkpoint: checkpointId || '',
        event: 'screening_completed', status: saved.risk_verdict, reference_id: saved.id,
      });
      res.status(201).json({ ...saved, analysis });
    } catch (err: any) {
      const status = err instanceof EngineError ? err.status : 500;
      await insertSystemLog({
        actor: user.name, role: user.role, checkpoint: checkpointId || '',
        event: 'screening_failed', status: 'error',
      });
      res.status(status).json({ error: err?.message || 'Screening failed' });
    }
  });

  app.get('/api/scans/:id', authMiddleware, async (req, res) => {
    const scan = await fetchScanById(req.params.id);
    if (!scan) return res.status(404).json({ error: 'Scan not found' });
    if (!inScope(req.authUser!, scan.checkpoint_id)) return res.status(403).json({ error: 'This record belongs to another checkpoint.' });
    res.json(scan);
  });

  // ---- Officer decisions, two-person rule, receipts ----
  app.post('/api/scans/:id/decision', authMiddleware, handle(async (req) => recordDecision(req.authUser!, req.params.id, req.body)));
  app.get('/api/scans/:id/decisions', authMiddleware, handle(async (req) => decisionsForScan(req.authUser!, req.params.id)));
  app.get('/api/scans/:id/receipt', authMiddleware, handle(async (req) => receiptFor(req.authUser!, req.params.id)));
  app.get('/api/decisions/pending', authMiddleware, handle(async (req) => pendingCosigns(req.authUser!)));
  app.post('/api/decisions/:id/cosign', authMiddleware, handle(async (req) => cosign(req.authUser!, Number(req.params.id), req.body)));
  // Anyone holding a receipt can check it; it reveals nothing beyond the receipt itself.
  app.post('/api/public/verify-receipt', handle(async (req) => verifyReceipt(req.body)));

  // ---- Security & trust administration (ADMIN) ----
  const admin = [authMiddleware, requireRole('ADMIN')];
  app.get('/api/admin/users', ...admin, handle(async () => listUsers()));
  app.post('/api/admin/users', ...admin, handle(async (req) => {
    const out = await createManagedUser(req.body);
    await insertSystemLog({ actor: req.authUser!.name, role: 'ADMIN', checkpoint: '', event: 'user_created', status: 'success', reference_id: out.id });
    return out;
  }));
  app.post('/api/admin/users/:id/active', ...admin, handle(async (req) => {
    forgetUser({ id: req.params.id }); // the offline sign-in copy must not outlive this change
    if (req.params.id === req.authUser!.userId) throw Object.assign(new Error('You cannot deactivate yourself.'), { status: 400 });
    await setUserActive(req.params.id, req.body?.active === true);
    await insertSystemLog({ actor: req.authUser!.name, role: 'ADMIN', checkpoint: '', event: req.body?.active ? 'user_activated' : 'user_deactivated', status: 'success', reference_id: req.params.id });
    return { ok: true };
  }));
  app.post('/api/admin/users/:id/reset-password', ...admin, handle(async (req) => {
    forgetUser({ id: req.params.id }); // the offline sign-in copy must not outlive this change
    const temporaryPassword = await resetUserPassword(req.params.id);
    await insertSystemLog({ actor: req.authUser!.name, role: 'ADMIN', checkpoint: '', event: 'password_reset', status: 'success', reference_id: req.params.id });
    return { temporaryPassword };
  }));
  app.post('/api/admin/checkpoints', ...admin, handle(async (req) => {
    await addCheckpoint(req.body);
    await insertSystemLog({ actor: req.authUser!.name, role: 'ADMIN', checkpoint: '', event: 'checkpoint_saved', status: 'success', reference_id: String(req.body?.id || '') });
    return { ok: true };
  }));
  app.get('/api/security/insider', ...admin, handle(async (req) => insiderAlerts(Number(req.query.days) || 30)));
  app.get('/api/security/registry', ...admin, handle(async () => listRegistry()));
  app.get('/api/security/batches', ...admin, handle(async () => listBatches()));
  app.post('/api/security/batches/seal', ...admin, handle(async (req) => ({ batch: await sealBatch(req.authUser!.name) })));
  // Batch roots in the database vs the roots the Fabric ledger recorded at sealing time.
  app.get('/api/security/fabric/verify', ...admin, handle(async () => verifyAgainstFabric()));
  app.get('/api/security/incident-report', ...admin, handle(async (req) => {
    const report = await incidentReport(req.authUser!, req.query.from as string, req.query.to as string);
    await insertSystemLog({ actor: req.authUser!.name, role: 'ADMIN', checkpoint: '', event: 'incident_report_generated', status: 'success', reference_id: report.report_sha256.slice(0, 16) });
    return report;
  }));

  app.get('/api/engine/health', authMiddleware, async (req, res) => {
    try {
      res.json(await fetchEngine('/api/health'));
    } catch (err: any) {
      res.status(503).json({ status: 'unreachable', error: err?.message });
    }
  });

  app.get('/api/engine/models', authMiddleware, requireRole('ADMIN'), async (req, res) => {
    try {
      res.json(await fetchEngine('/api/system/models'));
    } catch (err: any) {
      res.status(503).json({ error: `Screening engine unreachable: ${err?.message}` });
    }
  });

  // Scans: Capture & Store into Neon (with input sanitization)
  // Records are created only by /api/screenings from real engine output; a
  // direct insert would let a client write any verdict into the hash chain.
  app.post('/api/scans', authMiddleware, (req, res) => {
    res.status(410).json({ error: 'Scans are created by POST /api/screenings.' });
  });

  // Replay records queued on this gateway while the database was unreachable
  // (also runs automatically; see OUTBOX_SYNC_SECONDS below).
  app.post('/api/outbox/sync', authMiddleware, requireRole('ADMIN'), async (req, res) => {
    try {
      res.json(await syncOutboxToNeon());
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Outbox sync failed' });
    }
  });

  // Store-and-Forward Sync Batch
  app.post('/api/scans/sync-batch', authMiddleware, requireRole('ADMIN'), async (req, res) => {
    try {
      const { scans, stationId } = req.body;
      if (!Array.isArray(scans)) {
        return res.status(400).json({ error: 'scans array required' });
      }
      const result = await syncBatchScans(scans);
      res.json({
        success: true,
        stationId: stationId || null,
        ...result,
        syncedAt: new Date().toISOString(),
      });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Batch sync to Neon failed' });
    }
  });

  // Audit Logs: Fetch from Neon (optionally for one record, with signature check)
  app.get('/api/audit-logs', authMiddleware, async (req, res) => {
    try {
      const targetId = typeof req.query.targetId === 'string' ? req.query.targetId : '';
      if (targetId) {
        const target = await fetchScanById(targetId);
        if (target && !inScope(req.authUser!, target.checkpoint_id)) return res.status(403).json({ error: 'This record belongs to another checkpoint.' });
        const logs = await fetchAuditLogsForTarget(targetId);
        return res.json(logs.map((l: any) => {
          let signature: 'valid' | 'legacy' | 'invalid' | 'unsigned' = 'unsigned';
          if (l.hmac_signature) {
            try {
              signature = auditSignatureStatus({
                action: l.action, officer: l.officer, officer_uid: l.officer_uid, target_id: l.target_id,
                details: l.details, created_at: new Date(l.created_at).toISOString(), hmac_signature: l.hmac_signature,
              });
            } catch {
              signature = 'invalid';
            }
          }
          return { ...l, signature, signature_valid: signature === 'valid' ? true : signature === 'invalid' ? false : null };
        }));
      }
      const scope = scopeOf(req.authUser!);
      const logs = await fetchAllAuditLogs();
      res.json(scope === null ? logs : logs.filter((l: any) => scope.includes(l.remote_station)));
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Failed to fetch audit logs' });
    }
  });

  // Audit Logs: Insert into Neon
  app.post('/api/audit-logs', authMiddleware, async (req, res) => {
    try {
      // The author is whoever is signed in — never a name taken from the request.
      const user = req.authUser!;
      const saved = await insertAuditLog({
        ...req.body,
        officer: user.name,
        officer_uid: user.userId,
        action: String(req.body?.action || 'NOTE').slice(0, 64),
      });
      res.status(201).json(saved);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Failed to insert audit log' });
    }
  });

  // ---- Blockchain chain verification (ADMIN only) ----

  app.get('/api/chain/verify', authMiddleware, requireRole('ADMIN'), async (req, res) => {
    try {
      const result = await verifyChainIntegrity();
      await insertSystemLog({
        actor: req.authUser!.name, role: req.authUser!.role, checkpoint: '',
        event: 'chain_verification', status: result.valid ? 'success' : 'failed',
      });
      res.json(result);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Chain verification failed' });
    }
  });

  app.get('/api/chain/status', authMiddleware, async (req, res) => {
    try {
      const result = await verifyChainIntegrity();
      res.json({
        valid: result.valid,
        totalBlocks: result.totalBlocks,
        latestBlock: result.latestBlock,
        genesisHash: result.genesisHash.slice(0, 12) + '...',
        latestHash: result.latestHash ? result.latestHash.slice(0, 12) + '...' : 'N/A',
      });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Chain status check failed' });
    }
  });

  // ---- Reference Data (data.gov.in datasets — ADMIN only) ----

  app.get('/api/reference/datasets', authMiddleware, requireRole('ADMIN'), async (req, res) => {
    try {
      const { category } = req.query;
      const datasets = await fetchRefDatasets(category as string | undefined);
      res.json(datasets);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Failed to fetch reference datasets' });
    }
  });

  app.get('/api/reference/stats', authMiddleware, requireRole('ADMIN'), async (req, res) => {
    try {
      const stats = await fetchRefDatasetStats();
      res.json(stats);
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Failed to fetch reference stats' });
    }
  });

  app.post('/api/reference/seed', authMiddleware, requireRole('ADMIN'), async (req, res) => {
    try {
      const { default: fs } = await import('fs');
      const catalogPath = path.resolve(process.cwd(), '..', 'backend', 'data', 'reference', 'datasets_catalog.json');
      if (!fs.existsSync(catalogPath)) {
        return res.status(404).json({ error: 'Dataset catalog not found at ' + catalogPath });
      }
      const catalog = JSON.parse(fs.readFileSync(catalogPath, 'utf-8'));
      const count = await seedRefDatasets(catalog.map((d: any) => ({
        id: d.id,
        name: d.name,
        source: d.source,
        category: d.category,
        status: d.status,
        record_count: 0,
      })));
      await insertSystemLog({
        actor: req.authUser!.name, role: req.authUser!.role, checkpoint: '',
        event: 'reference_data_seeded', status: 'success',
        reference_id: `${count} datasets`,
      });
      res.json({ message: `Seeded ${count} dataset records`, count });
    } catch (err: any) {
      res.status(500).json({ error: err?.message || 'Failed to seed reference datasets' });
    }
  });

  // Scheduled maintenance for serverless hosting, where no timer survives
  // between requests. Vercel Cron sends `Authorization: Bearer $CRON_SECRET`.
  app.get('/api/cron/maintenance', async (req, res) => {
    const secret = process.env.CRON_SECRET;
    const sent = req.headers.authorization || '';
    const expected = `Bearer ${secret}`;
    if (!secret || sent.length !== expected.length || !crypto.timingSafeEqual(Buffer.from(sent), Buffer.from(expected))) {
      return res.status(401).json({ error: 'Unauthorized' });
    }
    res.json({ ok: true, ...(await runMaintenance()) });
  });

  // Anything under /api that no route above matched must 404 as JSON.
  // Without this it falls through to the SPA fallback below and returns
  // index.html with a 200, which reads as success to an API client.
  app.use('/api', (_req, res) => {
    res.status(404).json({ error: 'Not found' });
  });

  await securityStartup();
  return app;
}

/** Long-running server for a checkpoint machine or a VM. */
async function startServer() {
  const app = await createApp();
  const PORT = Number(process.env.PORT || 3000);
  const httpServer = http.createServer(app);

  // Vite middleware for development vs Static in production
  if (process.env.NODE_ENV !== 'production') {
    const { createServer: createViteServer } = await import('vite'); // dev only: kept out of the production bundle
    const vite = await createViteServer({
      // Live reload shares port 3000; a separate HMR port silently failed to
      // connect, leaving the browser on stale screens.
      server: { middlewareMode: true, hmr: { server: httpServer } },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  setTimeout(runMaintenance, 5_000);

  // Store-and-forward: scans taken while the database was unreachable are
  // kept on disk and written back, in order, once it answers again.
  const restored = loadOutboxIntoMemory();
  if (restored) console.log(`Outbox: ${restored} scan(s) from an earlier offline period are waiting to sync.`);
  const runOutboxSync = () => syncOutboxToNeon().catch((err) => console.warn('Outbox sync failed:', (err as Error).message));
  setTimeout(runOutboxSync, 8_000);
  setInterval(runOutboxSync, Number(process.env.OUTBOX_SYNC_SECONDS || 30) * 1000);
  setInterval(runMaintenance, Number(process.env.BATCH_INTERVAL_MINUTES || 10) * 60 * 1000);

  httpServer.listen(PORT, '0.0.0.0', () => {
    console.log(`PEHCHAAN gateway running on http://0.0.0.0:${PORT}`);
    console.log(`Engine link: ${describeEngineLink()}`);
  });
}

// On Vercel the app is created per function instance by api/index.js instead.
if (!process.env.VERCEL) startServer();

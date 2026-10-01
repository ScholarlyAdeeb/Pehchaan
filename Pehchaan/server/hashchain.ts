import crypto from 'crypto';

const GENESIS_SEED = 'PEHCHAAN_GENESIS_BLOCK_v1_SIH26188';
const HMAC_SECRET = process.env.HMAC_SECRET as string;
if (!HMAC_SECRET) throw new Error('HMAC_SECRET is not set (server/bootstrap-secrets.ts must load first)');
// Entries written before secrets were generated were signed with this published
// default. They are reported as 'legacy', never as valid.
const LEGACY_HMAC_SECRET = 'pehchaan-hmac-secret-change-me';

export const GENESIS_HASH = crypto.createHash('sha256').update(GENESIS_SEED).digest('hex');

export function computeScanHash(prevHash: string, scanData: {
  id: string;
  document_type: string;
  presenter_name: string;
  risk_score: number;
  risk_verdict: string;
  timestamp: string;
  officer_uid: string;
  doc_number?: string;
  provenance_hash?: string | null;
}): string {
  const payload = [
    prevHash,
    scanData.id,
    scanData.document_type,
    scanData.presenter_name,
    String(scanData.risk_score),
    scanData.risk_verdict,
    scanData.timestamp,
    scanData.officer_uid,
    scanData.doc_number || '',
    // Appended only when present so blocks written before provenance existed still verify.
    ...(scanData.provenance_hash ? [scanData.provenance_hash] : []),
  ].join('|');
  return crypto.createHash('sha256').update(payload).digest('hex');
}

export function abbreviateHash(fullHash: string): string {
  if (fullHash.length < 12) return fullHash;
  return '0x' + fullHash.slice(0, 4) + '...' + fullHash.slice(-4);
}

export function signAuditLog(logData: {
  action: string;
  officer: string;
  officer_uid: string;
  target_id: string;
  details: string;
  created_at: string;
}, secret: string = HMAC_SECRET): string {
  const payload = [
    logData.action,
    logData.officer,
    logData.officer_uid,
    logData.target_id,
    logData.details,
    logData.created_at,
  ].join('|');
  return crypto.createHmac('sha256', secret).update(payload).digest('hex');
}

export function auditSignatureStatus(logData: Parameters<typeof verifyAuditSignature>[0]): 'valid' | 'legacy' | 'invalid' {
  const eq = (a: string) => a.length === logData.hmac_signature.length &&
    crypto.timingSafeEqual(Buffer.from(a, 'hex'), Buffer.from(logData.hmac_signature, 'hex'));
  if (eq(signAuditLog(logData))) return 'valid';
  if (eq(signAuditLog(logData, LEGACY_HMAC_SECRET))) return 'legacy';
  return 'invalid';
}

export function verifyAuditSignature(logData: {
  action: string;
  officer: string;
  officer_uid: string;
  target_id: string;
  details: string;
  created_at: string;
  hmac_signature: string;
}): boolean {
  const expected = signAuditLog(logData);
  return crypto.timingSafeEqual(
    Buffer.from(expected, 'hex'),
    Buffer.from(logData.hmac_signature, 'hex')
  );
}

export function computeSessionFingerprint(userAgent: string): string {
  return crypto.createHash('sha256').update(userAgent || 'unknown').digest('hex').slice(0, 16);
}

const FIELD_MAX_LENGTHS: Record<string, number> = {
  id: 64, document_type: 64, doc_code: 64, country_code: 16, country_name: 128,
  presenter_name: 255, risk_verdict: 32, checksum_status: 16, lane: 64,
  officer: 128, officer_uid: 64, doc_number: 64, dob: 32,
  expiry_visual: 64, expiry_mrz: 64, face_match_rate: 32, ela_anomaly_rate: 32,
  remote_station_id: 64, action: 128, target_id: 64, remote_station: 64,
};

const HTML_TAG_RE = /<[^>]*>/g;

export function sanitizeString(value: string, maxLen: number): string {
  return value.replace(HTML_TAG_RE, '').trim().slice(0, maxLen);
}

export function sanitizeScanInput(scan: Record<string, any>): Record<string, any> {
  const cleaned: Record<string, any> = {};
  for (const [key, value] of Object.entries(scan)) {
    if (typeof value === 'string') {
      const maxLen = FIELD_MAX_LENGTHS[key] || 512;
      cleaned[key] = sanitizeString(value, maxLen);
    } else if (typeof value === 'number') {
      cleaned[key] = Number.isFinite(value) ? value : 0;
    } else {
      cleaned[key] = value;
    }
  }
  return cleaned;
}

export interface RateLimitEntry {
  count: number;
  resetAt: number;
}

export class RateLimiter {
  private store = new Map<string, RateLimitEntry>();
  constructor(
    private maxAttempts: number,
    private windowMs: number,
  ) {}

  check(key: string): { allowed: boolean; remaining: number; retryAfterMs: number } {
    const now = Date.now();
    const entry = this.store.get(key);

    if (!entry || now > entry.resetAt) {
      this.store.set(key, { count: 1, resetAt: now + this.windowMs });
      return { allowed: true, remaining: this.maxAttempts - 1, retryAfterMs: 0 };
    }

    if (entry.count >= this.maxAttempts) {
      return { allowed: false, remaining: 0, retryAfterMs: entry.resetAt - now };
    }

    entry.count++;
    return { allowed: true, remaining: this.maxAttempts - entry.count, retryAfterMs: 0 };
  }

  cleanup() {
    const now = Date.now();
    for (const [key, entry] of this.store) {
      if (now > entry.resetAt) this.store.delete(key);
    }
  }
}

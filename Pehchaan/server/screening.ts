import type { DbScanRecord } from './neon.ts';
import { engineBaseUrl, engineRequest, type EngineResponse } from './engine-transport.ts';

export const PYTHON_API_URL = engineBaseUrl();

const ENGINE_TYPES: Record<string, string> = {
  auto: 'auto',
  passport: 'passport',
  visa: 'visa',
  'national-id': 'national_id',
  aadhaar: 'aadhar',
  pan: 'pan',
  'driving-licence': 'driving_license',
  permit: 'permit',
};

const DOC_LABELS: Record<string, string> = {
  passport: 'Passport',
  visa: 'Visa',
  national_id: 'National ID',
  aadhar: 'Aadhaar',
  pan: 'PAN card',
  driving_license: 'Driving licence',
  permit: 'Border permit',
};

const UI_TYPES: Record<string, string> = {
  passport: 'passport',
  visa: 'visa',
  national_id: 'national-id',
  aadhar: 'aadhaar',
  pan: 'pan',
  driving_license: 'driving-licence',
  permit: 'permit',
};

const COUNTRIES: Record<string, string> = {
  IND: 'India', NPL: 'Nepal', BGD: 'Bangladesh', BTN: 'Bhutan', PAK: 'Pakistan', LKA: 'Sri Lanka',
  MMR: 'Myanmar', CHN: 'China', USA: 'United States', GBR: 'United Kingdom', UTO: 'Utopia (ICAO specimen)',
};

const INDIAN_DOCS = new Set(['aadhar', 'pan', 'driving_license']);

function engineHeaders(): Record<string, string> {
  return process.env.ENGINE_API_KEY ? { 'x-engine-key': process.env.ENGINE_API_KEY } : {};
}

// Document numbers are stored only masked (plus a keyed hash for look-ups):
// replace every occurrence of the full number inside the stored analysis.
export function redactForStorage(analysis: any): any {
  const full: string | undefined = analysis?.identity?.document_number;
  const masked: string | undefined = analysis?.identity?.document_number_masked;
  if (!full || !masked) return analysis;
  const compact = full.replace(/[^A-Za-z0-9]/g, '');
  const grouped = compact.match(/.{1,4}/g)?.join(' ') || compact; // Aadhaar prints as 1234 5678 9012
  const variants = new Set([full, compact, grouped].filter((v) => v.length >= 5));
  let text = JSON.stringify(analysis);
  for (const v of variants) text = text.split(v).join(masked);
  const out = JSON.parse(text);
  out.identity.document_number = masked;
  return out;
}

export class EngineError extends Error {
  constructor(message: string, public status = 502) {
    super(message);
  }
}

function dataUrlToBlob(dataUrl: string, field: string): Blob {
  const m = /^data:(image\/[a-z0-9.+-]+);base64,(.+)$/i.exec(dataUrl || '');
  if (!m) throw new EngineError(`${field} must be an image data URL`, 400);
  return new Blob([Buffer.from(m[2], 'base64')], { type: m[1] });
}

export async function runEngineScan(documentType: string, documentImage: string, liveImage?: string | null) {
  const engineType = ENGINE_TYPES[documentType];
  if (!engineType) throw new EngineError(`Unknown document type '${documentType}'`, 400);

  const form = new FormData();
  form.append('document_type', engineType);
  form.append('document', dataUrlToBlob(documentImage, 'documentImage'), 'document.jpg');
  if (liveImage) form.append('live_face', dataUrlToBlob(liveImage, 'liveImage'), 'live.jpg');

  let res: EngineResponse;
  try {
    res = await engineRequest('/api/documents/scan', { method: 'POST', headers: engineHeaders(), form, timeoutMs: 120_000 });
  } catch (err: any) {
    throw new EngineError(
      `Screening engine is not reachable at ${PYTHON_API_URL}. Start the Python backend (start_all.bat). (${err?.message || err})`,
      503,
    );
  }
  if (!res.ok) {
    const text = res.text();
    let detail = text;
    try { detail = JSON.parse(text).detail || text; } catch { /* plain text */ }
    throw new EngineError(`Screening engine rejected the scan: ${detail}`, res.status === 400 ? 400 : 502);
  }
  return res.json();
}

export async function fetchEngine(path: string) {
  const res = await engineRequest(path, { headers: engineHeaders(), timeoutMs: 15_000 });
  if (!res.ok) throw new EngineError(`Engine returned ${res.status}`);
  return res.json();
}

// The audit entry carries the whole evaluation so the signed log alone
// explains the verdict, even if the scan record were later altered.
export function screeningAuditDetails(saved: DbScanRecord, analysis: any): string {
  const rows: any[] = analysis.evaluation || [];
  const mark: Record<string, string> = { pass: 'PASS', warn: 'WARN', fail: 'FAIL', skip: 'SKIP' };
  const lines = rows.map((r) => `[${mark[r.status] || r.status}] ${r.check} (${r.method}; measured ${r.measured}): ${r.sentence}`);
  const floors = (analysis.risk?.overrides || []).map((o: string) => `Floor: ${o}`);
  return [
    `${saved.doc_code} for ${saved.presenter_name}: ${saved.risk_verdict} (${saved.risk_score}/100, weighted ${analysis.risk?.weighted_score}).`,
    ...lines,
    ...floors,
  ].join('\n');
}

function istNow(d: Date): string {
  return d.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }) + ' IST';
}

export function analysisToRecord(
  analysis: any,
  ctx: { officer: string; officerUid: string; checkpointId: string; checkpointName: string },
): DbScanRecord {
  const identity = analysis.identity || {};
  const risk = analysis.risk || {};
  const mrz = analysis.mrz;
  const fields = analysis.ocr?.extracted_fields || {};
  const docType: string = analysis.document_type;

  let checksum: 'PASS' | 'FAIL' | 'N/A' = 'N/A';
  if (mrz?.detected) {
    const checks = [...(mrz.fields || []).map((f: any) => f.valid), mrz.composite_valid].filter((v) => v !== null && v !== undefined);
    checksum = checks.length && checks.every(Boolean) ? 'PASS' : checks.some((v: boolean) => v === false) ? 'FAIL' : 'N/A';
  }

  const nat = (identity.nationality || (INDIAN_DOCS.has(docType) ? 'IND' : '') || '').toUpperCase().slice(0, 3);
  const verdict = risk.verdict === 'REJECT' ? 'HIGH RISK' : risk.verdict;
  const topFinding = (risk.contributing_factors || [])[0] || 'No risk indicators found.';
  const face = analysis.face || {};
  const now = new Date();

  return {
    id: `SCN-${String(analysis.id).replace(/-/g, '').slice(0, 10).toUpperCase()}`,
    document_type: UI_TYPES[docType] || docType,
    doc_code: DOC_LABELS[docType] || docType,
    country_code: nat,
    country_name: COUNTRIES[nat] || nat || 'Unknown',
    presenter_name: identity.name || 'Name not readable',
    risk_score: risk.risk_score,
    risk_verdict: verdict,
    checksum_status: checksum,
    findings: topFinding,
    timestamp: istNow(now),
    local_time: now.toISOString(),
    lane: ctx.checkpointName,
    officer: ctx.officer,
    officer_uid: ctx.officerUid,
    hash_proof: '',
    full_hash: '',
    block_height: '',
    flag_reason: verdict === 'CLEAR' ? undefined : topFinding,
    mrz_string: mrz?.raw_lines?.[0],
    mrz_line2: mrz?.raw_lines?.[1],
    doc_number: identity.document_number_masked || undefined,
    doc_number_hash: identity.document_number_hash || undefined,
    provenance_hash: analysis.provenance?.combined || undefined,
    image_fingerprint: analysis.image_fingerprint?.page
      ? `${analysis.image_fingerprint.page}:${analysis.image_fingerprint.portrait || ''}` : undefined,
    dob: identity.date_of_birth || undefined,
    expiry_visual: fields.expiry_date || fields.valid_till || undefined,
    expiry_mrz: mrz?.date_of_expiry || undefined,
    face_match_rate: face.attempted && face.similarity != null ? `${(face.similarity * 100).toFixed(1)}%` : 'Not run',
    ela_anomaly_rate: `${analysis.tampering?.tampering_score ?? 0}/100`,
    checkpoint_id: ctx.checkpointId,
    analysis: redactForStorage(analysis),
  };
}

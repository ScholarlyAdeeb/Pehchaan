import { AuditEntry, ScreeningRecord, NeonTelemetryStatus } from '../types';

const LOCAL_STORAGE_QUEUE_KEY = 'pehchaan_offline_queue_v1';
const LOW_BANDWIDTH_KEY = 'pehchaan_low_bandwidth_mode';
const REMOTE_STATION_KEY = 'pehchaan_remote_station_id';

export function getActiveRemoteStation(): string {
  if (typeof window === 'undefined') return '';
  return localStorage.getItem(REMOTE_STATION_KEY) || '';
}

export function setActiveRemoteStation(stationId: string): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem(REMOTE_STATION_KEY, stationId);
  }
}

export function isLowBandwidthMode(): boolean {
  if (typeof window === 'undefined') return false;
  return localStorage.getItem(LOW_BANDWIDTH_KEY) === 'true';
}

export function setLowBandwidthMode(enabled: boolean): void {
  if (typeof window !== 'undefined') {
    localStorage.setItem(LOW_BANDWIDTH_KEY, enabled ? 'true' : 'false');
  }
}

export function getOfflineQueue(): ScreeningRecord[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = localStorage.getItem(LOCAL_STORAGE_QUEUE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    console.error('Error reading offline queue:', e);
    return [];
  }
}

export function saveToOfflineQueue(record: ScreeningRecord): void {
  if (typeof window === 'undefined') return;
  const current = getOfflineQueue();
  const idx = current.findIndex(r => r.id === record.id);
  const updatedRecord: ScreeningRecord = {
    ...record,
    syncStatus: 'QUEUED_LOCAL',
    remoteStationId: record.remoteStationId || getActiveRemoteStation(),
  };

  if (idx >= 0) {
    current[idx] = updatedRecord;
  } else {
    current.unshift(updatedRecord);
  }
  localStorage.setItem(LOCAL_STORAGE_QUEUE_KEY, JSON.stringify(current));
}

export function removeFromOfflineQueue(ids: string[]): void {
  if (typeof window === 'undefined') return;
  const current = getOfflineQueue();
  const idSet = new Set(ids);
  const filtered = current.filter(r => !idSet.has(r.id));
  localStorage.setItem(LOCAL_STORAGE_QUEUE_KEY, JSON.stringify(filtered));
}

function authHeaders(token: string): Record<string, string> {
  return { 'Authorization': `Bearer ${token}` };
}

function recordToDbPayload(record: ScreeningRecord) {
  const lowBw = isLowBandwidthMode();
  return {
    id: record.id,
    document_type: record.documentType,
    doc_code: record.docCode,
    country_code: record.countryCode,
    country_name: record.countryName,
    presenter_name: record.presenterName,
    risk_score: record.riskScore,
    risk_verdict: record.riskVerdict,
    checksum_status: record.checksumStatus,
    findings: record.findings,
    timestamp: record.timestamp,
    local_time: record.localTime,
    lane: record.lane,
    officer: record.officer,
    officer_uid: record.officerUid,
    hash_proof: record.hashProof,
    full_hash: record.fullHash,
    block_height: record.blockHeight,
    flag_reason: record.flagReason,
    mrz_string: record.mrzString,
    mrz_line2: record.mrzLine2,
    doc_number: record.docNumber,
    dob: record.dob,
    expiry_visual: record.expiryVisual,
    expiry_mrz: record.expiryMrz,
    face_match_rate: record.faceMatchRate,
    ela_anomaly_rate: record.elaAnomalyRate,
    remote_station_id: record.remoteStationId || getActiveRemoteStation(),
    sync_status: 'SYNCED',
    _low_bandwidth: lowBw,
  };
}

export function dbPayloadToRecord(row: any): ScreeningRecord {
  return {
    id: row.id,
    documentType: row.document_type || '',
    docCode: row.doc_code || 'Document',
    countryCode: row.country_code || '',
    countryName: row.country_name || 'Unknown',
    presenterName: row.presenter_name || 'Name not readable',
    riskScore: Number(row.risk_score) || 0,
    riskVerdict: row.risk_verdict || 'REVIEW',
    checksumStatus: row.checksum_status || 'N/A',
    findings: row.findings || '',
    timestamp: row.timestamp || '',
    localTime: row.local_time || '',
    lane: row.lane || '',
    officer: row.officer || '',
    officerUid: row.officer_uid || '',
    hashProof: row.hash_proof || '',
    fullHash: row.full_hash || '',
    blockHeight: row.block_height || '',
    checkpointId: row.checkpoint_id || undefined,
    hasAnalysis: Boolean(row.has_analysis || row.analysis),
    analysis: row.analysis || undefined,
    flagReason: row.flag_reason,
    mrzString: row.mrz_string,
    mrzLine2: row.mrz_line2,
    docNumber: row.doc_number,
    dob: row.dob,
    expiryVisual: row.expiry_visual,
    expiryMrz: row.expiry_mrz,
    faceMatchRate: row.face_match_rate,
    elaAnomalyRate: row.ela_anomaly_rate,
    remoteStationId: row.remote_station_id,
    syncStatus: (row.sync_status as any) || 'SYNCED',
  };
}

export async function fetchScansFromNeon(token: string): Promise<ScreeningRecord[]> {
  try {
    const res = await fetch('/api/scans', {
      method: 'GET',
      headers: { 'Accept': 'application/json', ...authHeaders(token) },
    });
    if (!res.ok) {
      throw new Error(`Failed to fetch from Neon API: ${res.statusText}`);
    }
    const data = await res.json();
    const serverRecords = data.map(dbPayloadToRecord);

    const offline = getOfflineQueue();
    if (offline.length > 0) {
      const serverIds = new Set(serverRecords.map((r: ScreeningRecord) => r.id));
      const unSynced = offline.filter(r => !serverIds.has(r.id));
      return [...unSynced, ...serverRecords];
    }

    return serverRecords;
  } catch (err) {
    console.warn('Network unreachable or remote offline; loading from local queue & cache:', err);
    return getOfflineQueue();
  }
}

export async function runScreening(
  params: { documentType: string; documentImage: string; liveImage?: string | null; checkpointId: string },
  token: string,
): Promise<ScreeningRecord> {
  const res = await fetch('/api/screenings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
    body: JSON.stringify(params),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.error || `Screening failed (HTTP ${res.status})`);
  }
  return dbPayloadToRecord(body);
}

export async function fetchScanDetail(id: string, token: string): Promise<ScreeningRecord | null> {
  const res = await fetch(`/api/scans/${encodeURIComponent(id)}`, { headers: authHeaders(token) });
  if (!res.ok) return null;
  return dbPayloadToRecord(await res.json());
}

export async function fetchAuditTrail(targetId: string, token: string): Promise<AuditEntry[]> {
  const res = await fetch(`/api/audit-logs?targetId=${encodeURIComponent(targetId)}`, { headers: authHeaders(token) });
  if (!res.ok) return [];
  return res.json();
}

export async function captureAndStoreScan(record: ScreeningRecord, token: string): Promise<ScreeningRecord> {
  const stationId = getActiveRemoteStation();
  const recordWithStation: ScreeningRecord = {
    ...record,
    remoteStationId: stationId || undefined,
  };

  if (typeof navigator !== 'undefined' && !navigator.onLine) {
    saveToOfflineQueue(recordWithStation);
    return { ...recordWithStation, syncStatus: 'QUEUED_LOCAL' };
  }

  try {
    const payload = recordToDbPayload(recordWithStation);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6000);

    const res = await fetch('/api/scans', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (!res.ok) {
      throw new Error(`Server returned status ${res.status}`);
    }

    await res.json();
    return { ...recordWithStation, syncStatus: 'SYNCED' };
  } catch (err) {
    console.warn('Direct Neon transmission failed; store-and-forward queueing locally:', err);
    saveToOfflineQueue(recordWithStation);
    return { ...recordWithStation, syncStatus: 'QUEUED_LOCAL' };
  }
}

export async function syncOfflineQueueToNeon(token: string): Promise<{ synced: number; remaining: number; error?: string }> {
  const queue = getOfflineQueue();
  if (queue.length === 0) {
    return { synced: 0, remaining: 0 };
  }

  const stationId = getActiveRemoteStation();
  const dbPayloads = queue.map(recordToDbPayload);

  try {
    const res = await fetch('/api/scans/sync-batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify({
        stationId,
        scans: dbPayloads,
      }),
    });

    if (!res.ok) {
      throw new Error(`Neon batch sync failed: ${res.statusText}`);
    }

    const result = await res.json();
    const syncedIds = queue.slice(0, result.syncedCount).map(r => r.id);
    removeFromOfflineQueue(syncedIds);

    return {
      synced: result.syncedCount,
      remaining: getOfflineQueue().length,
    };
  } catch (err: any) {
    console.error('Offline queue flush to Neon encountered error:', err);
    return {
      synced: 0,
      remaining: queue.length,
      error: err?.message || 'Replication failed',
    };
  }
}

export async function checkNeonStatus(token?: string): Promise<NeonTelemetryStatus> {
  try {
    const headers: Record<string, string> = { 'Accept': 'application/json' };
    if (token) Object.assign(headers, authHeaders(token));
    const res = await fetch('/api/neon/status', { headers });
    if (!res.ok) {
      throw new Error('Neon status query failed');
    }
    return await res.json();
  } catch (err: any) {
    return {
      connected: false,
      configured: false,
      provider: 'Neon Serverless PostgreSQL',
      host: 'Air-Gapped / Remote Outpost',
      database: 'Local Buffer',
      totalScans: getOfflineQueue().length,
      totalAuditLogs: 0,
      latencyMs: 0,
      mode: 'OFFLINE_STORE_AND_FORWARD',
      message: 'Network offline. All records captured and safely buffered.',
    };
  }
}

export async function logAuditToNeon(action: string, details: string, targetId: string, officerName: string, officerUid: string, hashProof: string, token: string) {
  const payload = {
    action,
    officer: officerName,
    officer_uid: officerUid,
    target_id: targetId,
    remote_station: getActiveRemoteStation(),
    details,
    hash_proof: hashProof,
  };

  try {
    await fetch('/api/audit-logs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders(token) },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    console.warn('Could not post audit log to Neon, will be caught on next connection:', e);
  }
}

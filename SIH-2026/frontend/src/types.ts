export type UserRole = 'OFFICER' | 'POST_INCHARGE' | 'ADMIN';

export type ScreenType =
  | 'overview'
  | 'new-scan'
  | 'screening-report'
  | 'audit-trail'
  | 'system-health-and-docs'
  | 'admin-portal'
  | 'officer-status'
  | 'system-logs'
  | 'security';

export interface AuthUser {
  userId: string;
  mustChangePassword?: boolean;
  email: string;
  name: string;
  role: UserRole;
  checkpointIds: string[];
  /** signed in from this machine's cache while the database was unreachable */
  offline?: boolean;
}

export interface Checkpoint {
  id: string;
  name: string;
  location?: string;
  type?: string;
  latitude?: number | null;
  longitude?: number | null;
  radius_km?: number | null;
  detection?: {
    method: 'gps' | 'gps-outside-radius' | 'only-assignment' | 'global' | 'fallback' | 'manual';
    distanceKm?: number;
    accuracyM?: number;
    note: string;
  };
}

export type DocumentType =
  | 'auto'
  | 'passport'
  | 'visa'
  | 'aadhaar'
  | 'pan'
  | 'national-id'
  | 'driving-licence'
  | 'permit';

export type RiskVerdict = 'CLEAR' | 'REVIEW' | 'HIGH RISK';

// ---- Screening engine output (mirrors backend/app/models/schemas.py) ----

export interface ValidationIssue {
  code: string;
  message: string;
  severity: 'info' | 'warning' | 'critical';
  field?: string | null;
}

export interface RiskComponent {
  key: 'validation' | 'tampering' | 'face' | 'records';
  label: string;
  applicable: boolean;
  risk: number | null;
  weight: number;
  effective_weight: number;
  contribution: number;
  explanation: string;
}

export interface EvaluationRow {
  check: string;
  method: string;
  measured: string;
  expected: string;
  status: 'pass' | 'warn' | 'fail' | 'skip';
  sentence: string;
}

export interface AuditEntry {
  id?: number;
  action: string;
  officer: string;
  officer_uid: string;
  target_id: string;
  details: string;
  hash_proof?: string;
  created_at?: string;
  signature_valid?: boolean | null;
  signature?: 'valid' | 'legacy' | 'invalid' | 'unsigned';
}

export interface DecisionRecord {
  id: number;
  scan_id: string;
  decision: 'clear' | 'secondary' | 'reject';
  status: 'final' | 'pending_cosign' | 'cosigned' | 'cosign_refused';
  officer: string;
  officer_uid: string;
  notes?: string;
  cosigner?: string | null;
  cosigner_uid?: string | null;
  cosign_notes?: string | null;
  cosigned_at?: string | null;
  system_verdict: string;
  system_score: number;
  checkpoint_id?: string | null;
  created_at: string;
  presenter_name?: string;
  doc_code?: string;
  lane?: string;
  registered?: boolean;
}

export interface ScanReceipt {
  sealed: boolean;
  scanId: string;
  leaf?: string;
  path?: { hash: string; side: 'left' | 'right' }[];
  batch?: {
    id: number; merkle_root: string; leaf_count: number; first_scan: string; last_scan: string;
    sealed_at: string; signature: string; public_key: string; external_proof?: string | null;
  };
}

export interface ScreeningAnalysis {
  id: string;
  timestamp: string;
  document_type: string;
  processing_ms: number;
  evaluation?: EvaluationRow[];
  classification?: {
    requested_type: string;
    detected_type: string;
    used_type: string;
    method: string;
    confidence: number;
    reason: string;
    classifier_available: boolean;
    classifier_probs: Record<string, number> | null;
    text_scores: Record<string, number>;
    text_evidence: Record<string, string[]>;
    mismatch: boolean;
  } | null;
  identity: {
    name?: string | null;
    document_number?: string | null;
    date_of_birth?: string | null;
    expiry_date?: string | null;
    nationality?: string | null;
    gender?: string | null;
  };
  ocr: {
    raw_text: string;
    mean_confidence: number;
    engine_available: boolean;
    warning?: string | null;
    extracted_fields: Record<string, unknown>;
    /** how many located field boxes were read on their own */
    text_regions_used?: number;
    /** field key -> "region" (read from a located box) | "page+region" (both readings agree) */
    field_sources?: Record<string, string>;
    layout_recognised?: boolean;
    layout_note?: string;
  };
  mrz?: {
    detected: boolean;
    raw_lines: string[];
    fields: { name: string; value: string; valid: boolean | null; check_digit_printed: number | null; check_digit_computed: number | null }[];
    composite_valid: boolean | null;
    warnings: string[];
  } | null;
  validation: { score: number; issues: ValidationIssue[]; checks_run: number };
  tampering: {
    tampering_score: number;
    verdict: 'clean' | 'suspicious' | 'tampered';
    evidence: string[];
    ela_heatmap?: string | null;
    copy_move_matches: number;
    components: { name: string; raw: number; weight: number; contribution: number; how: string }[];
  };
  face: {
    attempted: boolean;
    similarity?: number | null;
    is_match?: boolean | null;
    backend?: string | null;
    document_face_found: boolean;
    live_face_found: boolean;
    threshold?: number | null;
    mismatch_threshold?: number | null;
    decision?: 'match' | 'uncertain' | 'mismatch' | 'not_run';
    document_face_thumb?: string | null;
    live_face_thumb?: string | null;
    document_face_candidates?: number;
    document_face_box?: { x: number; y: number; w: number; h: number; image_w: number; image_h: number } | null;
  };
  records?: {
    status: string;
    source: string;
    document_number?: string | null;
    prior_count: number;
    prior_records: { id: string; name?: string | null; dob?: string | null; verdict?: string | null; checkpoint?: string | null; when?: string | null }[];
    issues: ValidationIssue[];
    summary: string;
    risk: number | null;
    /** comparison with the issued-documents database */
    reference?: {
      status: 'not_checked' | 'unavailable' | 'not_found' | 'match' | 'mismatch';
      summary: string;
      database_size: number;
      fields: { field: string; on_document: string | null; in_database: string | null; match: boolean }[];
      mismatched: string[];
    } | null;
  } | null;
  risk: {
    risk_score: number;
    verdict: 'CLEAR' | 'REVIEW' | 'REJECT';
    contributing_factors: string[];
    components: RiskComponent[];
    weighted_score: number;
    overrides: string[];
    thresholds: { clear_max: number; review_max: number; override_floor: number; face_mismatch_floor?: number; face_uncertain_floor?: number };
    formula: string;
  };
}

export interface ScreeningRecord {
  id: string;
  documentType: string;
  docCode: string;
  countryCode: string;
  countryName: string;
  presenterName: string;
  riskScore: number;
  riskVerdict: RiskVerdict;
  checksumStatus: 'PASS' | 'FAIL' | 'N/A';
  findings: string;
  timestamp: string;
  localTime: string;
  lane: string;
  officer: string;
  officerUid: string;
  hashProof: string;
  fullHash: string;
  blockHeight: string;
  flagReason?: string;
  mrzString?: string;
  mrzLine2?: string;
  docNumber?: string;
  dob?: string;
  expiryVisual?: string;
  expiryMrz?: string;
  elaAnomalyRate?: string;
  faceMatchRate?: string;
  remoteStationId?: string;
  checkpointId?: string;
  syncStatus?: 'SYNCED' | 'QUEUED_LOCAL' | 'PENDING_BURST';
  hasAnalysis?: boolean;
  analysis?: ScreeningAnalysis;
}

export interface NeonTelemetryStatus {
  connected: boolean;
  configured: boolean;
  provider: string;
  project?: string;
  projectUrl?: string;
  host: string;
  database: string;
  totalScans: number;
  totalAuditLogs: number;
  latencyMs: number;
  mode: string;
  message: string;
  /** records queued on the gateway while the database was unreachable */
  pendingOutbox?: number;
}

export interface IcaoRule {
  code: string;
  assertionName: string;
  mathRule: string;
  executionModule: string;
  status: 'Active' | 'Enforced';
}

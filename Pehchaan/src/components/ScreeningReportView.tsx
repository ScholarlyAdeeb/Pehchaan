import React, { useEffect, useState } from 'react';
import { AuditEntry, DecisionRecord, ScanReceipt, ScreeningAnalysis, ScreeningRecord, ScreenType, ValidationIssue } from '../types';
import { DecisionList, ReceiptPanel } from './screening/DecisionsAndReceipt';
import { useAuth } from '../contexts/AuthContext';
import { fetchAuditTrail, fetchScanDetail } from '../services/neonSyncService';
import { DOC_TYPE_LABELS, EvaluationMatrix, FacesCompared, RecordAuditLog, RiskBreakdown, VerdictBadge, verdictTone } from './screening/ScreeningParts';

interface ScreeningReportViewProps {
  currentRecord: ScreeningRecord;
  records: ScreeningRecord[];
  onSelectRecord: (record: ScreeningRecord) => void;
  onNavigate: (screen: ScreenType) => void;
}

type Decision = 'clear' | 'secondary' | 'reject';

const DECISIONS: Record<Decision, { label: string; action: string; style: string }> = {
  clear: { label: 'Clear traveller', action: 'OFFICER_DECISION_CLEAR', style: 'bg-[#006a26] hover:bg-[#00531d] text-white' },
  secondary: { label: 'Refer to secondary check', action: 'OFFICER_DECISION_SECONDARY', style: 'bg-[#8a5600] hover:bg-[#6d4400] text-white' },
  reject: { label: 'Reject document', action: 'OFFICER_DECISION_REJECT', style: 'bg-[#ba1a1a] hover:bg-[#93000a] text-white' },
};

const FIELD_LABELS: Record<string, string> = {
  name: 'Name', surname: 'Surname', given_name: 'Given name', father_name: "Father's name", guardian_name: 'Guardian',
  id_number: 'ID number', passport_number_visual: 'Passport no. (printed)', license_number: 'Licence number',
  visa_number: 'Visa number', permit_number: 'Permit number', date_of_birth: 'Date of birth', gender: 'Gender',
  nationality: 'Nationality', place_of_birth: 'Place of birth', place_of_issue: 'Place of issue', issue_date: 'Issue date',
  expiry_date: 'Expiry date', valid_till: 'Valid till', address: 'Address', pincode: 'PIN code', state: 'State',
  issuing_office: 'File / office no.', issuing_state: 'Issuing state', blood_group: 'Blood group',
  class_of_vehicle: 'Vehicle classes', aadhaar_valid: 'Aadhaar checksum', pan_valid: 'PAN format', pan_holder_type: 'PAN holder type',
  dl_format_valid: 'DL format', visa_type: 'Visa type',
};

const SEVERITY_STYLE: Record<string, string> = {
  critical: 'bg-[#ffdad6] text-[#93000a]',
  warning: 'bg-[#ffe4af] text-[#5c3a00]',
  info: 'bg-[#e9e7ed] text-[#414753]',
};

const MRZ_FIELD_LABELS: Record<string, string> = {
  passport_number: 'Document number',
  date_of_birth: 'Date of birth',
  date_of_expiry: 'Date of expiry',
  personal_number: 'Personal number',
};

export const ScreeningReportView: React.FC<ScreeningReportViewProps> = ({
  currentRecord, records, onSelectRecord, onNavigate,
}) => {
  const { token, user, hasRole } = useAuth();
  const [detail, setDetail] = useState<ScreeningRecord>(currentRecord);
  const [loading, setLoading] = useState(false);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [notes, setNotes] = useState('');
  const [logged, setLogged] = useState<string | null>(null);
  const [auditEntries, setAuditEntries] = useState<AuditEntry[] | null>(null);
  const [decisions, setDecisions] = useState<DecisionRecord[] | null>(null);
  const [receipt, setReceipt] = useState<ScanReceipt | null>(null);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  const api = async (url: string, init?: RequestInit) => {
    const res = await fetch(url, { ...init, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` } });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    return body;
  };

  const loadTrust = (id: string) => {
    if (!token) return;
    setDecisions(null);
    setReceipt(null);
    api(`/api/scans/${encodeURIComponent(id)}/decisions`).then(setDecisions).catch(() => setDecisions([]));
    api(`/api/scans/${encodeURIComponent(id)}/receipt`).then(setReceipt).catch(() => setReceipt({ sealed: false, scanId: id }));
  };

  useEffect(() => { loadTrust(currentRecord.id); }, [currentRecord.id, token]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadAudit = (id: string) => {
    if (!token) return;
    setAuditEntries(null);
    fetchAuditTrail(id, token).then(setAuditEntries).catch(() => setAuditEntries([]));
  };

  useEffect(() => { loadAudit(currentRecord.id); }, [currentRecord.id, token]);

  useEffect(() => {
    setDetail(currentRecord);
    setLogged(null);
    if (currentRecord.analysis || !currentRecord.hasAnalysis || !token) return;
    setLoading(true);
    fetchScanDetail(currentRecord.id, token)
      .then((full) => full && setDetail(full))
      .finally(() => setLoading(false));
  }, [currentRecord, token]);

  const a = detail.analysis;
  const tone = verdictTone(detail.riskVerdict);

  const confirmDecision = async () => {
    if (!decision || !token) return;
    setDecisionError(null);
    try {
      const out = await api(`/api/scans/${encodeURIComponent(detail.id)}/decision`, {
        method: 'POST', body: JSON.stringify({ decision, notes }),
      });
      const d = DECISIONS[decision];
      setLogged(out.status === 'pending_cosign'
        ? 'Override requested — it takes effect only after a Post In-Charge co-signs it.'
        : `${d.label} — recorded in the audit log.${out.registered ? ' Its image fingerprint was added to the forged-document registry.' : ''}`);
      loadAudit(detail.id);
      loadTrust(detail.id);
      setDecision(null);
      setNotes('');
    } catch (e: any) {
      setDecisionError(e.message);
    }
  };

  const onCosign = async (id: number, approve: boolean, cosignNotes: string) => {
    await api(`/api/decisions/${id}/cosign`, { method: 'POST', body: JSON.stringify({ approve, notes: cosignNotes }) });
    setLogged(approve ? 'Override co-signed.' : 'Override refused.');
    loadAudit(detail.id);
    loadTrust(detail.id);
  };

  return (
    <div className="p-4 sm:p-6 space-y-5 max-w-[1400px] mx-auto pb-28 lg:pb-32 print:pb-6">
      {/* Header */}
      <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-4 pb-4 border-b border-[#efedf3]">
        <div className="space-y-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap text-xs">
            <span className="font-mono font-bold text-[#0059b5]">{detail.id}</span>
            <span className="text-[#717785]">{detail.timestamp}</span>
            {detail.lane && <span className="text-[#717785]">· {detail.lane}</span>}
            {detail.officer && <span className="text-[#717785]">· {detail.officer}</span>}
          </div>
          <h1 className="text-xl sm:text-2xl font-bold text-[#1a1b1f] break-words">
            {detail.presenterName} <span className="text-[#717785] font-medium">· {detail.docCode}</span>
          </h1>
        </div>
        <div className="flex items-center gap-2 flex-wrap print:hidden">
          <label className="flex items-center gap-1.5 bg-[#f4f3f8] px-2.5 py-1.5 rounded-lg text-xs">
            <span className="text-[#717785]">Record</span>
            <select
              value={detail.id}
              onChange={(e) => {
                const found = records.find((r) => r.id === e.target.value);
                if (found) onSelectRecord(found);
              }}
              className="bg-transparent font-mono font-semibold text-[#0059b5] max-w-[220px]"
            >
              {records.map((r) => (
                <option key={r.id} value={r.id}>{r.id} — {r.presenterName}</option>
              ))}
            </select>
          </label>
          <button onClick={() => window.print()} className="btn-ghost">
            <span className="material-symbols-outlined text-[16px]">print</span> Print
          </button>
          <button onClick={() => onNavigate('overview')} className="btn-secondary">
            <span className="material-symbols-outlined text-[16px]">arrow_back</span> Dashboard
          </button>
        </div>
      </div>

      {logged && (
        <div className="p-3 bg-[#dcf5e1] rounded-lg text-xs font-semibold text-[#00531d] flex items-center gap-2">
          <span className="material-symbols-outlined text-[18px]">verified</span>{logged}
        </div>
      )}

      {/* Verdict */}
      <section className={`rounded-xl p-5 ${tone.panel}`}>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-2">
            <VerdictBadge verdict={detail.riskVerdict} />
            {a ? (
              <ul className="text-xs space-y-1 list-disc pl-4 max-w-3xl">
                {a.risk.contributing_factors.slice(0, 5).map((f) => <li key={f}>{f}</li>)}
              </ul>
            ) : (
              <p className="text-xs">{detail.findings}</p>
            )}
          </div>
          <div className="text-left sm:text-right shrink-0">
            <div className="text-5xl font-extrabold font-mono leading-none">{detail.riskScore}</div>
            <div className="text-[10px] uppercase tracking-wider mt-1 opacity-80">risk score / 100</div>
          </div>
        </div>
      </section>

      {loading && <div className="text-xs text-[#717785]">Loading full analysis…</div>}
      {!loading && !a && (
        <div className="p-4 bg-[#f4f3f8] rounded-lg text-xs text-[#414753]">
          Detailed analysis is not stored for this record (it was created before analysis storage was added). The summary
          above is what was recorded.
        </div>
      )}

      {a && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          <Card title="Evaluation matrix" icon="fact_check" className="lg:col-span-2">
            <EvaluationMatrix rows={a.evaluation} />
          </Card>

          <Card title="Risk score calculation" icon="calculate" className="lg:col-span-2">
            <RiskBreakdown analysis={a} />
          </Card>

          <Card title="Document type" icon="auto_awesome">
            <ClassificationPanel a={a} />
          </Card>

          <Card title="Extracted details" icon="text_snippet">
            <FieldsPanel a={a} />
          </Card>

          {a.mrz && (
            <Card title="Machine-readable zone (MRZ)" icon="qr_code_2" className="lg:col-span-2">
              <MrzPanel a={a} />
            </Card>
          )}

          <Card title={`Document checks (${a.validation.checks_run} run)`} icon="rule">
            <IssueList issues={a.validation.issues} empty="All document checks passed." />
          </Card>

          <Card title="Earlier screenings of this document" icon="manage_search">
            <RecordsPanel a={a} />
          </Card>

          <Card title="Tampering forensics" icon="image_search">
            <TamperingPanel a={a} />
          </Card>

          <Card title="Face match" icon="face">
            <FacesCompared face={a.face} />
            <FacePanel a={a} />
          </Card>

          <Card title="Tamper-evident record" icon="link" className="lg:col-span-2">
            <dl className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
              <KV k="Block" v={detail.blockHeight} mono />
              <KV k="Processing time" v={`${(a.processing_ms / 1000).toFixed(1)} s`} mono />
              <KV k="Engine scan ID" v={a.id} mono />
              <div className="sm:col-span-3">
                <KV k="SHA-256 (chained to previous record)" v={detail.fullHash} mono />
              </div>
            </dl>
          </Card>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <section className="bg-white border border-[#efedf3] rounded-xl p-5 space-y-3">
          <h2 className="text-xs font-bold text-[#1a1b1f] uppercase tracking-wider flex items-center gap-2">
            <span className="material-symbols-outlined text-[#0059b5] text-[18px]">how_to_reg</span>
            Officer decisions
          </h2>
          <p className="text-[11px] text-[#717785]">Clearing a traveller the system flagged needs a second person: a Post In-Charge must co-sign.</p>
          <DecisionList decisions={decisions} canCosign={hasRole('POST_INCHARGE', 'ADMIN')} currentUserId={user?.userId} onCosign={onCosign} />
        </section>
        <section className="bg-white border border-[#efedf3] rounded-xl p-5 space-y-3">
          <h2 className="text-xs font-bold text-[#1a1b1f] uppercase tracking-wider flex items-center gap-2">
            <span className="material-symbols-outlined text-[#0059b5] text-[18px]">receipt_long</span>
            Tamper-proof receipt
          </h2>
          <ReceiptPanel receipt={receipt} />
        </section>
      </div>

      <section className="bg-white border border-[#efedf3] rounded-xl p-5 space-y-3">
        <h2 className="text-xs font-bold text-[#1a1b1f] uppercase tracking-wider flex items-center gap-2">
          <span className="material-symbols-outlined text-[#0059b5] text-[18px]">history</span>
          Audit trail for this record
        </h2>
        <p className="text-[11px] text-[#717785]">Every entry is signed with HMAC-SHA-256 when written; the signature is re-checked each time this page loads.</p>
        <RecordAuditLog entries={auditEntries} />
      </section>

      {/* Officer decision */}
      <div className="fixed left-0 right-0 bottom-[calc(3.75rem+env(safe-area-inset-bottom))] lg:bottom-0 z-40 bg-white/95 backdrop-blur border-t border-[#efedf3] p-2.5 sm:p-3 print:hidden">
        <div className="max-w-[1400px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-3">
          <span className="hidden sm:inline text-xs text-[#414753]">
            <span className="font-semibold text-[#1a1b1f]">Your decision</span> — the system advises; the officer decides.
          </span>
          <div className="grid grid-cols-3 gap-2 w-full sm:w-auto sm:flex sm:flex-wrap sm:justify-center">
            {(Object.keys(DECISIONS) as Decision[]).map((k) => (
              <button key={k} onClick={() => setDecision(k)} className={`min-h-[44px] px-2 sm:px-3.5 py-2 text-[11px] sm:text-xs leading-tight font-semibold rounded-lg ${DECISIONS[k].style}`}>
                {DECISIONS[k].label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {decision && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
          <div className="bg-white rounded-xl max-w-md w-full p-5 space-y-3">
            <h3 className="text-sm font-bold text-[#1a1b1f]">{DECISIONS[decision].label}</h3>
            {decision === 'clear' && detail.riskVerdict !== 'CLEAR' && (
              <p className="text-xs text-[#93000a] bg-[#fff1f0] p-2 rounded">
                The system rated this {detail.riskVerdict}. Clearing it overrides the system; give a reason.
              </p>
            )}
            {decision === 'clear' && detail.riskVerdict !== 'CLEAR' && (
              <p className="text-xs text-[#5c3a00] bg-[#fff4dc] p-2 rounded">A Post In-Charge must co-sign before this clearance takes effect.</p>
            )}
            {decisionError && <p className="text-xs text-[#93000a]">{decisionError}</p>}
            <label className="block text-[11px] font-semibold text-[#1a1b1f]" htmlFor="decision-notes">Notes</label>
            <textarea
              id="decision-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              className="w-full text-xs p-2.5 border border-[#e3e2e7] rounded-lg focus:outline-none focus:border-[#0059b5]"
              placeholder="What you checked and why"
            />
            <div className="flex justify-end gap-2">
              <button onClick={() => setDecision(null)} className="btn-ghost">Cancel</button>
              <button
                onClick={confirmDecision}
                disabled={decision === 'clear' && detail.riskVerdict !== 'CLEAR' && !notes.trim()}
                className={`px-4 py-2 text-xs font-bold rounded-md disabled:opacity-40 ${DECISIONS[decision].style}`}
              >
                Record decision
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

const Card: React.FC<{ title: string; icon: string; className?: string; children: React.ReactNode }> = ({ title, icon, className = '', children }) => (
  <section className={`bg-white border border-[#efedf3] rounded-xl p-5 space-y-3 min-w-0 ${className}`}>
    <h2 className="text-xs font-bold text-[#1a1b1f] uppercase tracking-wider flex items-center gap-2">
      <span className="material-symbols-outlined text-[#0059b5] text-[18px]">{icon}</span>
      {title}
    </h2>
    {children}
  </section>
);

const KV: React.FC<{ k: string; v?: React.ReactNode; mono?: boolean }> = ({ k, v, mono }) => (
  <div className="min-w-0">
    <dt className="text-[10px] uppercase tracking-wide text-[#717785]">{k}</dt>
    <dd className={`text-[#1a1b1f] font-semibold break-all ${mono ? 'font-mono text-[11px]' : ''}`}>
      {v === undefined || v === null || v === '' ? <span className="text-[#a0a4ad] font-normal">—</span> : v}
    </dd>
  </div>
);

const Bar: React.FC<{ value: number; tone?: string }> = ({ value, tone = 'bg-[#0059b5]' }) => (
  <div className="h-1.5 bg-[#efedf3] rounded-full overflow-hidden">
    <div className={`h-full ${tone}`} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
  </div>
);

const IssueList: React.FC<{ issues: ValidationIssue[]; empty: string }> = ({ issues, empty }) =>
  issues.length === 0 ? (
    <p className="text-xs text-[#006a26] flex items-center gap-1.5">
      <span className="material-symbols-outlined text-[16px]">check_circle</span>{empty}
    </p>
  ) : (
    <ul className="space-y-2">
      {[...issues].sort((x, y) => ['critical', 'warning', 'info'].indexOf(x.severity) - ['critical', 'warning', 'info'].indexOf(y.severity)).map((i, idx) => (
        <li key={`${i.code}-${idx}`} className="text-xs flex gap-2 items-start">
          <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase shrink-0 ${SEVERITY_STYLE[i.severity]}`}>{i.severity}</span>
          <span className="text-[#1a1b1f] leading-snug">{i.message}</span>
        </li>
      ))}
    </ul>
  );

const ClassificationPanel: React.FC<{ a: ScreeningAnalysis }> = ({ a }) => {
  const c = a.classification;
  if (!c) return <p className="text-xs text-[#717785]">Not available for this record.</p>;
  const methodText: Record<string, string> = {
    'classifier+text': 'Image classifier and printed text agree',
    classifier: 'Image classifier',
    text: 'Printed-text markers',
    fallback: 'No clear signal',
  };
  return (
    <div className="space-y-3 text-xs">
      <dl className="grid grid-cols-2 gap-3">
        <KV k="Requested" v={DOC_TYPE_LABELS[c.requested_type] || c.requested_type} />
        <KV k="Screened as" v={DOC_TYPE_LABELS[c.used_type] || c.used_type} />
        <KV k="Decided by" v={methodText[c.method] || c.method} />
        <KV k="Confidence" v={`${Math.round(c.confidence * 100)}%`} mono />
      </dl>
      <p className="text-[#414753]">{c.reason}</p>
      {c.mismatch && (
        <p className="text-[#5c3a00] bg-[#ffe4af] rounded p-2">The document does not look like the type the officer selected.</p>
      )}
      {c.classifier_probs && (
        <div className="space-y-1.5">
          <div className="text-[10px] uppercase tracking-wide text-[#717785]">Classifier probabilities (MobileNetV2)</div>
          {(Object.entries(c.classifier_probs) as [string, number][]).sort((x, y) => y[1] - x[1]).map(([k, p]) => (
            <div key={k} className="grid grid-cols-[80px_1fr_44px] items-center gap-2">
              <span>{DOC_TYPE_LABELS[k] || k}</span>
              <Bar value={p * 100} />
              <span className="font-mono text-right">{(p * 100).toFixed(1)}%</span>
            </div>
          ))}
        </div>
      )}
      {Object.keys(c.text_evidence).length > 0 && (
        <div>
          <div className="text-[10px] uppercase tracking-wide text-[#717785] mb-1">Text markers found</div>
          <ul className="space-y-0.5">
            {(Object.entries(c.text_evidence) as [string, string[]][]).map(([k, ev]) => (
              <li key={k}><span className="font-semibold">{DOC_TYPE_LABELS[k] || k}:</span> {ev.join(', ')}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

const FieldsPanel: React.FC<{ a: ScreeningAnalysis }> = ({ a }) => {
  const entries = Object.entries(a.ocr.extracted_fields).filter(([, v]) => v !== null && v !== undefined && v !== '');
  const show = (v: unknown) => (typeof v === 'boolean' ? (v ? 'Valid' : 'Invalid') : Array.isArray(v) ? v.join(', ') : String(v));
  const sources = a.ocr.field_sources || {};
  const boxesRead = a.ocr.text_regions_used || 0;
  return (
    <div className="space-y-3 text-xs">
      {!a.ocr.engine_available && <p className="text-[#93000a]">{a.ocr.warning}</p>}
      {boxesRead > 0 && (
        <p className={a.ocr.layout_recognised ? 'text-[#006a26]' : 'text-[#8a5600]'}>
          {a.ocr.layout_recognised
            ? `Field detector located and read ${boxesRead} field boxes (${a.ocr.layout_note}).`
            : `Field detector not used: ${a.ocr.layout_note}. Values below come from the full-page reading.`}
        </p>
      )}
      <dl className="grid grid-cols-2 gap-3">
        <KV k="Name" v={a.identity.name} />
        <KV k="Document number" v={a.identity.document_number} mono />
        <KV k="Date of birth" v={a.identity.date_of_birth} mono />
        <KV k="Expiry" v={a.identity.expiry_date} mono />
        <KV k="Nationality" v={a.identity.nationality} />
        <KV k="Gender" v={a.identity.gender} />
      </dl>
      {entries.length > 0 && (
        <table className="w-full text-[11px]">
          <tbody>
            {entries.map(([k, v]) => (
              <tr key={k} className="border-t border-[#f4f3f8]">
                <td className="py-1 pr-3 text-[#717785] whitespace-nowrap align-top">{FIELD_LABELS[k] || k}</td>
                <td className="py-1 text-[#1a1b1f] break-words">
                  {show(v)}
                  {sources[k] && (
                    <span
                      className="ml-2 px-1.5 py-0.5 rounded bg-[#eef3fb] text-[#0059b5] text-[10px] font-semibold whitespace-nowrap"
                      title={sources[k] === 'region' ? 'Read from the box the field detector located' : 'Full-page reading and located box agree'}
                    >
                      {sources[k] === 'region' ? 'located field' : 'confirmed'}
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <details className="text-[11px]">
        <summary className="cursor-pointer text-[#0059b5] font-semibold">
          Raw OCR text (Tesseract, mean word confidence {Math.round(a.ocr.mean_confidence)}%)
        </summary>
        <pre className="mt-2 p-2 bg-[#f4f3f8] rounded whitespace-pre-wrap break-words max-h-60 overflow-auto font-mono text-[10.5px]">
          {a.ocr.raw_text || '(no text read)'}
        </pre>
      </details>
    </div>
  );
};

const MrzPanel: React.FC<{ a: ScreeningAnalysis }> = ({ a }) => {
  const m = a.mrz!;
  if (!m.detected) return <p className="text-xs text-[#93000a]">No MRZ could be read from the image.</p>;
  return (
    <div className="space-y-3 text-xs">
      <pre className="bg-[#1a1b1f] text-[#f1f0f6] p-3 rounded-lg font-mono text-[12px] sm:text-sm tracking-wider overflow-x-auto">
        {m.raw_lines.join('\n')}
      </pre>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] tabular-nums">
          <thead>
            <tr className="text-left text-[#717785] border-b border-[#efedf3]">
              <th className="py-1.5 pr-2">Field</th>
              <th className="py-1.5 px-2">Value</th>
              <th className="hidden sm:table-cell py-1.5 px-2 text-right">Printed check digit</th>
              <th className="hidden sm:table-cell py-1.5 px-2 text-right">Computed (ICAO 7-3-1)</th>
              <th className="sm:hidden py-1.5 px-1.5 text-right" title="Printed check digit / computed (ICAO 7-3-1)">Digit</th>
              <th className="py-1.5 pl-2">Result</th>
            </tr>
          </thead>
          <tbody>
            {m.fields.map((f) => (
              <tr key={f.name} className="border-b border-[#f4f3f8]">
                <td className="py-1.5 pr-2 font-semibold">{MRZ_FIELD_LABELS[f.name] || f.name}</td>
                <td className="py-1.5 px-1.5 sm:px-2 font-mono break-all">{f.value}</td>
                <td className="hidden sm:table-cell py-1.5 px-2 font-mono text-right">{f.check_digit_printed ?? '?'}</td>
                <td className="hidden sm:table-cell py-1.5 px-2 font-mono text-right">{f.check_digit_computed ?? '?'}</td>
                <td className="sm:hidden py-1.5 px-1.5 font-mono text-right whitespace-nowrap">{f.check_digit_printed ?? '?'} / {f.check_digit_computed ?? '?'}</td>
                <td className="py-1.5 pl-2"><CheckResult ok={f.valid} /></td>
              </tr>
            ))}
            <tr>
              <td className="hidden sm:table-cell py-1.5 pr-2 font-semibold" colSpan={4}>Composite (whole line 2)</td>
              <td className="sm:hidden py-1.5 pr-2 font-semibold" colSpan={3}>Composite (line 2)</td>
              <td className="py-1.5 pl-2"><CheckResult ok={m.composite_valid} /></td>
            </tr>
          </tbody>
        </table>
      </div>
      {m.warnings.map((w) => <p key={w} className="text-[11px] text-[#717785]">{w}</p>)}
    </div>
  );
};

const CheckResult: React.FC<{ ok: boolean | null }> = ({ ok }) =>
  ok === null ? (
    <span className="text-[#717785]">Unreadable</span>
  ) : ok ? (
    <span className="text-[#006a26] font-semibold">Pass</span>
  ) : (
    <span className="text-[#ba1a1a] font-semibold">Fail</span>
  );

const TamperingPanel: React.FC<{ a: ScreeningAnalysis }> = ({ a }) => {
  const t = a.tampering;
  const tone = t.verdict === 'tampered' ? 'bg-[#ba1a1a]' : t.verdict === 'suspicious' ? 'bg-[#c98a00]' : 'bg-[#008633]';
  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center justify-between">
        <span className="capitalize font-semibold">{t.verdict}</span>
        <span className="font-mono">{t.tampering_score}/100</span>
      </div>
      <Bar value={t.tampering_score} tone={tone} />
      {t.components.length > 0 && (
        <table className="w-full text-[11px] tabular-nums">
          <tbody>
            {t.components.map((c) => (
              <tr key={c.name} className="border-t border-[#f4f3f8] align-top">
                <td className="py-1 pr-2">
                  <div className="font-semibold">{c.name}</div>
                  <div className="text-[#717785]">{c.how}</div>
                </td>
                <td className="py-1 text-right font-mono whitespace-nowrap">{c.raw} × {c.weight} = {c.contribution}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <ul className="list-disc pl-4 space-y-1 text-[#414753]">
        {t.evidence.map((e) => <li key={e}>{e}</li>)}
      </ul>
      {t.ela_heatmap && (
        <figure className="space-y-1">
          <img src={t.ela_heatmap} alt="Error level analysis heatmap" className="rounded border border-[#efedf3] max-h-64 w-auto" />
          <figcaption className="text-[10.5px] text-[#717785]">
            Error Level Analysis: brighter areas re-compress differently from the rest of the image. Printed text and
            photo edges are naturally bright; a bright patch with a sharp boundary on a flat area suggests an edit.
          </figcaption>
        </figure>
      )}
    </div>
  );
};

const FacePanel: React.FC<{ a: ScreeningAnalysis }> = ({ a }) => {
  const f = a.face;
  if (!f.attempted) {
    return (
      <div className="text-xs text-[#414753] space-y-1">
        <p>No live photo was provided, so faces were not compared.</p>
        <p>Face on the document: <span className="font-semibold">{f.document_face_found ? 'found' : 'not found'}</span></p>
      </div>
    );
  }
  const sim = (f.similarity ?? 0) * 100;
  const matchAt = (f.threshold ?? 0.3) * 100;
  const mismatchBelow = (f.mismatch_threshold ?? f.threshold ?? 0.18) * 100;
  const decision = f.decision && f.decision !== 'not_run' ? f.decision : f.is_match ? 'match' : 'mismatch';
  const look = {
    match: { text: 'Same person', cls: 'text-[#006a26]', bar: 'bg-[#008633]' },
    uncertain: { text: 'Inconclusive — compare manually', cls: 'text-[#8a5600]', bar: 'bg-[#c98a00]' },
    mismatch: { text: 'Different person', cls: 'text-[#ba1a1a]', bar: 'bg-[#ba1a1a]' },
  }[decision];
  return (
    <div className="space-y-3 text-xs">
      <div className="flex items-center justify-between">
        <span className={`font-semibold ${look.cls}`}>{look.text}</span>
        <span className="font-mono">{sim.toFixed(1)}% similarity</span>
      </div>
      <div className="relative">
        <Bar value={sim} tone={look.bar} />
        <span className="absolute -top-1 h-3.5 w-px bg-[#ba1a1a]" style={{ left: `${mismatchBelow}%` }} title="Different-person line" />
        <span className="absolute -top-1 h-3.5 w-px bg-[#006a26]" style={{ left: `${matchAt}%` }} title="Same-person line" />
      </div>
      <p className="text-[11px] text-[#717785]">
        Below {mismatchBelow.toFixed(0)}%: different person · {mismatchBelow.toFixed(0)}–{matchAt.toFixed(0)}%: inconclusive ·
        {' '}≥ {matchAt.toFixed(0)}%: same person
      </p>
      <dl className="grid grid-cols-2 gap-3">
        <KV k="Face on document" v={f.document_face_found ? 'Found' : 'Not found'} />
        <KV k="Face in live photo" v={f.live_face_found ? 'Found' : 'Not found'} />
      </dl>
      <p className="text-[11px] text-[#717785]">Method: {f.backend}</p>
    </div>
  );
};

const RecordsPanel: React.FC<{ a: ScreeningAnalysis }> = ({ a }) => {
  const r = a.records;
  if (!r) return <p className="text-xs text-[#717785]">Not available for this record.</p>;
  const statusTone: Record<string, string> = {
    conflict: 'text-[#ba1a1a]', flagged_history: 'text-[#8a5600]', consistent: 'text-[#006a26]',
  };
  return (
    <div className="space-y-3 text-xs">
      <p className={`font-semibold ${statusTone[r.status] || 'text-[#414753]'}`}>{r.summary}</p>
      {r.document_number && <p className="text-[#717785]">Looked up document number <span className="font-mono">{r.document_number}</span></p>}
      {r.reference && r.reference.status !== 'not_checked' && (
        <div className="border border-[#efedf3] rounded p-2.5 space-y-2">
          <p className="font-semibold text-[#1a1b1f]">Issuing records</p>
          <p className={r.reference.status === 'mismatch' ? 'text-[#ba1a1a]' : r.reference.status === 'match' ? 'text-[#006a26]' : 'text-[#717785]'}>
            {r.reference.summary}
          </p>
          {r.reference.fields.length > 0 && (
            <table className="w-full text-[11px]">
              <thead>
                <tr className="text-left text-[#717785] border-b border-[#efedf3]">
                  <th className="py-1 pr-2">Field</th><th className="py-1 px-2">On this document</th><th className="py-1 px-2">As issued</th><th className="py-1 pl-2">Result</th>
                </tr>
              </thead>
              <tbody>
                {r.reference.fields.map((f) => (
                  <tr key={f.field} className="border-b border-[#f4f3f8]">
                    <td className="py-1 pr-2">{f.field.replace(/_/g, ' ')}</td>
                    <td className="py-1 px-2 font-mono break-words">{f.on_document || 'not read'}</td>
                    <td className="py-1 px-2 font-mono break-words">{f.in_database || '—'}</td>
                    <td className={`py-1 pl-2 font-semibold ${f.match ? 'text-[#006a26]' : 'text-[#ba1a1a]'}`}>
                      {!f.on_document ? 'not compared' : f.match ? 'Same' : 'Different'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      <IssueList issues={r.issues.filter((i) => i.severity !== 'info')} empty="No conflicts with earlier records." />
      {r.prior_records.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[11px]">
            <thead>
              <tr className="text-left text-[#717785] border-b border-[#efedf3]">
                <th className="py-1 pr-2">Record</th><th className="py-1 px-2">Name</th><th className="py-1 px-2">DOB</th><th className="py-1 pl-2">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {r.prior_records.slice(0, 8).map((p) => (
                <tr key={p.id} className="border-b border-[#f4f3f8]">
                  <td className="py-1 pr-2 font-mono">{p.id}</td>
                  <td className="py-1 px-2">{p.name || '—'}</td>
                  <td className="py-1 px-2 font-mono">{p.dob || '—'}</td>
                  <td className="py-1 pl-2">{p.verdict || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

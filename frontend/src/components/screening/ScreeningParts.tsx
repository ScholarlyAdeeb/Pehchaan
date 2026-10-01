import React from 'react';
import { AuditEntry, EvaluationRow, RiskVerdict, ScreeningAnalysis } from '../../types';

export const DOC_TYPE_LABELS: Record<string, string> = {
  passport: 'Passport',
  visa: 'Visa',
  national_id: 'National ID',
  aadhar: 'Aadhaar',
  pan: 'PAN card',
  driving_license: 'Driving licence',
  permit: 'Border permit',
  auto: 'Auto-detect',
};

export function verdictTone(verdict: RiskVerdict | string) {
  if (verdict === 'HIGH RISK' || verdict === 'REJECT') {
    return { panel: 'bg-[#ffdad6] text-[#410002]', chip: 'bg-[#ba1a1a] text-white', text: 'text-[#ba1a1a]', bar: 'bg-[#ba1a1a]', label: 'HIGH RISK' };
  }
  if (verdict === 'REVIEW') {
    return { panel: 'bg-[#ffe4af] text-[#3d2600]', chip: 'bg-[#8a5600] text-white', text: 'text-[#8a5600]', bar: 'bg-[#c98a00]', label: 'REVIEW' };
  }
  return { panel: 'bg-[#dcf5e1] text-[#00210a]', chip: 'bg-[#006a26] text-white', text: 'text-[#006a26]', bar: 'bg-[#008633]', label: 'CLEAR' };
}

const VERDICT_TEXT: Record<string, string> = {
  CLEAR: 'Clear — no disqualifying findings',
  REVIEW: 'Review — send for secondary check',
  'HIGH RISK': 'High risk — do not clear',
};

export const VerdictBadge: React.FC<{ verdict: RiskVerdict | string }> = ({ verdict }) => {
  const tone = verdictTone(verdict);
  return (
    <div className="flex items-center gap-2">
      <span className={`px-2 py-0.5 rounded text-[11px] font-bold tracking-wider ${tone.chip}`}>{tone.label}</span>
      <span className="text-xs font-semibold">{VERDICT_TEXT[tone.label]}</span>
    </div>
  );
};

const fmt = (n: number, d = 1) => (Number.isInteger(n) ? String(n) : n.toFixed(d));

/**
 * Shows exactly how the risk score was produced: each signal's own 0-100
 * risk, its weight (rescaled over the signals that ran), its contribution,
 * then any hard floor applied and the verdict band.
 */
export const RiskBreakdown: React.FC<{ analysis: ScreeningAnalysis; compact?: boolean }> = ({ analysis, compact }) => {
  const { risk } = analysis;
  const ran = risk.components.filter((c) => c.applicable);
  const skipped = risk.components.filter((c) => !c.applicable);
  const t = risk.thresholds;

  return (
    <div className="space-y-2">
      <div className="text-xs font-bold text-[#1a1b1f]">How the score was calculated</div>
      <div className="overflow-x-auto">
        <table className="w-full text-[11px] tabular-nums">
          <thead>
            <tr className="text-left text-[#717785] border-b border-[#efedf3]">
              <th className="py-1.5 pr-2 font-semibold">Signal</th>
              <th className="py-1.5 px-2 font-semibold text-right">Risk</th>
              <th className="py-1.5 px-2 font-semibold text-right">× Weight</th>
              <th className="py-1.5 pl-2 font-semibold text-right">= Points</th>
            </tr>
          </thead>
          <tbody>
            {ran.map((c) => (
              <tr key={c.key} className="border-b border-[#f4f3f8] align-top">
                <td className="py-1.5 pr-2">
                  <div className="font-semibold text-[#1a1b1f]">{c.label}</div>
                  {!compact && <div className="text-[#717785] leading-snug mt-0.5">{c.explanation}</div>}
                </td>
                <td className="py-1.5 px-2 text-right font-mono">{fmt(c.risk ?? 0)}</td>
                <td className="py-1.5 px-2 text-right font-mono" title={`Configured weight ${c.weight}`}>
                  {(c.effective_weight * 100).toFixed(1)}%
                </td>
                <td className="py-1.5 pl-2 text-right font-mono font-semibold">{c.contribution.toFixed(1)}</td>
              </tr>
            ))}
            <tr>
              <td className="py-1.5 pr-2 font-semibold text-[#1a1b1f]" colSpan={3}>Weighted score</td>
              <td className="py-1.5 pl-2 text-right font-mono font-bold">{risk.weighted_score.toFixed(1)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      {!compact && risk.overrides.map((o) => (
        <div key={o} className="text-[11px] bg-[#fff1f0] border border-[#ffdad6] text-[#93000a] rounded p-2">
          <span className="font-semibold">Floor applied: </span>{o}
        </div>
      ))}

      <div className="text-[11px] text-[#414753]">
        Final score <span className="font-mono font-bold">{risk.risk_score}</span> → bands: 0–{t.clear_max} Clear,{' '}
        {t.clear_max + 1}–{t.review_max} Review, {t.review_max + 1}–100 High risk.
      </div>

      {skipped.length > 0 && (
        <div className="text-[11px] text-[#717785]">
          Not counted: {skipped.map((c) => `${c.label} (${c.explanation.replace(/\.$/, '')})`).join('; ')}. Their weight is
          shared among the signals that ran.
        </div>
      )}
    </div>
  );
};

const STATUS_CHIP: Record<EvaluationRow['status'], { label: string; cls: string; dot: string }> = {
  fail: { label: 'FAIL', cls: 'bg-[#ffdad6] text-[#93000a]', dot: 'bg-[#ba1a1a]' },
  warn: { label: 'CHECK', cls: 'bg-[#ffe4af] text-[#5c3a00]', dot: 'bg-[#c98a00]' },
  pass: { label: 'PASS', cls: 'bg-[#dcf5e1] text-[#00531d]', dot: 'bg-[#008633]' },
  skip: { label: 'NOT RUN', cls: 'bg-[#e9e7ed] text-[#414753]', dot: 'bg-[#a0a4ad]' },
};
const ORDER: EvaluationRow['status'][] = ['fail', 'warn', 'pass', 'skip'];

/** One row per check: what was checked, how it was measured, what was found, one-line result. */
export const EvaluationMatrix: React.FC<{ rows?: EvaluationRow[]; compact?: boolean }> = ({ rows, compact }) => {
  if (!rows || rows.length === 0) {
    return <p className="text-xs text-[#717785]">No evaluation stored for this record.</p>;
  }
  const sorted = [...rows].sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status));
  const counts = ORDER.map((s) => [s, rows.filter((r) => r.status === s).length] as const).filter(([, n]) => n);

  if (compact) {
    return (
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="text-xs font-bold text-[#1a1b1f]">Evaluation</div>
          <div className="flex gap-1">
            {counts.map(([s, n]) => (
              <span key={s} className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${STATUS_CHIP[s].cls}`}>{n} {STATUS_CHIP[s].label}</span>
            ))}
          </div>
        </div>
        <ul className="divide-y divide-[#f4f3f8] border border-[#efedf3] rounded-lg">
          {sorted.map((r) => (
            <li key={r.check} className="p-2 text-xs flex gap-2">
              <span className={`mt-1 w-2 h-2 rounded-full shrink-0 ${STATUS_CHIP[r.status].dot}`} />
              <div className="min-w-0">
                <div className="text-[#1a1b1f]"><span className="font-semibold">{r.check}:</span> {r.sentence}</div>
                <div className="text-[10.5px] text-[#717785]">{r.method} · found {r.measured}</div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-[#717785] border-b border-[#efedf3]">
            <th className="py-2 pr-3 font-semibold">Result</th>
            <th className="py-2 px-3 font-semibold">Check</th>
            <th className="py-2 px-3 font-semibold">How it was measured</th>
            <th className="py-2 px-3 font-semibold">Found</th>
            <th className="py-2 px-3 font-semibold">Needed</th>
            <th className="py-2 pl-3 font-semibold">In short</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => (
            <tr key={r.check} className="border-b border-[#f4f3f8] align-top">
              <td className="py-2 pr-3">
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap ${STATUS_CHIP[r.status].cls}`}>{STATUS_CHIP[r.status].label}</span>
              </td>
              <td className="py-2 px-3 font-semibold text-[#1a1b1f] whitespace-nowrap">{r.check}</td>
              <td className="py-2 px-3 text-[#414753] min-w-[180px]">{r.method}</td>
              <td className="py-2 px-3 font-mono text-[11px] whitespace-nowrap">{r.measured}</td>
              <td className="py-2 px-3 text-[#717785] min-w-[120px]">{r.expected}</td>
              <td className="py-2 pl-3 text-[#1a1b1f] min-w-[220px]">{r.sentence}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const ACTION_LABELS: Record<string, string> = {
  SCREENING_CLEAR: 'Screened — CLEAR',
  SCREENING_REVIEW: 'Screened — REVIEW',
  SCREENING_HIGH_RISK: 'Screened — HIGH RISK',
  OFFICER_DECISION_CLEAR: 'Officer cleared traveller',
  OFFICER_DECISION_SECONDARY: 'Officer referred to secondary check',
  OFFICER_DECISION_REJECT: 'Officer rejected document',
};

/** Chronological, signature-checked log entries for one screening record. */
export const RecordAuditLog: React.FC<{ entries: AuditEntry[] | null }> = ({ entries }) => {
  if (entries === null) return <p className="text-xs text-[#717785]">Loading audit entries…</p>;
  if (entries.length === 0) return <p className="text-xs text-[#717785]">No audit entries for this record.</p>;
  return (
    <ol className="space-y-3">
      {entries.map((e, i) => (
        <li key={e.id ?? i} className="border-l-2 border-[#c1c6d6] pl-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <span className="font-semibold text-[#1a1b1f]">{ACTION_LABELS[e.action] || e.action}</span>
            <span className="text-[#717785]">{e.created_at ? new Date(e.created_at).toLocaleString('en-IN') : ''}</span>
            <span className="text-[#717785]">by {e.officer}</span>
            {e.signature_valid === true && <span className="text-[10px] font-bold text-[#00531d] bg-[#dcf5e1] px-1.5 py-0.5 rounded">SIGNATURE OK</span>}
            {e.signature_valid === false && <span className="text-[10px] font-bold text-[#93000a] bg-[#ffdad6] px-1.5 py-0.5 rounded">SIGNATURE INVALID — ENTRY ALTERED</span>}
          </div>
          <pre className="mt-1 text-[11px] text-[#414753] whitespace-pre-wrap break-words font-sans leading-relaxed">{e.details}</pre>
        </li>
      ))}
    </ol>
  );
};


/** The exact two face regions that were compared, so a wrong pick (e.g. a ghost image) is visible. */
export const FacesCompared: React.FC<{ face: ScreeningAnalysis['face'] }> = ({ face }) => {
  if (!face.attempted && !face.document_face_thumb) return null;
  const decision = face.decision && face.decision !== 'not_run' ? face.decision : null;
  const tone = decision === 'match' ? 'text-[#006a26]' : decision === 'uncertain' ? 'text-[#8a5600]' : 'text-[#ba1a1a]';
  const Thumb: React.FC<{ src?: string | null; label: string }> = ({ src, label }) => (
    <figure className="text-center space-y-1">
      <div className="w-20 h-20 rounded-lg overflow-hidden bg-[#f4f3f8] border border-[#efedf3] flex items-center justify-center">
        {src ? <img src={src} alt={label} className="w-full h-full object-cover" /> : <span className="text-[10px] text-[#717785] px-1">no face found</span>}
      </div>
      <figcaption className="text-[10px] text-[#717785]">{label}</figcaption>
    </figure>
  );
  return (
    <div className="flex items-center gap-3">
      <Thumb src={face.document_face_thumb} label="From document" />
      {face.attempted && (
        <>
          <div className="text-center text-xs">
            <div className={`font-bold font-mono ${tone}`}>
              {face.similarity != null ? `${Math.round(face.similarity * 100)}%` : '—'}
            </div>
            <div className={`text-[10px] font-semibold ${tone}`}>
              {decision === 'match' ? 'same person' : decision === 'uncertain' ? 'inconclusive' : decision === 'mismatch' ? 'different person' : 'not compared'}
            </div>
          </div>
          <Thumb src={face.live_face_thumb} label="Live photo" />
        </>
      )}
      {(face.document_face_candidates ?? 0) > 1 && (
        <p className="text-[10.5px] text-[#717785] max-w-[180px]">
          {face.document_face_candidates} face-like regions on the document; the sharpest, highest-contrast one was used
          (ghost images and watermarks are skipped).
        </p>
      )}
    </div>
  );
};

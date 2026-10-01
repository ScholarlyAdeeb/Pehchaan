import React, { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { checkNeonStatus } from '../services/neonSyncService';
import { NeonTelemetryStatus } from '../types';

interface ModelInfo {
  key: string;
  name: string;
  kind: string;
  architecture: string;
  purpose: string;
  status: 'active' | 'disabled' | 'missing';
  weights?: { present: boolean; size_mb?: number; modified?: string } | null;
  classes?: string[];
  details?: Record<string, unknown> | null;
  caveat?: string | null;
  training?: {
    train_images: number;
    validation_images: number;
    validation_accuracy: number;
    epochs: number;
    optimizer: string;
    input_size: number[];
    per_class: Record<string, { support: number; precision: number; recall: number }>;
    confusion_matrix: { rows_true_cols_pred: string[]; matrix: number[][] };
  } | null;
}

interface ModelsResponse {
  generated_at: string;
  models: ModelInfo[];
  risk_engine: { weights: Record<string, number>; clear_max: number; review_max: number };
  records_database: string;
}

const STATUS_STYLE: Record<string, string> = {
  active: 'bg-[#dcf5e1] text-[#00531d]',
  disabled: 'bg-[#e9e7ed] text-[#414753]',
  missing: 'bg-[#ffdad6] text-[#93000a]',
};

const RULES: { area: string; rule: string; how: string; severity: string }[] = [
  { area: 'Passport MRZ', rule: 'Check digits', how: 'ICAO 9303 weights 7-3-1, mod 10, on document number, DOB, expiry, personal number and the composite', severity: 'Critical' },
  { area: 'Passport MRZ', rule: 'Printed page vs MRZ', how: 'Name, DOB, expiry and passport number printed on the page must equal the MRZ', severity: 'Critical' },
  { area: 'Passport', rule: 'Expiry / age', how: 'Expired document; implausible age (<0 or >120 years)', severity: 'Critical' },
  { area: 'Passport', rule: 'Issuing office', how: 'File-number office code looked up in the Passport Seva Kendra list', severity: 'Warning' },
  { area: 'Aadhaar', rule: 'Verhoeff checksum', how: 'The 12th digit must satisfy the Verhoeff algorithm used by UIDAI', severity: 'Critical' },
  { area: 'PAN', rule: 'Format', how: 'Five letters, four digits, one letter (ABCDE1234F); 4th letter gives holder type', severity: 'Critical' },
  { area: 'Driving licence', rule: 'Format', how: 'State code + RTO code + year + serial; state code must be a valid RTO state', severity: 'Warning' },
  { area: 'Address', rule: 'PIN code vs state', how: 'The PIN code must belong to the state printed on the document', severity: 'Critical' },
  { area: 'Visa', rule: 'e-Visa eligibility', how: 'Nationality must be on the e-Visa eligible list', severity: 'Critical' },
  { area: 'Any', rule: 'Required fields', how: 'Name and document number must be readable', severity: 'Warning' },
  { area: 'Any', rule: 'Document type', how: 'Selected type disagrees strongly with auto-detection', severity: 'Warning' },
  { area: 'Records', rule: 'Same number, different holder', how: 'Earlier screening of this number has a different name or DOB', severity: 'Critical' },
];

export const SystemHealthDocsView: React.FC = () => {
  const { token } = useAuth();
  const [models, setModels] = useState<ModelsResponse | null>(null);
  const [engineError, setEngineError] = useState<string | null>(null);
  const [neon, setNeon] = useState<NeonTelemetryStatus | null>(null);
  const [chain, setChain] = useState<{ valid: boolean; totalBlocks: number; latestBlock: number } | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    const headers = { Authorization: `Bearer ${token}` };
    const [m, n, c] = await Promise.allSettled([
      fetch('/api/engine/models', { headers }).then(async (r) => {
        const body = await r.json();
        if (!r.ok) throw new Error(body.error || `HTTP ${r.status}`);
        return body as ModelsResponse;
      }),
      checkNeonStatus(token),
      fetch('/api/chain/status', { headers }).then((r) => (r.ok ? r.json() : null)),
    ]);
    if (m.status === 'fulfilled') { setModels(m.value); setEngineError(null); } else { setModels(null); setEngineError(m.reason?.message); }
    if (n.status === 'fulfilled') setNeon(n.value);
    if (c.status === 'fulfilled') setChain(c.value);
    setLoading(false);
  }, [token]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-4 sm:p-6 space-y-6 max-w-[1400px] mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-3 pb-4 border-b border-[#efedf3]">
        <div>
          <h1 className="text-xl font-bold text-[#1a1b1f]">System health &amp; models</h1>
          <p className="text-xs text-[#414753] mt-0.5">
            Live status reported by the screening engine and database{models ? ` · ${new Date(models.generated_at).toLocaleTimeString()}` : ''}
          </p>
        </div>
        <button onClick={load} disabled={loading} className="btn-secondary self-start">
          <span className={`material-symbols-outlined text-[16px] ${loading ? 'animate-spin' : ''}`}>refresh</span> Refresh
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatusTile
          title="Screening engine (Python)"
          ok={!!models}
          value={models ? 'Reachable' : 'Unreachable'}
          sub={engineError || `${models?.models.filter((x) => x.status === 'active').length} components active`}
        />
        <StatusTile
          title="Records database (Neon)"
          ok={!!neon?.connected}
          value={neon?.connected ? `${neon.totalScans} scans stored` : 'Not connected'}
          sub={neon ? (neon.connected ? `${neon.latencyMs} ms round trip · ${neon.database}` : neon.message) : '…'}
        />
        <StatusTile
          title="Hash chain"
          ok={!!chain?.valid}
          value={chain ? (chain.valid ? 'Intact' : 'Broken') : '…'}
          sub={chain ? `${chain.totalBlocks} linked records` : 'Checking'}
        />
      </div>

      {engineError && (
        <div className="p-3 rounded-lg bg-[#fff1f0] border border-[#ffdad6] text-xs text-[#93000a]">
          {engineError}. Start the backend with <code className="font-mono">start_all.bat</code> (port 8000).
        </div>
      )}

      {models && (
        <section className="space-y-3">
          <h2 className="text-xs font-bold text-[#1a1b1f] uppercase tracking-wider">Models and engines in the pipeline</h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {models.models.map((m) => <ModelCard key={m.key} m={m} />)}
          </div>
        </section>
      )}

      {models && (
        <section className="bg-white border border-[#efedf3] rounded-xl p-5 space-y-3">
          <h2 className="text-xs font-bold text-[#1a1b1f] uppercase tracking-wider">Risk score formula</h2>
          <p className="text-xs text-[#414753] leading-relaxed max-w-3xl">
            Each signal gives its own risk from 0 to 100. Score = Σ(risk × weight) ÷ Σ(weights of the signals that ran), so a
            missing live photo or a first-time document does not dilute the score. A critical rule failure, a “tampered”
            forensics verdict or a records conflict lifts the score to at least 66.
          </p>
          <div className="flex flex-wrap gap-2 text-xs">
            {Object.entries(models.risk_engine.weights).map(([k, w]) => (
              <span key={k} className="px-2.5 py-1 rounded bg-[#f4f3f8] font-mono">{k} {w}</span>
            ))}
            <span className="px-2.5 py-1 rounded bg-[#dcf5e1] font-mono">CLEAR ≤ {models.risk_engine.clear_max}</span>
            <span className="px-2.5 py-1 rounded bg-[#ffe4af] font-mono">REVIEW ≤ {models.risk_engine.review_max}</span>
            <span className="px-2.5 py-1 rounded bg-[#ffdad6] font-mono">HIGH RISK &gt; {models.risk_engine.review_max}</span>
          </div>
        </section>
      )}

      <section className="bg-white border border-[#efedf3] rounded-xl p-5 space-y-3">
        <h2 className="text-xs font-bold text-[#1a1b1f] uppercase tracking-wider">Document rules applied</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-[#717785] border-b border-[#efedf3]">
                <th className="py-2 pr-3">Applies to</th><th className="py-2 px-3">Rule</th><th className="py-2 px-3">How it is checked</th><th className="py-2 pl-3">Severity</th>
              </tr>
            </thead>
            <tbody>
              {RULES.map((r) => (
                <tr key={r.area + r.rule} className="border-b border-[#f4f3f8] align-top">
                  <td className="py-2 pr-3 whitespace-nowrap">{r.area}</td>
                  <td className="py-2 px-3 font-semibold whitespace-nowrap">{r.rule}</td>
                  <td className="py-2 px-3 text-[#414753]">{r.how}</td>
                  <td className="py-2 pl-3">{r.severity}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-[#717785]">Penalties per finding: critical 30, warning 10, info 2 (validation risk = sum, capped at 100).</p>
      </section>
    </div>
  );
};

const StatusTile: React.FC<{ title: string; ok: boolean; value: string; sub?: string }> = ({ title, ok, value, sub }) => (
  <div className="bg-white border border-[#efedf3] rounded-xl p-4 space-y-1">
    <div className="flex items-center justify-between text-[11px] text-[#717785] font-semibold">
      {title}
      <span className={`w-2 h-2 rounded-full ${ok ? 'bg-[#008633]' : 'bg-[#ba1a1a]'}`} />
    </div>
    <div className="text-lg font-bold text-[#1a1b1f]">{value}</div>
    {sub && <div className="text-[11px] text-[#717785] break-words">{sub}</div>}
  </div>
);

const ModelCard: React.FC<{ m: ModelInfo }> = ({ m }) => (
  <article className="bg-white border border-[#efedf3] rounded-xl p-4 space-y-2 text-xs">
    <div className="flex items-start justify-between gap-2">
      <div>
        <h3 className="text-sm font-bold text-[#1a1b1f]">{m.name}</h3>
        <div className="text-[#717785]">{m.kind} · {m.architecture}</div>
      </div>
      <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${STATUS_STYLE[m.status]}`}>{m.status}</span>
    </div>
    <p className="text-[#414753]">{m.purpose}</p>
    {m.weights?.present && (
      <p className="text-[#717785]">Weights {m.weights.size_mb} MB · updated {new Date(m.weights.modified!).toLocaleDateString()}</p>
    )}
    {m.training && (
      <div className="bg-[#f4f3f8] rounded-lg p-3 space-y-2">
        <div className="flex flex-wrap gap-x-4 gap-y-1">
          <span><b>{(m.training.validation_accuracy * 100).toFixed(1)}%</b> validation accuracy</span>
          <span>{m.training.train_images} train / {m.training.validation_images} held-out images</span>
          <span>{m.training.epochs} epochs · {m.training.optimizer} · {m.training.input_size.join('×')} px</span>
        </div>
        <table className="text-[11px] tabular-nums">
          <thead>
            <tr className="text-[#717785]"><th className="pr-3 text-left font-semibold">Class</th><th className="px-2 font-semibold">Images</th><th className="px-2 font-semibold">Precision</th><th className="pl-2 font-semibold">Recall</th></tr>
          </thead>
          <tbody>
            {(Object.entries(m.training.per_class) as [string, { support: number; precision: number; recall: number }][]).map(([c, v]) => (
              <tr key={c}>
                <td className="pr-3">{c}</td>
                <td className="px-2 text-center">{v.support}</td>
                <td className="px-2 text-center">{(v.precision * 100).toFixed(1)}%</td>
                <td className="pl-2 text-center">{(v.recall * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
    {m.details && (
      <p className="text-[#717785] font-mono text-[10.5px] break-words">
        {Object.entries(m.details).map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`).join(' · ')}
      </p>
    )}
    {m.caveat && <p className="text-[#5c3a00] bg-[#fff4dc] rounded p-2">{m.caveat}</p>}
  </article>
);

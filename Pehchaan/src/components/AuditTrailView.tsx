import React, { useEffect, useMemo, useState } from 'react';
import { AuditEntry, ScreeningRecord, ScreenType } from '../types';
import { useAuth } from '../contexts/AuthContext';
import { fetchAuditTrail, fetchScanDetail } from '../services/neonSyncService';
import { EvaluationMatrix, RecordAuditLog, VerdictBadge, verdictTone } from './screening/ScreeningParts';

interface AuditTrailViewProps {
  records: ScreeningRecord[];
  onSelectRecord: (record: ScreeningRecord) => void;
  onNavigate: (screen: ScreenType) => void;
}

type ChainState = { valid: boolean; totalBlocks: number; latestBlock: number; brokenAt?: number; error?: string };

export const AuditTrailView: React.FC<AuditTrailViewProps> = ({ records, onSelectRecord, onNavigate }) => {
  const { token, isAdmin } = useAuth();
  const [search, setSearch] = useState('');
  const [verdict, setVerdict] = useState<'ALL' | 'CLEAR' | 'REVIEW' | 'HIGH RISK'>('ALL');
  const [selectedId, setSelectedId] = useState<string | null>(records[0]?.id ?? null);
  const [detail, setDetail] = useState<ScreeningRecord | null>(null);
  const [entries, setEntries] = useState<AuditEntry[] | null>(null);
  const [chain, setChain] = useState<ChainState | null>(null);
  const [verifying, setVerifying] = useState(false);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return records.filter((r) =>
      (verdict === 'ALL' || r.riskVerdict === verdict) &&
      (!q || [r.id, r.presenterName, r.docNumber, r.fullHash, r.officer].some((v) => v?.toLowerCase().includes(q))));
  }, [records, search, verdict]);

  const selected = records.find((r) => r.id === selectedId) || null;

  useEffect(() => {
    if (!token) return;
    fetch('/api/chain/status', { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : null)).then(setChain).catch(() => setChain(null));
  }, [token, records.length]);

  useEffect(() => {
    if (!selected || !token) return;
    setDetail(selected.analysis ? selected : null);
    setEntries(null);
    if (!selected.analysis && selected.hasAnalysis) fetchScanDetail(selected.id, token).then((d) => d && setDetail(d));
    fetchAuditTrail(selected.id, token).then(setEntries).catch(() => setEntries([]));
  }, [selectedId, token]); // eslint-disable-line react-hooks/exhaustive-deps

  const verifyChain = async () => {
    if (!token) return;
    setVerifying(true);
    try {
      const res = await fetch('/api/chain/verify', { headers: { Authorization: `Bearer ${token}` } });
      if (res.ok) setChain(await res.json());
    } finally {
      setVerifying(false);
    }
  };

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(filtered, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pehchaan-screenings-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="p-4 sm:p-6 space-y-5 max-w-[1500px] mx-auto">
      <div className="flex flex-col lg:flex-row lg:items-end justify-between gap-3 pb-4 border-b border-[#efedf3]">
        <div>
          <h1 className="text-xl font-bold text-[#1a1b1f]">Audit trail</h1>
          <p className="text-xs text-[#414753] mt-0.5">
            Every screening with its evaluation, signed log entries and position in the hash chain.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {chain && (
            <span className={`px-2.5 py-1 rounded text-xs font-semibold ${chain.valid ? 'bg-[#dcf5e1] text-[#00531d]' : 'bg-[#ffdad6] text-[#93000a]'}`}>
              Chain {chain.valid ? 'intact' : `broken${chain.brokenAt ? ` at block #${chain.brokenAt}` : ''}`} · {chain.totalBlocks} records
            </span>
          )}
          {isAdmin && (
            <button onClick={verifyChain} disabled={verifying} className="btn-secondary">
              <span className={`material-symbols-outlined text-[16px] ${verifying ? 'animate-spin' : ''}`}>verified</span>
              {verifying ? 'Recomputing…' : 'Recompute every hash'}
            </button>
          )}
          <button onClick={exportJson} className="btn-ghost">
            <span className="material-symbols-outlined text-[16px]">download</span> Export list
          </button>
        </div>
      </div>
      {chain?.error && <p className="text-xs text-[#93000a]">{chain.error}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        <section className="lg:col-span-2 bg-white border border-[#efedf3] rounded-xl overflow-hidden">
          <div className="p-3 border-b border-[#efedf3] flex flex-col sm:flex-row gap-2">
            <label className="sr-only" htmlFor="audit-search">Search</label>
            <input
              id="audit-search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search ID, name, document no., officer, hash"
              className="flex-1 text-xs px-3 py-2 border border-[#e3e2e7] rounded-lg focus:outline-none focus:border-[#0059b5]"
            />
            <label className="sr-only" htmlFor="audit-verdict">Verdict</label>
            <select
              id="audit-verdict"
              value={verdict}
              onChange={(e) => setVerdict(e.target.value as typeof verdict)}
              className="text-xs px-2 py-2 border border-[#e3e2e7] rounded-lg"
            >
              <option value="ALL">All verdicts</option>
              <option value="CLEAR">Clear</option>
              <option value="REVIEW">Review</option>
              <option value="HIGH RISK">High risk</option>
            </select>
          </div>
          {filtered.length === 0 ? (
            <p className="p-6 text-center text-xs text-[#717785]">No screenings match.</p>
          ) : (
            <ul className="max-h-[70vh] overflow-y-auto divide-y divide-[#f4f3f8]">
              {filtered.map((r) => {
                const tone = verdictTone(r.riskVerdict);
                return (
                  <li key={r.id}>
                    <button
                      onClick={() => setSelectedId(r.id)}
                      className={`w-full text-left p-3 flex items-start gap-3 ${selectedId === r.id ? 'bg-[#eef3ff]' : 'hover:bg-[#fbfbfe]'}`}
                    >
                      <span className={`mt-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold font-mono shrink-0 ${tone.chip}`}>{r.riskScore}</span>
                      <div className="min-w-0">
                        <div className="text-xs font-semibold text-[#1a1b1f] truncate">{r.presenterName} · {r.docCode}</div>
                        <div className="text-[10.5px] text-[#717785] truncate">{r.id} · {r.timestamp}</div>
                        <div className="text-[10.5px] text-[#717785] truncate">{r.lane} · {r.officer} · block {r.blockHeight}</div>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>

        <section className="lg:col-span-3 space-y-4">
          {!selected ? (
            <p className="text-xs text-[#717785]">Select a screening to see its log.</p>
          ) : (
            <>
              <div className={`rounded-xl p-4 ${verdictTone(selected.riskVerdict).panel}`}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <VerdictBadge verdict={selected.riskVerdict} />
                    <div className="text-xs mt-1.5">{selected.presenterName} · {selected.docCode} · {selected.docNumber || 'number not read'}</div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-3xl font-extrabold font-mono">{selected.riskScore}</span>
                    <button
                      onClick={() => { onSelectRecord(detail || selected); onNavigate('screening-report'); }}
                      className="px-3 py-2 bg-white/80 hover:bg-white rounded-lg text-xs font-semibold text-[#1a1b1f]"
                    >
                      Full report
                    </button>
                  </div>
                </div>
              </div>

              <div className="bg-white border border-[#efedf3] rounded-xl p-4 space-y-2">
                <h2 className="text-xs font-bold uppercase tracking-wider text-[#1a1b1f]">Evaluation at time of screening</h2>
                {detail?.analysis ? (
                  <EvaluationMatrix rows={detail.analysis.evaluation} compact />
                ) : selected.hasAnalysis ? (
                  <p className="text-xs text-[#717785]">Loading…</p>
                ) : (
                  <p className="text-xs text-[#717785]">This record predates stored evaluations.</p>
                )}
              </div>

              <div className="bg-white border border-[#efedf3] rounded-xl p-4 space-y-3">
                <h2 className="text-xs font-bold uppercase tracking-wider text-[#1a1b1f]">Log entries</h2>
                <RecordAuditLog entries={entries} />
              </div>

              <div className="bg-white border border-[#efedf3] rounded-xl p-4 text-xs space-y-1">
                <h2 className="text-xs font-bold uppercase tracking-wider text-[#1a1b1f] mb-1">Chain position</h2>
                <div>Block <span className="font-mono">{selected.blockHeight}</span> · checkpoint {selected.lane || '—'} · officer {selected.officer || '—'}</div>
                <div className="font-mono text-[11px] break-all text-[#414753]">SHA-256 {selected.fullHash}</div>
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  );
};

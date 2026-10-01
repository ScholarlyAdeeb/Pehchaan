import React, { useMemo, useState } from 'react';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid, Cell, Legend,
} from 'recharts';
import { ScreeningRecord } from '../types';

interface RiskDistributionVisualizerProps {
  records: ScreeningRecord[];
  selectedFilter: string | null;
  onSelectFilter: (filter: string | null) => void;
}

const VERDICT_COLORS = { CLEAR: '#008633', REVIEW: '#c98a00', 'HIGH RISK': '#ba1a1a' } as const;
const AXIS = { fontSize: 11, fill: '#5b606b' };

type Tab = 'scores' | 'documents' | 'hourly' | 'findings';

function bandOf(score: number) {
  return score <= 30 ? 'CLEAR' : score <= 65 ? 'REVIEW' : 'HIGH RISK';
}

export const RiskDistributionVisualizer: React.FC<RiskDistributionVisualizerProps> = ({
  records, selectedFilter, onSelectFilter,
}) => {
  const [tab, setTab] = useState<Tab>('scores');

  const scoreBuckets = useMemo(() => {
    const buckets = Array.from({ length: 10 }, (_, i) => ({
      label: `${i * 10}–${i === 9 ? 100 : i * 10 + 9}`, count: 0, verdict: bandOf(i * 10 + 5),
    }));
    records.forEach((r) => { buckets[Math.min(9, Math.floor(r.riskScore / 10))].count += 1; });
    return buckets;
  }, [records]);

  const byDocument = useMemo(() => {
    const map = new Map<string, { type: string; CLEAR: number; REVIEW: number; 'HIGH RISK': number }>();
    records.forEach((r) => {
      const row = map.get(r.docCode) || { type: r.docCode, CLEAR: 0, REVIEW: 0, 'HIGH RISK': 0 };
      row[r.riskVerdict] += 1;
      map.set(r.docCode, row);
    });
    return [...map.values()].sort((a, b) => b.CLEAR + b.REVIEW + b['HIGH RISK'] - (a.CLEAR + a.REVIEW + a['HIGH RISK']));
  }, [records]);

  const hourly = useMemo(() => {
    const rows = Array.from({ length: 24 }, (_, h) => ({ hour: `${String(h).padStart(2, '0')}:00`, CLEAR: 0, REVIEW: 0, 'HIGH RISK': 0 }));
    let dated = 0;
    records.forEach((r) => {
      const d = new Date(r.localTime);
      if (Number.isNaN(d.getTime())) return;
      dated += 1;
      rows[d.getHours()][r.riskVerdict] += 1;
    });
    return { rows, dated };
  }, [records]);

  const findings = useMemo(() => {
    const counts = new Map<string, number>();
    records.filter((r) => r.riskVerdict !== 'CLEAR' && r.findings).forEach((r) => {
      const key = r.findings.split(/[:—.]/)[0].trim().slice(0, 70);
      counts.set(key, (counts.get(key) || 0) + 1);
    });
    return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
  }, [records]);

  const total = records.length;
  const verdictCounts = (['CLEAR', 'REVIEW', 'HIGH RISK'] as const).map((v) => ({
    v, n: records.filter((r) => r.riskVerdict === v).length,
  }));
  const avg = total ? Math.round(records.reduce((s, r) => s + r.riskScore, 0) / total) : 0;

  const tabs: { id: Tab; label: string }[] = [
    { id: 'scores', label: 'Risk scores' },
    { id: 'documents', label: 'Document types' },
    { id: 'hourly', label: 'By hour' },
    { id: 'findings', label: 'Top findings' },
  ];

  return (
    <div className="bg-white border border-[#efedf3] rounded-xl overflow-hidden">
      <div className="p-4 border-b border-[#efedf3] bg-[#fbfbfe] flex flex-col lg:flex-row lg:items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-bold text-[#1a1b1f] flex items-center gap-2">
            <span className="material-symbols-outlined text-[#0059b5] text-[18px]">query_stats</span>
            Screening analytics
          </h2>
          <p className="text-xs text-[#717785] mt-0.5">
            From the {total} most recent screening records in the database · average risk {avg}/100
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1 bg-[#f4f3f8] p-1 rounded-lg text-xs" role="tablist">
          {tabs.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => setTab(t.id)}
              className={`px-3 py-1.5 font-semibold rounded-md ${tab === t.id ? 'bg-white text-[#0059b5] shadow-xs' : 'text-[#414753] hover:text-[#1a1b1f]'}`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="p-5 space-y-4">
        {total === 0 ? (
          <p className="text-sm text-[#717785] text-center py-10">No screenings recorded yet — charts appear after the first scan.</p>
        ) : (
          <>
            {tab === 'scores' && (
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-center">
                <div className="lg:col-span-2 h-[260px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={scoreBuckets} margin={{ top: 10, right: 10, left: -10, bottom: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#efedf3" />
                      <XAxis dataKey="label" tick={AXIS} tickLine={false} />
                      <YAxis allowDecimals={false} tick={AXIS} axisLine={false} tickLine={false} />
                      <Tooltip formatter={(v: number) => [`${v} scans`, 'Count']} labelFormatter={(l) => `Risk score ${l}`} />
                      <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                        {scoreBuckets.map((b) => <Cell key={b.label} fill={VERDICT_COLORS[b.verdict as keyof typeof VERDICT_COLORS]} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="space-y-2">
                  {verdictCounts.map(({ v, n }) => (
                    <button
                      key={v}
                      onClick={() => onSelectFilter(selectedFilter === v ? null : v)}
                      className={`w-full p-2.5 rounded-lg border text-left flex items-center justify-between text-xs ${
                        selectedFilter === v ? 'border-[#0059b5] bg-[#eef3ff]' : 'border-[#efedf3] hover:border-[#c1c6d6]'
                      }`}
                    >
                      <span className="flex items-center gap-2 font-semibold text-[#1a1b1f]">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ background: VERDICT_COLORS[v] }} />
                        {v} {v === 'CLEAR' ? '(0–30)' : v === 'REVIEW' ? '(31–65)' : '(66–100)'}
                      </span>
                      <span className="font-mono font-bold tabular-nums">{n} ({Math.round((n / total) * 100)}%)</span>
                    </button>
                  ))}
                  <p className="text-[10.5px] text-[#717785]">Click a band to filter the table below.</p>
                </div>
              </div>
            )}

            {tab === 'documents' && (
              <div className="h-[280px]">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={byDocument} layout="vertical" margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#efedf3" />
                    <XAxis type="number" allowDecimals={false} tick={AXIS} />
                    <YAxis dataKey="type" type="category" width={110} tick={{ ...AXIS, fill: '#1a1b1f' }} />
                    <Tooltip />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    {(['CLEAR', 'REVIEW', 'HIGH RISK'] as const).map((v) => (
                      <Bar key={v} dataKey={v} stackId="v" fill={VERDICT_COLORS[v]} />
                    ))}
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}

            {tab === 'hourly' && (
              <div className="space-y-2">
                <div className="h-[260px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={hourly.rows} margin={{ top: 10, right: 10, left: -10, bottom: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#efedf3" />
                      <XAxis dataKey="hour" tick={AXIS} interval={2} />
                      <YAxis allowDecimals={false} tick={AXIS} axisLine={false} tickLine={false} />
                      <Tooltip />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      {(['CLEAR', 'REVIEW', 'HIGH RISK'] as const).map((v) => (
                        <Bar key={v} dataKey={v} stackId="h" fill={VERDICT_COLORS[v]} />
                      ))}
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <p className="text-[10.5px] text-[#717785]">
                  Local time of day, {hourly.dated} of {total} records carry a timestamp this chart can read.
                </p>
              </div>
            )}

            {tab === 'findings' && (
              findings.length === 0 ? (
                <p className="text-sm text-[#717785] py-6 text-center">No REVIEW or HIGH RISK screenings yet.</p>
              ) : (
                <ul className="space-y-2">
                  {findings.map(([text, n]) => (
                    <li key={text} className="grid grid-cols-[1fr_auto] gap-3 items-center text-xs">
                      <div className="min-w-0">
                        <div className="text-[#1a1b1f] truncate" title={text}>{text}</div>
                        <div className="h-1.5 bg-[#efedf3] rounded-full mt-1 overflow-hidden">
                          <div className="h-full bg-[#ba1a1a]" style={{ width: `${(n / findings[0][1]) * 100}%` }} />
                        </div>
                      </div>
                      <span className="font-mono font-bold tabular-nums">{n}</span>
                    </li>
                  ))}
                </ul>
              )
            )}
          </>
        )}
      </div>
    </div>
  );
};

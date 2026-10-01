import React, { useState } from 'react';
import { ScreeningRecord, ScreenType } from '../types';

interface OfficerStatusViewProps {
  records: ScreeningRecord[];
  onNavigate: (screen: ScreenType) => void;
}

interface OfficerSummary {
  name: string;
  uid: string;
  totalScans: number;
  clear: number;
  review: number;
  highRisk: number;
  avgRiskScore: number;
  lastActive: string;
  lanes: string[];
}

function aggregateOfficers(records: ScreeningRecord[]): OfficerSummary[] {
  const map = new Map<string, OfficerSummary>();

  for (const r of records) {
    const key = r.officerUid || r.officer;
    let entry = map.get(key);
    if (!entry) {
      entry = {
        name: r.officer,
        uid: r.officerUid,
        totalScans: 0,
        clear: 0,
        review: 0,
        highRisk: 0,
        avgRiskScore: 0,
        lastActive: r.timestamp,
        lanes: [],
      };
      map.set(key, entry);
    }
    entry.totalScans++;
    if (r.riskVerdict === 'CLEAR') entry.clear++;
    else if (r.riskVerdict === 'REVIEW') entry.review++;
    else if (r.riskVerdict === 'HIGH RISK') entry.highRisk++;
    entry.avgRiskScore += r.riskScore;
    if (r.lane && !entry.lanes.includes(r.lane)) entry.lanes.push(r.lane);
  }

  return Array.from(map.values()).map((o) => ({
    ...o,
    avgRiskScore: o.totalScans > 0 ? Math.round(o.avgRiskScore / o.totalScans) : 0,
  }));
}

export const OfficerStatusView: React.FC<OfficerStatusViewProps> = ({ records, onNavigate }) => {
  const officers = aggregateOfficers(records);
  const [selectedOfficer, setSelectedOfficer] = useState<OfficerSummary | null>(
    officers.length > 0 ? officers[0] : null
  );
  const [searchQuery, setSearchQuery] = useState('');

  const filtered = officers.filter(
    (o) =>
      o.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      o.uid.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const selectedRecords = selectedOfficer
    ? records.filter((r) => r.officerUid === selectedOfficer.uid || r.officer === selectedOfficer.name)
    : [];

  return (
    <div className="p-6 space-y-6 max-w-[1720px] mx-auto">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-[#efedf3]">
        <div>
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 text-[10px] font-bold font-mono uppercase bg-[#fce4ec] text-[#880e4f] rounded-sm">
              ADMINISTRATIVE
            </span>
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[#f1ffec] text-[#006a26] text-xs font-mono font-semibold">
              <span className="w-1.5 h-1.5 rounded-full bg-[#008633]"></span>
              Live Roster
            </span>
          </div>
          <h1 className="text-xl font-bold text-[#1a1b1f] mt-1">Officer Status & Performance Dashboard</h1>
          <p className="text-xs text-[#414753] mt-0.5">
            Track record and screening performance of all duty officers across checkpoints.
          </p>
        </div>

        <button
          onClick={() => onNavigate('admin-portal')}
          className="text-xs font-semibold text-[#0059b5] hover:underline flex items-center gap-1 cursor-pointer"
        >
          <span className="material-symbols-outlined text-[16px]">arrow_back</span>
          <span>Back to Admin Portal</span>
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-[#ffffff] p-4 rounded-xl border border-[#efedf3] shadow-2xs space-y-1">
          <div className="text-[10px] font-semibold text-[#717785] uppercase">Total Officers</div>
          <div className="text-2xl font-bold font-mono text-[#1a1b1f]">{officers.length}</div>
          <p className="text-[11px] text-[#006a26] font-medium">Active in current dataset</p>
        </div>
        <div className="bg-[#ffffff] p-4 rounded-xl border border-[#efedf3] shadow-2xs space-y-1">
          <div className="text-[10px] font-semibold text-[#717785] uppercase">Total Screenings</div>
          <div className="text-2xl font-bold font-mono text-[#0059b5]">{records.length}</div>
          <p className="text-[11px] text-[#717785]">Across all officers</p>
        </div>
        <div className="bg-[#ffffff] p-4 rounded-xl border border-[#efedf3] shadow-2xs space-y-1">
          <div className="text-[10px] font-semibold text-[#717785] uppercase">Avg. Risk Score</div>
          <div className="text-2xl font-bold font-mono text-[#b45309]">
            {records.length > 0
              ? Math.round(records.reduce((sum, r) => sum + r.riskScore, 0) / records.length)
              : 0}
          </div>
          <p className="text-[11px] text-[#717785]">Across all screenings</p>
        </div>
        <div className="bg-[#ffffff] p-4 rounded-xl border border-[#efedf3] shadow-2xs space-y-1">
          <div className="text-[10px] font-semibold text-[#717785] uppercase">High Risk Flags</div>
          <div className="text-2xl font-bold font-mono text-[#ba1a1a]">
            {records.filter((r) => r.riskVerdict === 'HIGH RISK').length}
          </div>
          <p className="text-[11px] text-[#717785]">Requiring officer intervention</p>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 bg-[#ffffff] border border-[#efedf3] rounded-xl shadow-2xs overflow-hidden">
          <div className="p-3.5 border-b border-[#efedf3] bg-[#fbfbfe] flex items-center justify-between">
            <span className="text-xs font-bold text-[#1a1b1f] uppercase tracking-wider">
              Officer Roster ({filtered.length})
            </span>
            <div className="relative">
              <span className="material-symbols-outlined absolute left-2.5 top-2 text-[16px] text-[#717785]">search</span>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search officer..."
                className="text-xs pl-8 pr-3 py-1.5 bg-[#f4f3f8] border border-[#efedf3] rounded-lg focus:outline-hidden focus:border-[#0059b5] w-48"
              />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="bg-[#f4f3f8] text-[#414753] font-semibold text-[11px] border-b border-[#efedf3]">
                  <th className="py-2.5 px-3">Officer</th>
                  <th className="py-2.5 px-3">UID</th>
                  <th className="py-2.5 px-3 text-center">Scans</th>
                  <th className="py-2.5 px-3 text-center">Clear</th>
                  <th className="py-2.5 px-3 text-center">Review</th>
                  <th className="py-2.5 px-3 text-center">High Risk</th>
                  <th className="py-2.5 px-3 text-center">Avg Risk</th>
                  <th className="py-2.5 px-3">Lanes</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efedf3]">
                {filtered.map((o) => {
                  const isSelected = selectedOfficer?.uid === o.uid;
                  return (
                    <tr
                      key={o.uid}
                      onClick={() => setSelectedOfficer(o)}
                      className={`hover:bg-[#f4f3f8] cursor-pointer transition-colors ${
                        isSelected ? 'bg-[#d7e2ff]/20' : ''
                      }`}
                    >
                      <td className="py-3 px-3">
                        <div className="flex items-center gap-2">
                          <span className="w-7 h-7 rounded-full bg-[#d7e2ff] flex items-center justify-center">
                            <span className="material-symbols-outlined text-[14px] text-[#0059b5]">person</span>
                          </span>
                          <span className="font-semibold text-[#1a1b1f]">{o.name}</span>
                        </div>
                      </td>
                      <td className="py-3 px-3 font-mono text-[#414753]">{o.uid}</td>
                      <td className="py-3 px-3 text-center font-mono font-bold text-[#1a1b1f]">{o.totalScans}</td>
                      <td className="py-3 px-3 text-center">
                        <span className="px-1.5 py-0.5 rounded bg-[#f1ffec] text-[#006a26] font-mono font-bold text-[11px]">
                          {o.clear}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-center">
                        <span className="px-1.5 py-0.5 rounded bg-[#ffe4af] text-[#7c4d00] font-mono font-bold text-[11px]">
                          {o.review}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-center">
                        <span className="px-1.5 py-0.5 rounded bg-[#ffdad6] text-[#ba1a1a] font-mono font-bold text-[11px]">
                          {o.highRisk}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-center font-mono text-[#414753]">{o.avgRiskScore}</td>
                      <td className="py-3 px-3 text-[11px] text-[#717785]">{o.lanes.join(', ')}</td>
                    </tr>
                  );
                })}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={8} className="py-8 text-center text-[#717785]">
                      No officers found
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {selectedOfficer && (
          <div className="bg-[#ffffff] border border-[#efedf3] rounded-xl p-5 shadow-2xs space-y-4">
            <div className="flex items-center justify-between border-b border-[#efedf3] pb-3">
              <span className="text-xs font-bold text-[#1a1b1f] uppercase tracking-wider">Officer Detail</span>
              <span className="text-[10px] font-mono bg-[#f1ffec] text-[#006a26] px-2 py-0.5 rounded font-semibold">
                ACTIVE
              </span>
            </div>

            <div className="flex items-center gap-3">
              <span className="w-14 h-14 rounded-full bg-[#d7e2ff] flex items-center justify-center">
                <span className="material-symbols-outlined text-[28px] text-[#0059b5]">person</span>
              </span>
              <div>
                <div className="font-bold text-[#1a1b1f]">{selectedOfficer.name}</div>
                <div className="text-[11px] font-mono text-[#717785]">{selectedOfficer.uid}</div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="bg-[#f4f3f8] rounded-lg p-3 text-center">
                <div className="text-lg font-bold font-mono text-[#1a1b1f]">{selectedOfficer.totalScans}</div>
                <div className="text-[10px] text-[#717785] font-semibold uppercase">Total Scans</div>
              </div>
              <div className="bg-[#f4f3f8] rounded-lg p-3 text-center">
                <div className="text-lg font-bold font-mono text-[#b45309]">{selectedOfficer.avgRiskScore}</div>
                <div className="text-[10px] text-[#717785] font-semibold uppercase">Avg Risk</div>
              </div>
            </div>

            <div className="space-y-2">
              <div className="text-[11px] font-semibold text-[#1a1b1f] uppercase">Verdict Breakdown</div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between text-xs">
                  <span className="text-[#006a26]">Clear</span>
                  <span className="font-mono font-bold">{selectedOfficer.clear}</span>
                </div>
                <div className="w-full bg-[#efedf3] rounded-full h-1.5">
                  <div
                    className="bg-[#22c55e] h-1.5 rounded-full"
                    style={{
                      width: `${selectedOfficer.totalScans > 0 ? (selectedOfficer.clear / selectedOfficer.totalScans) * 100 : 0}%`,
                    }}
                  />
                </div>

                <div className="flex items-center justify-between text-xs">
                  <span className="text-[#b45309]">Review</span>
                  <span className="font-mono font-bold">{selectedOfficer.review}</span>
                </div>
                <div className="w-full bg-[#efedf3] rounded-full h-1.5">
                  <div
                    className="bg-[#f59e0b] h-1.5 rounded-full"
                    style={{
                      width: `${selectedOfficer.totalScans > 0 ? (selectedOfficer.review / selectedOfficer.totalScans) * 100 : 0}%`,
                    }}
                  />
                </div>

                <div className="flex items-center justify-between text-xs">
                  <span className="text-[#ba1a1a]">High Risk</span>
                  <span className="font-mono font-bold">{selectedOfficer.highRisk}</span>
                </div>
                <div className="w-full bg-[#efedf3] rounded-full h-1.5">
                  <div
                    className="bg-[#ef4444] h-1.5 rounded-full"
                    style={{
                      width: `${selectedOfficer.totalScans > 0 ? (selectedOfficer.highRisk / selectedOfficer.totalScans) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>
            </div>

            <div className="space-y-2 pt-2 border-t border-[#efedf3]">
              <div className="text-[11px] font-semibold text-[#1a1b1f] uppercase">Recent Screenings</div>
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {selectedRecords.slice(0, 10).map((r) => (
                  <div
                    key={r.id}
                    className="flex items-center justify-between p-2 bg-[#f4f3f8] rounded-lg text-[11px]"
                  >
                    <div>
                      <span className="font-mono font-bold text-[#0059b5]">{r.id}</span>
                      <span className="text-[#717785] ml-2">{r.presenterName}</span>
                    </div>
                    <span
                      className={`px-1.5 py-0.5 rounded font-bold font-mono text-[10px] ${
                        r.riskVerdict === 'HIGH RISK'
                          ? 'bg-[#ffdad6] text-[#ba1a1a]'
                          : r.riskVerdict === 'REVIEW'
                          ? 'bg-[#ffe4af] text-[#7c4d00]'
                          : 'bg-[#f1ffec] text-[#006a26]'
                      }`}
                    >
                      {r.riskVerdict}
                    </span>
                  </div>
                ))}
                {selectedRecords.length === 0 && (
                  <p className="text-[11px] text-[#717785] text-center py-2">No screenings found</p>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

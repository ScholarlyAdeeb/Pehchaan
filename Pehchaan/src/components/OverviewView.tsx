import React, { useState } from 'react';
import { ScreeningRecord, ScreenType } from '../types';
import { RiskDistributionVisualizer } from './RiskDistributionVisualizer';
import { LiveClock } from './LiveClock';
import { useAuth } from '../contexts/AuthContext';
import { useI18n } from '../contexts/I18nContext';

interface OverviewViewProps {
  records: ScreeningRecord[];
  onNavigate: (screen: ScreenType) => void;
  onSelectRecord: (record: ScreeningRecord) => void;
}

export const OverviewView: React.FC<OverviewViewProps> = ({
  records,
  onNavigate,
  onSelectRecord,
}) => {
  const { user, isAdmin, isOfficer, checkpoint } = useAuth();
  const { t } = useI18n();
  const [activeFilter, setActiveFilter] = useState<string | null>(null);

  const filteredRecords = records.filter((r) => {
    if (!activeFilter) return true;
    if (activeFilter === 'CLEAR' || activeFilter === 'REVIEW' || activeFilter === 'HIGH RISK') {
      return r.riskVerdict === activeFilter;
    }
    if (r.docCode.toLowerCase().includes(activeFilter.toLowerCase()) || r.documentType.toLowerCase().includes(activeFilter.toLowerCase())) return true;
    return false;
  });

  return (
    <div className="p-6 space-y-6 max-w-[1720px] mx-auto">
      {/* Hero Banner */}
      <div className="bg-gradient-to-r from-[#0059b5] to-[#00458f] rounded-xl p-6 text-white shadow-md relative overflow-hidden">
        <div className="absolute right-0 top-0 bottom-0 w-1/3 bg-white/5 pointer-events-none skew-x-12"></div>

        <div className="relative z-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-6">
          <div className="space-y-2 max-w-2xl">
            <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full bg-white/15 text-xs font-mono text-white backdrop-blur-xs">
              <span className="w-2 h-2 rounded-full bg-[#72fe88] animate-ping"></span>
              {t('overview.engine_online')}
            </div>
            {isOfficer ? (
              <>
                <h1 className="text-2xl font-bold tracking-tight text-white">
                  {t('overview.welcome')}, {user?.name}
                </h1>
                <p className="text-white/85 text-xs leading-relaxed">
                  {checkpoint?.name} &mdash; {t('overview.officer_subtitle')}
                </p>
              </>
            ) : (
              <>
                <h1 className="text-2xl font-bold tracking-tight text-white">
                  {t('overview.title')}
                </h1>
                <p className="text-white/85 text-xs leading-relaxed">
                  {t('overview.subtitle')}
                </p>
              </>
            )}
          </div>

          <div className="flex items-center gap-3">
            {isOfficer && <LiveClock />}
            {(isOfficer || isAdmin) && (
              <button
                onClick={() => onNavigate('new-scan')}
                className="flex items-center gap-2 bg-[#ffffff] text-[#0059b5] hover:bg-[#f4f3f8] px-4 py-2.5 rounded-lg text-xs font-semibold shadow-xs transition-all active:scale-98 cursor-pointer"
              >
                <span className="material-symbols-outlined text-[18px]">document_scanner</span>
                <span>{t('overview.start_screening')}</span>
              </button>
            )}
            {!isOfficer && (
              <button
                onClick={() => onNavigate('audit-trail')}
                className="flex items-center gap-2 bg-white/10 hover:bg-white/20 border border-white/20 text-white px-3.5 py-2.5 rounded-lg text-xs font-medium transition-all"
              >
                <span className="material-symbols-outlined text-[18px]">history_edu</span>
                <span>{t('overview.audit_ledger')}</span>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-[#ffffff] p-4 rounded-xl border border-[#efedf3] shadow-2xs space-y-2">
          <div className="flex items-center justify-between text-[#717785] text-xs font-medium">
            <span>{t('overview.scans_today')}</span>
            <span className="material-symbols-outlined text-[#0059b5] text-[18px]">insights</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-[#1a1b1f] font-mono">{records.length}</span>
          </div>
          <div className="w-full bg-[#efedf3] h-1.5 rounded-full overflow-hidden">
            <div className="bg-[#0059b5] h-full" style={{ width: `${Math.min(100, (records.length / 20) * 100)}%` }}></div>
          </div>
        </div>

        <div
          onClick={() => setActiveFilter(activeFilter === 'CLEAR' ? null : 'CLEAR')}
          className="bg-[#ffffff] p-4 rounded-xl border border-[#efedf3] hover:border-[#008633] transition-all cursor-pointer shadow-2xs space-y-2"
        >
          <div className="flex items-center justify-between text-[#717785] text-xs font-medium">
            <span>{t('verdict.clear')}</span>
            <span className="material-symbols-outlined text-[#006a26] text-[18px]">verified</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-[#006a26] font-mono">{records.filter(r => r.riskVerdict === 'CLEAR').length}</span>
            <span className="text-xs text-[#414753] font-medium">
              {records.length > 0 ? `${Math.round((records.filter(r => r.riskVerdict === 'CLEAR').length / records.length) * 100)}%` : '—'}
            </span>
          </div>
        </div>

        <div
          onClick={() => setActiveFilter(activeFilter === 'REVIEW' ? null : 'REVIEW')}
          className="bg-[#ffffff] p-4 rounded-xl border border-[#efedf3] hover:border-[#ba7500] transition-all cursor-pointer shadow-2xs space-y-2"
        >
          <div className="flex items-center justify-between text-[#717785] text-xs font-medium">
            <span>{t('verdict.review')}</span>
            <span className="material-symbols-outlined text-[#ba7500] text-[18px]">warning</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-[#9e6200] font-mono">{records.filter(r => r.riskVerdict === 'REVIEW').length}</span>
            <span className="text-xs text-[#414753] font-medium">
              {records.length > 0 ? `${Math.round((records.filter(r => r.riskVerdict === 'REVIEW').length / records.length) * 100)}%` : '—'}
            </span>
          </div>
        </div>

        <div
          onClick={() => setActiveFilter(activeFilter === 'HIGH RISK' ? null : 'HIGH RISK')}
          className="bg-[#ffffff] p-4 rounded-xl border border-[#efedf3] hover:border-[#ba1a1a] transition-all cursor-pointer shadow-2xs space-y-2"
        >
          <div className="flex items-center justify-between text-[#717785] text-xs font-medium">
            <span>{t('verdict.high_risk')}</span>
            <span className="material-symbols-outlined text-[#ba1a1a] text-[18px]">dangerous</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-2xl font-bold text-[#ba1a1a] font-mono">{records.filter(r => r.riskVerdict === 'HIGH RISK').length}</span>
            <span className="text-xs text-[#ba1a1a] bg-[#ffdad6] px-1.5 py-0.5 rounded-sm font-semibold">
              {records.length > 0 ? `${Math.round((records.filter(r => r.riskVerdict === 'HIGH RISK').length / records.length) * 100)}%` : '—'}
            </span>
          </div>
        </div>
      </div>

      {/* Charts — ADMIN ONLY */}
      {isAdmin && (
        <RiskDistributionVisualizer
          records={records}
          selectedFilter={activeFilter}
          onSelectFilter={setActiveFilter}
        />
      )}

      {/* Screening Records Table */}
      <div className="bg-[#ffffff] border border-[#efedf3] rounded-xl shadow-2xs overflow-hidden">
        <div className="p-4 border-b border-[#efedf3] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-[#fbfbfe]">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-bold text-[#1a1b1f] flex items-center gap-2">
                <span className="material-symbols-outlined text-[#0059b5] text-[18px]">receipt_long</span>
                {t('overview.recent_screenings')}
              </h2>
              {activeFilter && (
                <span className="px-2 py-0.5 bg-[#0059b5] text-white rounded text-[10px] font-mono font-bold flex items-center gap-1">
                  <span>Filter: {activeFilter}</span>
                  <button onClick={() => setActiveFilter(null)} className="hover:text-red-200 cursor-pointer">&times;</button>
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {activeFilter && (
              <button
                onClick={() => setActiveFilter(null)}
                className="text-xs text-[#ba1a1a] hover:underline font-semibold cursor-pointer"
              >
                Reset ({filteredRecords.length}/{records.length})
              </button>
            )}
            {(isOfficer || isAdmin) && (
              <button
                onClick={() => onNavigate('new-scan')}
                className="flex items-center gap-1.5 bg-[#0059b5] hover:bg-[#00458f] text-white text-xs font-medium px-3 py-1.5 rounded-md transition-colors shadow-2xs cursor-pointer"
              >
                <span className="material-symbols-outlined text-[16px]">add_circle</span>
                <span>{t('overview.new_scan')}</span>
              </button>
            )}
          </div>
        </div>

        {filteredRecords.length === 0 ? (
          <div className="p-8 text-center">
            <span className="material-symbols-outlined text-[48px] text-[#d4d0dc]">inbox</span>
            <p className="text-sm text-[#717785] mt-3">{t('empty.no_scans')}</p>
          </div>
        ) : (
          <>
            {/* Desktop Table */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="border-b border-[#efedf3] bg-[#f4f3f8] text-[#414753] font-semibold text-[11px]">
                    <th className="py-2.5 px-4">{t('table.scan_id')}</th>
                    <th className="py-2.5 px-3">{t('table.doc_type')}</th>
                    <th className="py-2.5 px-3">{t('table.presenter')}</th>
                    <th className="py-2.5 px-3">{t('table.risk_score')}</th>
                    {!isOfficer && <th className="py-2.5 px-3">{t('table.mrz_check')}</th>}
                    <th className="py-2.5 px-3">{t('table.finding')}</th>
                    {!isOfficer && <th className="py-2.5 px-3">{t('table.sync')}</th>}
                    <th className="py-2.5 px-3">{t('table.time')}</th>
                    <th className="py-2.5 px-4 text-right">{t('table.action')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#efedf3]">
                  {filteredRecords.map((r) => {
                    const isHighRisk = r.riskVerdict === 'HIGH RISK';
                    const isReview = r.riskVerdict === 'REVIEW';
                    const isSynced = r.syncStatus === 'SYNCED' || !r.syncStatus;
                    return (
                      <tr
                        key={r.id}
                        onClick={() => { onSelectRecord(r); onNavigate('screening-report'); }}
                        className="hover:bg-[#f4f3f8]/70 transition-colors cursor-pointer group"
                      >
                        <td className="py-3 px-4 font-mono font-semibold text-[#0059b5] group-hover:underline">{r.id}</td>
                        <td className="py-3 px-3">
                          <span className="px-2 py-0.5 bg-[#efedf3] text-[#1a1b1f] rounded text-[11px] font-medium">{r.docCode}</span>
                        </td>
                        <td className="py-3 px-3">
                          <div className="font-medium text-[#1a1b1f]">{r.presenterName}</div>
                          <div className="text-[10px] text-[#717785] font-mono">{r.countryName} ({r.countryCode})</div>
                        </td>
                        <td className="py-3 px-3">
                          <span className={`font-mono font-bold px-2 py-0.5 rounded text-[11px] ${
                            isHighRisk ? 'bg-[#ffdad6] text-[#ba1a1a]' : isReview ? 'bg-[#ffe4af] text-[#7c4d00]' : 'bg-[#f1ffec] text-[#006a26]'
                          }`}>
                            {r.riskScore.toString().padStart(2, '0')} &middot; {r.riskVerdict}
                          </span>
                        </td>
                        {!isOfficer && (
                          <td className="py-3 px-3">
                            <span className={`text-[11px] font-mono font-semibold px-2 py-0.5 rounded ${
                              r.checksumStatus === 'PASS' ? 'bg-[#f1ffec] text-[#006a26]' : r.checksumStatus === 'FAIL' ? 'bg-[#ffdad6] text-[#ba1a1a]' : 'bg-[#efedf3] text-[#717785]'
                            }`}>
                              {r.checksumStatus}
                            </span>
                          </td>
                        )}
                        <td className="py-3 px-3 text-[#414753] max-w-xs truncate">{r.findings}</td>
                        {!isOfficer && (
                          <td className="py-3 px-3">
                            <span className={`inline-flex items-center gap-1 text-[10px] font-mono px-2 py-0.5 rounded font-semibold ${
                              isSynced ? 'bg-[#ecfdf5] text-[#047857]' : 'bg-[#fffbeb] text-[#b45309]'
                            }`}>
                              <span className={`w-1.5 h-1.5 rounded-full ${isSynced ? 'bg-[#10b981]' : 'bg-[#f59e0b] animate-pulse'}`}></span>
                              <span>{isSynced ? 'SYNCED' : 'OUTBOX'}</span>
                            </span>
                          </td>
                        )}
                        <td className="py-3 px-3 text-[#717785] text-[11px]">{r.timestamp}</td>
                        <td className="py-3 px-4 text-right">
                          <button
                            onClick={(e) => { e.stopPropagation(); onSelectRecord(r); onNavigate('screening-report'); }}
                            className="text-xs font-semibold text-[#0059b5] hover:text-[#00458f] bg-[#d7e2ff]/50 hover:bg-[#d7e2ff] px-2.5 py-1 rounded transition-colors"
                          >
                            {t('table.view')}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Mobile Cards */}
            <div className="md:hidden divide-y divide-[#efedf3]">
              {filteredRecords.map((r) => {
                const isHighRisk = r.riskVerdict === 'HIGH RISK';
                const isReview = r.riskVerdict === 'REVIEW';
                return (
                  <div
                    key={r.id}
                    onClick={() => { onSelectRecord(r); onNavigate('screening-report'); }}
                    className="p-3.5 hover:bg-[#f8fafc] transition-colors space-y-2 cursor-pointer"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="font-mono font-bold text-xs text-[#0059b5]">{r.id}</span>
                        <span className="px-1.5 py-0.5 bg-[#efedf3] text-[#1a1b1f] rounded text-[10px] font-medium">{r.docCode}</span>
                      </div>
                      <span className={`font-mono font-bold px-2 py-0.5 rounded text-[10px] ${
                        isHighRisk ? 'bg-[#ffdad6] text-[#ba1a1a]' : isReview ? 'bg-[#ffe4af] text-[#7c4d00]' : 'bg-[#f1ffec] text-[#006a26]'
                      }`}>
                        {r.riskScore.toString().padStart(2, '0')} &middot; {r.riskVerdict}
                      </span>
                    </div>
                    <div>
                      <div className="font-semibold text-xs text-[#1a1b1f]">{r.presenterName}</div>
                      <div className="text-[10px] text-[#717785] font-mono">{r.countryName} ({r.countryCode})</div>
                    </div>
                    <p className="text-[11px] text-[#414753] line-clamp-2">{r.findings}</p>
                    <div className="flex items-center justify-between pt-1 text-[10px] text-[#717785]">
                      <span>{r.timestamp}</span>
                      <span className="text-[#0059b5] font-semibold flex items-center gap-1">
                        <span>{t('table.view')}</span>
                        <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>

    </div>
  );
};

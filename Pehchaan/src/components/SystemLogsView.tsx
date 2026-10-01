import React, { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useI18n } from '../contexts/I18nContext';

interface SystemLog {
  id: number;
  timestamp: string;
  actor: string;
  role: string;
  checkpoint: string;
  event: string;
  status: string;
  reference_id?: string;
}

export const SystemLogsView: React.FC = () => {
  const { token } = useAuth();
  const { t } = useI18n();
  const [logs, setLogs] = useState<SystemLog[]>([]);
  const [search, setSearch] = useState('');
  const [eventFilter, setEventFilter] = useState('');
  const [loading, setLoading] = useState(true);

  const fetchLogs = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      if (eventFilter) params.set('event', eventFilter);
      const res = await fetch(`/api/system-logs?${params}`, {
        headers: { 'Authorization': `Bearer ${token}` },
      });
      if (res.ok) setLogs(await res.json());
    } catch {}
    setLoading(false);
  }, [token, search, eventFilter]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  const eventTypes = ['login', 'logout', 'screening_started', 'screening_completed',
    'authentication_failure', 'configuration_change', 'system_error', 'seed_users_created'];

  const statusColor = (s: string) => {
    if (s === 'success') return 'bg-[#f1ffec] text-[#006a26]';
    if (s === 'failed' || s === 'error') return 'bg-[#ffdad6] text-[#ba1a1a]';
    return 'bg-[#efedf3] text-[#717785]';
  };

  return (
    <div className="p-6 space-y-6 max-w-[1720px] mx-auto">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-[#efedf3]">
        <div>
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 text-[10px] font-bold font-mono uppercase bg-[#fce4ec] text-[#880e4f] rounded-sm">
              ADMIN ONLY
            </span>
          </div>
          <h1 className="text-xl font-bold text-[#1a1b1f] mt-1">{t('logs.title')}</h1>
          <p className="text-xs text-[#414753] mt-0.5">{t('logs.subtitle')}</p>
        </div>
        <button
          onClick={fetchLogs}
          className="text-xs font-semibold text-[#0059b5] hover:underline flex items-center gap-1 cursor-pointer"
        >
          <span className="material-symbols-outlined text-[16px]">refresh</span>
          <span>Refresh</span>
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <span className="material-symbols-outlined absolute left-3 top-2 text-[16px] text-[#717785]">search</span>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('logs.search')}
            className="w-full text-xs pl-9 pr-3 py-2 bg-[#f4f3f8] border border-[#efedf3] rounded-lg focus:outline-none focus:border-[#0059b5]"
          />
        </div>
        <select
          value={eventFilter}
          onChange={(e) => setEventFilter(e.target.value)}
          className="text-xs p-2 bg-[#f4f3f8] border border-[#efedf3] rounded-lg focus:outline-none focus:border-[#0059b5]"
        >
          <option value="">{t('logs.filter_event')}: All</option>
          {eventTypes.map(e => <option key={e} value={e}>{e}</option>)}
        </select>
      </div>

      <div className="bg-[#ffffff] border border-[#efedf3] rounded-xl shadow-2xs overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-[#717785] text-sm">Loading...</div>
        ) : logs.length === 0 ? (
          <div className="p-8 text-center">
            <span className="material-symbols-outlined text-[48px] text-[#d4d0dc]">event_note</span>
            <p className="text-sm text-[#717785] mt-3">{t('logs.no_logs')}</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[#efedf3] bg-[#f4f3f8] text-[#414753] font-semibold text-[11px]">
                  <th className="py-2.5 px-4">{t('logs.timestamp')}</th>
                  <th className="py-2.5 px-3">{t('logs.actor')}</th>
                  <th className="py-2.5 px-3">{t('logs.role')}</th>
                  <th className="py-2.5 px-3">{t('logs.checkpoint')}</th>
                  <th className="py-2.5 px-3">{t('logs.event')}</th>
                  <th className="py-2.5 px-3">{t('logs.status')}</th>
                  <th className="py-2.5 px-4">{t('logs.reference')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#efedf3]">
                {logs.map((log) => (
                  <tr key={log.id} className="hover:bg-[#f4f3f8]/70">
                    <td className="py-2.5 px-4 font-mono text-[#717785]">
                      {log.timestamp ? new Date(log.timestamp).toLocaleString() : '—'}
                    </td>
                    <td className="py-2.5 px-3 text-[#1a1b1f] font-medium">{log.actor}</td>
                    <td className="py-2.5 px-3">
                      <span className="px-2 py-0.5 bg-[#efedf3] rounded text-[10px] font-mono">{log.role}</span>
                    </td>
                    <td className="py-2.5 px-3 text-[#717785]">{log.checkpoint || '—'}</td>
                    <td className="py-2.5 px-3 font-medium text-[#1a1b1f]">{log.event}</td>
                    <td className="py-2.5 px-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${statusColor(log.status)}`}>
                        {log.status}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 font-mono text-[#717785]">{log.reference_id || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

import React, { useState, useEffect } from 'react';
import {
  checkNeonStatus,
  getOfflineQueue,
  syncOfflineQueueToNeon,
  isLowBandwidthMode,
  setLowBandwidthMode,
} from '../services/neonSyncService';
import { NeonTelemetryStatus } from '../types';
import { useAuth } from '../contexts/AuthContext';
import { PWAInstallButton } from './PWAInstallButton';

interface RemoteLocationSyncBarProps {
  onSyncCompleted?: () => void;
}

export const RemoteLocationSyncBar: React.FC<RemoteLocationSyncBarProps> = ({ onSyncCompleted }) => {
  const { token, checkpoint } = useAuth();
  const [isOnline, setIsOnline] = useState<boolean>(typeof navigator !== 'undefined' ? navigator.onLine : true);
  const [lowBw, setLowBw] = useState<boolean>(isLowBandwidthMode());
  const [queueCount, setQueueCount] = useState<number>(0);
  const [isSyncing, setIsSyncing] = useState<boolean>(false);
  const [syncFeedback, setSyncFeedback] = useState<string | null>(null);
  const [neonStatus, setNeonStatus] = useState<NeonTelemetryStatus | null>(null);
  const [isExpanded, setIsExpanded] = useState<boolean>(false);

  const refreshState = async () => {
    const local = getOfflineQueue().length;
    setQueueCount(local);
    try {
      const status = await checkNeonStatus(token || undefined);
      setNeonStatus(status);
      // records the gateway is holding on disk until the database is reachable again
      setQueueCount(local + (status.pendingOutbox || 0));
    } catch {}
  };

  useEffect(() => {
    const handleOnline = () => {
      setIsOnline(true);
      triggerSync();
    };
    const handleOffline = () => setIsOnline(false);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    refreshState();
    const interval = setInterval(refreshState, 12000);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      clearInterval(interval);
    };
  }, []);

  const triggerSync = async () => {
    if (!token) return;
    setIsSyncing(true);
    setSyncFeedback(null);
    try {
      const res = await syncOfflineQueueToNeon(token);
      if (res.synced > 0) {
        setSyncFeedback(`Successfully transmitted ${res.synced} record(s) to Neon PostgreSQL.`);
        if (onSyncCompleted) onSyncCompleted();
      } else if (res.remaining > 0 && res.error) {
        setSyncFeedback(`Sync pending: ${res.error}`);
      } else {
        setSyncFeedback('All local outbox records are up to date in Neon database.');
      }
      refreshState();
    } catch (err: any) {
      setSyncFeedback(`Sync attempt failed: ${err?.message || 'Remote network timeout'}`);
    } finally {
      setIsSyncing(false);
      setTimeout(() => setSyncFeedback(null), 6000);
    }
  };

  const handleLowBwToggle = (e: React.ChangeEvent<HTMLInputElement>) => {
    const checked = e.target.checked;
    setLowBw(checked);
    setLowBandwidthMode(checked);
  };

  return (
    <aside aria-label="Remote synchronization and Neon database status" className="w-full bg-[#0e131d] border-b border-[#1b2333] px-3 sm:px-6 py-2.5 text-xs text-[#94a3b8] transition-all">
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          <div
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold tracking-wide border ${
              isOnline
                ? neonStatus?.connected
                  ? 'bg-[#052e16]/80 text-[#4ade80] border-[#166534]'
                  : 'bg-[#1e1b4b]/80 text-[#a5b4fc] border-[#3730a3]'
                : 'bg-[#450a0a]/80 text-[#f87171] border-[#991b1b]'
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                isOnline
                  ? neonStatus?.connected ? 'bg-[#22c55e] animate-pulse' : 'bg-[#818cf8]'
                  : 'bg-[#ef4444]'
              }`}
            />
            <span>
              {isOnline
                ? neonStatus?.connected ? 'NEON DB: ONLINE' : 'NEON: SYNC READY'
                : 'OFFLINE / AIR-GAPPED'}
            </span>
          </div>

          {checkpoint && (
            <div className="flex items-center gap-1.5 bg-[#141b27] border border-[#222e44] rounded-lg px-2 py-1">
              <span className="material-symbols-outlined text-[14px] text-[#60a5fa]">location_on</span>
              <span className="text-[11px] font-medium text-[#cbd5e1]">{checkpoint.name}</span>
            </div>
          )}

          <label className="flex items-center gap-1.5 cursor-pointer bg-[#141b27] border border-[#222e44] hover:border-[#2e3f5d] px-2 py-1 rounded-lg transition-colors select-none">
            <input
              type="checkbox"
              checked={lowBw}
              onChange={handleLowBwToggle}
              className="w-3.5 h-3.5 rounded bg-[#1e293b] border-gray-600 text-blue-600 focus:ring-0 cursor-pointer"
            />
            <span className="text-[11px] font-medium text-[#cbd5e1] flex items-center gap-1">
              <span className="material-symbols-outlined text-[13px] text-[#fbbf24]">signal_cellular_alt_1_bar</span>
              Low-Bandwidth Mode
            </span>
          </label>
        </div>

        <div className="flex items-center gap-2">
          <div
            className={`flex items-center gap-1 px-2 py-1 rounded-lg border text-[11px] font-mono ${
              queueCount > 0
                ? 'bg-[#422006] text-[#fde047] border-[#854d0e]'
                : 'bg-[#141b27] text-[#94a3b8] border-[#222e44]'
            }`}
          >
            <span className="material-symbols-outlined text-[14px]">
              {queueCount > 0 ? 'outbox' : 'cloud_done'}
            </span>
            <span>{queueCount > 0 ? `${queueCount} Queued` : 'All Synced'}</span>
          </div>

          <button
            onClick={triggerSync}
            disabled={isSyncing}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-lg font-semibold text-[11px] transition-all cursor-pointer shadow-xs ${
              isSyncing
                ? 'bg-[#1e293b] text-gray-400 cursor-not-allowed'
                : queueCount > 0
                ? 'bg-[#2563eb] hover:bg-[#1d4ed8] text-white'
                : 'bg-[#182236] hover:bg-[#202d47] text-[#93c5fd] border border-[#2b3a55]'
            }`}
          >
            <span className={`material-symbols-outlined text-[14px] ${isSyncing ? 'animate-spin' : ''}`}>sync</span>
            <span>{isSyncing ? 'Transmitting...' : 'Sync to Neon'}</span>
          </button>

          <button
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1 rounded-lg bg-[#141b27] border border-[#222e44] hover:bg-[#1c2637] text-[#94a3b8] hover:text-white transition-colors cursor-pointer"
          >
            <span className="material-symbols-outlined text-[16px]">
              {isExpanded ? 'expand_less' : 'database'}
            </span>
          </button>

          <PWAInstallButton compact={true} />
        </div>
      </div>

      {syncFeedback && (
        <div className="mt-2 text-[11px] px-3 py-1.5 rounded bg-[#13233c] border border-[#1e3a5f] text-[#60a5fa] flex items-center justify-between animate-fadeIn">
          <div className="flex items-center gap-1.5">
            <span className="material-symbols-outlined text-[14px]">info</span>
            <span>{syncFeedback}</span>
          </div>
          <button onClick={() => setSyncFeedback(null)} className="text-gray-400 hover:text-white">
            <span className="material-symbols-outlined text-[12px]">close</span>
          </button>
        </div>
      )}

      {isExpanded && (
        <div className="mt-2.5 p-3.5 rounded-xl bg-[#080c13] border border-[#1e293b] text-[#cbd5e1] animate-fadeIn">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#1b2333] pb-2.5 mb-2.5">
            <div className="flex items-center gap-2">
              <span className="material-symbols-outlined text-[18px] text-[#22c55e]">storage</span>
              <div>
                <h4 className="font-bold text-white text-xs">Neon Serverless PostgreSQL Database</h4>
                <p className="text-[10px] text-[#94a3b8]">Centralized database for all checkpoint data.</p>
              </div>
            </div>
            <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-[#1e293b] text-[#93c5fd] border border-[#334155]">
              {neonStatus?.connected ? 'SSL: ENCRYPTED' : 'STORE-AND-FORWARD BUFFER'}
            </span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
            <div className="bg-[#0f172a] p-2 rounded-lg border border-[#1e293b]">
              <div className="text-[10px] text-[#64748b] uppercase tracking-wider font-mono">Database Status</div>
              <div className="font-mono font-semibold text-[#4ade80]">
                {neonStatus?.connected ? 'Live Online' : 'Outbox Store & Fwd'}
              </div>
            </div>
            <div className="bg-[#0f172a] p-2 rounded-lg border border-[#1e293b]">
              <div className="text-[10px] text-[#64748b] uppercase tracking-wider font-mono">Total Scans in DB</div>
              <div className="font-mono font-semibold text-[#fbbf24]">
                {neonStatus?.totalScans ?? 0}
              </div>
            </div>
            <div className="bg-[#0f172a] p-2 rounded-lg border border-[#1e293b]">
              <div className="text-[10px] text-[#64748b] uppercase tracking-wider font-mono">Latency</div>
              <div className="font-mono font-semibold text-white">
                {neonStatus?.latencyMs ?? '—'}ms
              </div>
            </div>
            <div className="bg-[#0f172a] p-2 rounded-lg border border-[#1e293b]">
              <div className="text-[10px] text-[#64748b] uppercase tracking-wider font-mono">Remote Mode</div>
              <div className="font-mono font-semibold text-[#60a5fa]">
                {lowBw ? '90% Compressed' : 'Full Telemetry'}
              </div>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
};

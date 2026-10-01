import React, { useState, useEffect } from 'react';
import { ScreenType, ScreeningRecord, NeonTelemetryStatus } from '../types';
import { checkNeonStatus } from '../services/neonSyncService';
import { useAuth } from '../contexts/AuthContext';

interface ChainStatus {
  valid: boolean;
  totalBlocks: number;
  latestBlock: number;
  genesisHash: string;
  latestHash: string;
  brokenAt?: number;
  error?: string;
}

interface RefDatasetStats {
  total: number;
  seeded: number;
  pending: number;
  categories: Record<string, number>;
}

interface AdminPortalViewProps {
  onNavigate: (screen: ScreenType) => void;
  records: ScreeningRecord[];
}

export const AdminPortalView: React.FC<AdminPortalViewProps> = ({ onNavigate, records }) => {
  const { token } = useAuth();
  const [neonStatus, setNeonStatus] = useState<NeonTelemetryStatus | null>(null);
  const [chainStatus, setChainStatus] = useState<ChainStatus | null>(null);
  const [chainLoading, setChainLoading] = useState(false);
  const [chainVerifyResult, setChainVerifyResult] = useState<ChainStatus | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [refStats, setRefStats] = useState<RefDatasetStats | null>(null);
  const [seeding, setSeeding] = useState(false);
  const [seedResult, setSeedResult] = useState<string | null>(null);

  useEffect(() => {
    checkNeonStatus(token || undefined).then(setNeonStatus);
    if (token) {
      fetch('/api/chain/status', { headers: { Authorization: `Bearer ${token}` } })
        .then(r => r.json()).then(setChainStatus).catch(() => {});
      fetch('/api/reference/stats', { headers: { Authorization: `Bearer ${token}` } })
        .then(r => r.ok ? r.json() : null).then(setRefStats).catch(() => {});
    }
  }, [token]);

  const handleSeedDatasets = async () => {
    if (!token) return;
    setSeeding(true);
    setSeedResult(null);
    try {
      const res = await fetch('/api/reference/seed', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (res.ok) {
        setSeedResult(`${data.count} datasets seeded successfully`);
        fetch('/api/reference/stats', { headers: { Authorization: `Bearer ${token}` } })
          .then(r => r.ok ? r.json() : null).then(setRefStats).catch(() => {});
      } else {
        setSeedResult(data.error || 'Seed failed');
      }
    } catch {
      setSeedResult('Network error');
    }
    setSeeding(false);
  };

  const handleVerifyChain = async () => {
    if (!token) return;
    setVerifying(true);
    setChainVerifyResult(null);
    try {
      const res = await fetch('/api/chain/verify', { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      setChainVerifyResult(data);
      setChainStatus(data);
    } catch {
      setChainVerifyResult({ valid: false, totalBlocks: 0, latestBlock: 0, genesisHash: '', latestHash: '', error: 'Verification request failed' });
    } finally {
      setVerifying(false);
    }
  };

  const clearCount = records.filter((r) => r.riskVerdict === 'CLEAR').length;
  const reviewCount = records.filter((r) => r.riskVerdict === 'REVIEW').length;
  const highRiskCount = records.filter((r) => r.riskVerdict === 'HIGH RISK').length;
  const uniqueOfficers = new Set(records.map((r) => r.officerUid)).size;

  return (
    <div className="p-6 space-y-6 max-w-[1720px] mx-auto">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pb-4 border-b border-[#efedf3]">
        <div>
          <div className="flex items-center gap-2">
            <span className="px-2 py-0.5 text-[10px] font-bold font-mono uppercase bg-[#fce4ec] text-[#880e4f] rounded-sm">
              ADMIN CONTROL CENTER
            </span>
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[#f1ffec] text-[#006a26] text-xs font-mono font-semibold">
              <span className="w-1.5 h-1.5 rounded-full bg-[#008633]"></span>
              Authenticated
            </span>
          </div>
          <h1 className="text-xl font-bold text-[#1a1b1f] mt-1">Administrative Control Center</h1>
          <p className="text-xs text-[#414753] mt-0.5">
            System oversight, officer management, and database administration.
          </p>
        </div>

        <button
          onClick={() => onNavigate('overview')}
          className="text-xs font-semibold text-[#0059b5] hover:underline flex items-center gap-1 cursor-pointer"
        >
          <span className="material-symbols-outlined text-[16px]">arrow_back</span>
          <span>Back to Overview</span>
        </button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-[#ffffff] p-4 rounded-xl border border-[#efedf3] shadow-2xs space-y-1">
          <div className="text-[10px] font-semibold text-[#717785] uppercase">Active Officers</div>
          <div className="text-2xl font-bold font-mono text-[#1a1b1f]">{uniqueOfficers}</div>
          <p className="text-[11px] text-[#006a26] font-medium">On duty</p>
        </div>
        <div className="bg-[#ffffff] p-4 rounded-xl border border-[#efedf3] shadow-2xs space-y-1">
          <div className="text-[10px] font-semibold text-[#717785] uppercase">Total Screenings</div>
          <div className="text-2xl font-bold font-mono text-[#0059b5]">{records.length}</div>
          <p className="text-[11px] text-[#717785]">All stations</p>
        </div>
        <div className="bg-[#ffffff] p-4 rounded-xl border border-[#efedf3] shadow-2xs space-y-1">
          <div className="text-[10px] font-semibold text-[#717785] uppercase">High Risk Flags</div>
          <div className="text-2xl font-bold font-mono text-[#ba1a1a]">{highRiskCount}</div>
          <p className="text-[11px] text-[#717785]">Requires attention</p>
        </div>
        <div className="bg-[#ffffff] p-4 rounded-xl border border-[#efedf3] shadow-2xs space-y-1">
          <div className="text-[10px] font-semibold text-[#717785] uppercase">Database</div>
          <div className="text-lg font-bold font-mono text-[#1a1b1f]">
            {neonStatus?.connected ? 'ONLINE' : 'OFFLINE'}
          </div>
          <p className="text-[11px] text-[#717785]">{neonStatus?.mode || 'Checking...'}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <button
          onClick={() => onNavigate('officer-status')}
          className="bg-[#ffffff] border border-[#efedf3] rounded-xl p-5 shadow-2xs text-left hover:border-[#880e4f] hover:shadow-md transition-all cursor-pointer group"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="w-10 h-10 rounded-lg bg-[#fce4ec] flex items-center justify-center">
              <span className="material-symbols-outlined text-[22px] text-[#880e4f]">groups</span>
            </span>
            <div>
              <div className="text-sm font-bold text-[#1a1b1f] group-hover:text-[#880e4f] transition-colors">
                Officer Status
              </div>
              <div className="text-[11px] text-[#717785]">Track record & performance</div>
            </div>
          </div>
          <p className="text-xs text-[#414753]">
            View all officer activity, screening counts, verdict breakdown, and lane assignments.
          </p>
          <div className="mt-3 flex items-center gap-2 text-[11px] text-[#880e4f] font-semibold">
            <span>{uniqueOfficers} officer{uniqueOfficers !== 1 ? 's' : ''} active</span>
            <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
          </div>
        </button>

        <button
          onClick={() => onNavigate('audit-trail')}
          className="bg-[#ffffff] border border-[#efedf3] rounded-xl p-5 shadow-2xs text-left hover:border-[#0059b5] hover:shadow-md transition-all cursor-pointer group"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="w-10 h-10 rounded-lg bg-[#d7e2ff] flex items-center justify-center">
              <span className="material-symbols-outlined text-[22px] text-[#0059b5]">history_edu</span>
            </span>
            <div>
              <div className="text-sm font-bold text-[#1a1b1f] group-hover:text-[#0059b5] transition-colors">
                Audit Trail
              </div>
              <div className="text-[11px] text-[#717785]">Immutable screening ledger</div>
            </div>
          </div>
          <p className="text-xs text-[#414753]">
            Tamper-proof chronological log of all credential scans with SHA-256 chain verification.
          </p>
          <div className="mt-3 flex items-center gap-2 text-[11px] text-[#0059b5] font-semibold">
            <span>{records.length} blocks recorded</span>
            <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
          </div>
        </button>

        <button
          onClick={() => onNavigate('system-health-and-docs')}
          className="bg-[#ffffff] border border-[#efedf3] rounded-xl p-5 shadow-2xs text-left hover:border-[#006a26] hover:shadow-md transition-all cursor-pointer group"
        >
          <div className="flex items-center gap-3 mb-3">
            <span className="w-10 h-10 rounded-lg bg-[#f1ffec] flex items-center justify-center">
              <span className="material-symbols-outlined text-[22px] text-[#006a26]">terminal</span>
            </span>
            <div>
              <div className="text-sm font-bold text-[#1a1b1f] group-hover:text-[#006a26] transition-colors">
                System Health
              </div>
              <div className="text-[11px] text-[#717785]">Engine & API status</div>
            </div>
          </div>
          <p className="text-xs text-[#414753]">
            Monitor AI engine performance, API endpoints, and system diagnostics.
          </p>
          <div className="mt-3 flex items-center gap-2 text-[11px] text-[#006a26] font-semibold">
            <span>All engines active</span>
            <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
          </div>
        </button>
      </div>

      <div className="bg-[#ffffff] border border-[#efedf3] rounded-xl p-5 shadow-2xs">
        <div className="flex items-center gap-2 mb-4">
          <span className="material-symbols-outlined text-[20px] text-[#0059b5]">database</span>
          <h3 className="text-sm font-bold text-[#1a1b1f]">Database Connection</h3>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
          <div>
            <div className="text-[#717785] font-semibold mb-0.5">Provider</div>
            <div className="text-[#1a1b1f]">{neonStatus?.provider || 'Neon PostgreSQL'}</div>
          </div>
          <div>
            <div className="text-[#717785] font-semibold mb-0.5">Status</div>
            <div className={neonStatus?.connected ? 'text-[#006a26] font-semibold' : 'text-[#b45309]'}>
              {neonStatus?.connected ? 'Connected' : 'Store-and-Forward Mode'}
            </div>
          </div>
          <div>
            <div className="text-[#717785] font-semibold mb-0.5">Total Scans in DB</div>
            <div className="text-[#1a1b1f] font-mono">{neonStatus?.totalScans ?? '—'}</div>
          </div>
          <div>
            <div className="text-[#717785] font-semibold mb-0.5">Latency</div>
            <div className="text-[#1a1b1f] font-mono">{neonStatus?.latencyMs ?? '—'}ms</div>
          </div>
        </div>
      </div>

      {/* Blockchain Hash Chain */}
      <div className="bg-[#ffffff] border border-[#efedf3] rounded-xl p-5 shadow-2xs">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <span className="w-8 h-8 rounded-lg bg-[#ede7f6] flex items-center justify-center">
              <span className="material-symbols-outlined text-[18px] text-[#6a1b9a]">link</span>
            </span>
            <div>
              <h3 className="text-sm font-bold text-[#1a1b1f]">SHA-256 Hash Chain</h3>
              <p className="text-[10px] text-[#717785]">Tamper-evident blockchain audit trail</p>
            </div>
          </div>
          <button
            onClick={handleVerifyChain}
            disabled={verifying}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-[#ede7f6] text-[#6a1b9a] hover:bg-[#d1c4e9] transition-colors cursor-pointer disabled:opacity-50"
          >
            <span className={`material-symbols-outlined text-[14px] ${verifying ? 'animate-spin' : ''}`}>
              {verifying ? 'sync' : 'verified_user'}
            </span>
            <span>{verifying ? 'Verifying...' : 'Verify Chain Integrity'}</span>
          </button>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <div className="bg-[#fafafa] p-3 rounded-lg border border-[#efedf3]">
            <div className="text-[10px] font-semibold text-[#717785] uppercase tracking-wider">Chain Status</div>
            <div className={`text-sm font-bold font-mono mt-1 flex items-center gap-1.5 ${chainStatus?.valid !== false ? 'text-[#006a26]' : 'text-[#ba1a1a]'}`}>
              <span className={`w-2 h-2 rounded-full ${chainStatus?.valid !== false ? 'bg-[#22c55e] animate-pulse' : 'bg-[#ef4444]'}`}></span>
              {chainStatus ? (chainStatus.valid ? 'INTACT' : 'BROKEN') : 'CHECKING...'}
            </div>
          </div>
          <div className="bg-[#fafafa] p-3 rounded-lg border border-[#efedf3]">
            <div className="text-[10px] font-semibold text-[#717785] uppercase tracking-wider">Total Blocks</div>
            <div className="text-lg font-bold font-mono text-[#1a1b1f] mt-1">{chainStatus?.totalBlocks ?? '—'}</div>
          </div>
          <div className="bg-[#fafafa] p-3 rounded-lg border border-[#efedf3]">
            <div className="text-[10px] font-semibold text-[#717785] uppercase tracking-wider">Latest Block</div>
            <div className="text-lg font-bold font-mono text-[#6a1b9a] mt-1">#{chainStatus?.latestBlock ?? '—'}</div>
          </div>
          <div className="bg-[#fafafa] p-3 rounded-lg border border-[#efedf3]">
            <div className="text-[10px] font-semibold text-[#717785] uppercase tracking-wider">Algorithm</div>
            <div className="text-sm font-bold font-mono text-[#1a1b1f] mt-1">SHA-256</div>
          </div>
        </div>

        <div className="space-y-2 text-xs">
          <div className="flex items-center gap-2 bg-[#f5f5f5] rounded-lg px-3 py-2 font-mono">
            <span className="text-[10px] text-[#717785] uppercase font-semibold min-w-[80px]">Genesis</span>
            <span className="text-[#1a1b1f] truncate">{chainStatus?.genesisHash || '—'}</span>
          </div>
          <div className="flex items-center gap-2 bg-[#f5f5f5] rounded-lg px-3 py-2 font-mono">
            <span className="text-[10px] text-[#717785] uppercase font-semibold min-w-[80px]">Latest</span>
            <span className="text-[#6a1b9a] truncate">{chainStatus?.latestHash || '—'}</span>
          </div>
        </div>

        {chainVerifyResult && (
          <div className={`mt-4 p-3 rounded-lg border text-xs ${chainVerifyResult.valid
            ? 'bg-[#f1ffec] border-[#c8e6c9] text-[#006a26]'
            : 'bg-[#fce4ec] border-[#f8bbd0] text-[#ba1a1a]'
          }`}>
            <div className="flex items-center gap-2 font-semibold">
              <span className="material-symbols-outlined text-[16px]">
                {chainVerifyResult.valid ? 'check_circle' : 'error'}
              </span>
              {chainVerifyResult.valid
                ? `Chain verified: ${chainVerifyResult.totalBlocks} block(s) validated — no tampering detected.`
                : `Chain integrity failure: ${chainVerifyResult.error}`
              }
            </div>
            {chainVerifyResult.valid && chainVerifyResult.totalBlocks > 0 && (
              <p className="mt-1 text-[11px] opacity-80">
                Every block's SHA-256 hash was recomputed from (prev_hash + scan_data) and matched the stored hash.
              </p>
            )}
          </div>
        )}
      </div>

      {/* Data Sources — data.gov.in Reference Datasets */}
      <div className="bg-[#ffffff] border border-[#efedf3] rounded-xl p-5 shadow-2xs">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <span className="w-8 h-8 rounded-lg bg-[#e3f2fd] flex items-center justify-center">
              <span className="material-symbols-outlined text-[18px] text-[#1565c0]">dataset</span>
            </span>
            <div>
              <h3 className="text-sm font-bold text-[#1a1b1f]">Government Data Sources</h3>
              <p className="text-[10px] text-[#717785]">45 datasets from data.gov.in powering screening intelligence</p>
            </div>
          </div>
          <button
            onClick={handleSeedDatasets}
            disabled={seeding}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-[#e3f2fd] text-[#1565c0] hover:bg-[#bbdefb] transition-colors cursor-pointer disabled:opacity-50"
          >
            <span className={`material-symbols-outlined text-[14px] ${seeding ? 'animate-spin' : ''}`}>
              {seeding ? 'sync' : 'cloud_download'}
            </span>
            <span>{seeding ? 'Seeding...' : 'Seed Dataset Catalog'}</span>
          </button>
        </div>

        {seedResult && (
          <div className={`mb-4 p-2.5 rounded-lg text-xs font-medium ${
            seedResult.includes('success') ? 'bg-[#f1ffec] text-[#006a26] border border-[#c8e6c9]' : 'bg-[#fce4ec] text-[#ba1a1a] border border-[#f8bbd0]'
          }`}>
            <span className="material-symbols-outlined text-[14px] align-middle mr-1">
              {seedResult.includes('success') ? 'check_circle' : 'error'}
            </span>
            {seedResult}
          </div>
        )}

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
          <div className="bg-[#fafafa] p-3 rounded-lg border border-[#efedf3]">
            <div className="text-[10px] font-semibold text-[#717785] uppercase tracking-wider">Total Datasets</div>
            <div className="text-lg font-bold font-mono text-[#1565c0] mt-1">{refStats?.total ?? 45}</div>
          </div>
          <div className="bg-[#fafafa] p-3 rounded-lg border border-[#efedf3]">
            <div className="text-[10px] font-semibold text-[#717785] uppercase tracking-wider">Loaded</div>
            <div className="text-lg font-bold font-mono text-[#006a26] mt-1">{refStats?.seeded ?? '—'}</div>
          </div>
          <div className="bg-[#fafafa] p-3 rounded-lg border border-[#efedf3]">
            <div className="text-[10px] font-semibold text-[#717785] uppercase tracking-wider">Pending</div>
            <div className="text-lg font-bold font-mono text-[#b45309] mt-1">{refStats?.pending ?? '—'}</div>
          </div>
          <div className="bg-[#fafafa] p-3 rounded-lg border border-[#efedf3]">
            <div className="text-[10px] font-semibold text-[#717785] uppercase tracking-wider">Categories</div>
            <div className="text-lg font-bold font-mono text-[#1a1b1f] mt-1">{refStats?.categories ? Object.keys(refStats.categories).length : 7}</div>
          </div>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2">
          {[
            { key: 'passport', label: 'Passport', color: '#1565c0', bg: '#e3f2fd', count: 5 },
            { key: 'visa', label: 'Visa', color: '#7b1fa2', bg: '#f3e5f5', count: 7 },
            { key: 'immigration', label: 'Immigration', color: '#00695c', bg: '#e0f2f1', count: 8 },
            { key: 'aadhaar', label: 'Aadhaar', color: '#2e7d32', bg: '#e8f5e9', count: 7 },
            { key: 'border', label: 'Border', color: '#c62828', bg: '#fce4ec', count: 7 },
            { key: 'fraud', label: 'Fraud', color: '#e65100', bg: '#fff3e0', count: 5 },
            { key: 'crime', label: 'Crime/Ref', color: '#455a64', bg: '#eceff1', count: 6 },
          ].map(cat => (
            <div key={cat.key} className="flex items-center gap-2 p-2 rounded-lg border border-[#efedf3]" style={{ background: cat.bg }}>
              <div className="text-lg font-bold font-mono" style={{ color: cat.color }}>
                {refStats?.categories?.[cat.key] ?? cat.count}
              </div>
              <div className="text-[10px] font-semibold" style={{ color: cat.color }}>{cat.label}</div>
            </div>
          ))}
        </div>

        <div className="mt-4 p-3 bg-[#f5f5f5] rounded-lg text-[11px] text-[#717785] space-y-1">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-[14px]">info</span>
            <span className="font-semibold">Data Pipeline Status</span>
          </div>
          <p>Reference data feeds the validation engine (pincode verification, PSK codes, e-visa eligibility, visa plausibility), risk scoring (border threat levels, nationality baselines), and admin analytics.</p>
          <p className="font-mono text-[10px]">Source: data.gov.in · MEA · UIDAI · MHA · Min. of Tourism · Dept of Posts</p>
        </div>
      </div>

      {/* Security Controls */}
      <div className="bg-[#ffffff] border border-[#efedf3] rounded-xl p-5 shadow-2xs">
        <div className="flex items-center gap-2 mb-4">
          <span className="w-8 h-8 rounded-lg bg-[#fff3e0] flex items-center justify-center">
            <span className="material-symbols-outlined text-[18px] text-[#e65100]">shield</span>
          </span>
          <div>
            <h3 className="text-sm font-bold text-[#1a1b1f]">Cybersecurity Controls</h3>
            <p className="text-[10px] text-[#717785]">Active security measures protecting this system</p>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          <div className="flex items-start gap-3 p-3 bg-[#fafafa] rounded-lg border border-[#efedf3]">
            <span className="w-7 h-7 rounded-md bg-[#e8f5e9] flex items-center justify-center flex-shrink-0 mt-0.5">
              <span className="material-symbols-outlined text-[16px] text-[#2e7d32]">lock</span>
            </span>
            <div>
              <div className="text-xs font-semibold text-[#1a1b1f]">HMAC-SHA256 Audit Signatures</div>
              <p className="text-[10px] text-[#717785] mt-0.5">
                Every audit log entry is cryptographically signed with a server-side secret. Tampering is detectable.
              </p>
              <span className="inline-flex items-center gap-1 mt-1 text-[10px] font-semibold text-[#2e7d32]">
                <span className="w-1.5 h-1.5 rounded-full bg-[#4caf50]"></span> Active
              </span>
            </div>
          </div>

          <div className="flex items-start gap-3 p-3 bg-[#fafafa] rounded-lg border border-[#efedf3]">
            <span className="w-7 h-7 rounded-md bg-[#e3f2fd] flex items-center justify-center flex-shrink-0 mt-0.5">
              <span className="material-symbols-outlined text-[16px] text-[#1565c0]">speed</span>
            </span>
            <div>
              <div className="text-xs font-semibold text-[#1a1b1f]">Brute Force Protection</div>
              <p className="text-[10px] text-[#717785] mt-0.5">
                Login rate-limited to 5 attempts per 15 minutes per IP. Excess attempts return HTTP 429.
              </p>
              <span className="inline-flex items-center gap-1 mt-1 text-[10px] font-semibold text-[#1565c0]">
                <span className="w-1.5 h-1.5 rounded-full bg-[#2196f3]"></span> Enforced
              </span>
            </div>
          </div>

          <div className="flex items-start gap-3 p-3 bg-[#fafafa] rounded-lg border border-[#efedf3]">
            <span className="w-7 h-7 rounded-md bg-[#fce4ec] flex items-center justify-center flex-shrink-0 mt-0.5">
              <span className="material-symbols-outlined text-[16px] text-[#c62828]">fingerprint</span>
            </span>
            <div>
              <div className="text-xs font-semibold text-[#1a1b1f]">Session Fingerprinting</div>
              <p className="text-[10px] text-[#717785] mt-0.5">
                JWT tokens are bound to the originating device. Stolen tokens cannot be replayed from another browser.
              </p>
              <span className="inline-flex items-center gap-1 mt-1 text-[10px] font-semibold text-[#c62828]">
                <span className="w-1.5 h-1.5 rounded-full bg-[#ef5350]"></span> Bound
              </span>
            </div>
          </div>

          <div className="flex items-start gap-3 p-3 bg-[#fafafa] rounded-lg border border-[#efedf3]">
            <span className="w-7 h-7 rounded-md bg-[#f3e5f5] flex items-center justify-center flex-shrink-0 mt-0.5">
              <span className="material-symbols-outlined text-[16px] text-[#7b1fa2]">cleaning_services</span>
            </span>
            <div>
              <div className="text-xs font-semibold text-[#1a1b1f]">Input Sanitization</div>
              <p className="text-[10px] text-[#717785] mt-0.5">
                All scan data is sanitized before DB insertion — HTML tags stripped, field lengths enforced.
              </p>
              <span className="inline-flex items-center gap-1 mt-1 text-[10px] font-semibold text-[#7b1fa2]">
                <span className="w-1.5 h-1.5 rounded-full bg-[#ab47bc]"></span> Active
              </span>
            </div>
          </div>

          <div className="flex items-start gap-3 p-3 bg-[#fafafa] rounded-lg border border-[#efedf3]">
            <span className="w-7 h-7 rounded-md bg-[#e0f2f1] flex items-center justify-center flex-shrink-0 mt-0.5">
              <span className="material-symbols-outlined text-[16px] text-[#00695c]">policy</span>
            </span>
            <div>
              <div className="text-xs font-semibold text-[#1a1b1f]">CSP & Security Headers</div>
              <p className="text-[10px] text-[#717785] mt-0.5">
                Content-Security-Policy, HSTS, X-Frame-Options DENY, X-Content-Type-Options nosniff.
              </p>
              <span className="inline-flex items-center gap-1 mt-1 text-[10px] font-semibold text-[#00695c]">
                <span className="w-1.5 h-1.5 rounded-full bg-[#26a69a]"></span> Helmet.js
              </span>
            </div>
          </div>

          <div className="flex items-start gap-3 p-3 bg-[#fafafa] rounded-lg border border-[#efedf3]">
            <span className="w-7 h-7 rounded-md bg-[#fff8e1] flex items-center justify-center flex-shrink-0 mt-0.5">
              <span className="material-symbols-outlined text-[16px] text-[#f57f17]">admin_panel_settings</span>
            </span>
            <div>
              <div className="text-xs font-semibold text-[#1a1b1f]">Server-Side RBAC</div>
              <p className="text-[10px] text-[#717785] mt-0.5">
                Role-based access control enforced on every API endpoint. Unauthorized requests return 403.
              </p>
              <span className="inline-flex items-center gap-1 mt-1 text-[10px] font-semibold text-[#f57f17]">
                <span className="w-1.5 h-1.5 rounded-full bg-[#ffb300]"></span> Enforced
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-[#ffffff] border border-[#efedf3] rounded-xl p-5 shadow-2xs">
        <h3 className="text-sm font-bold text-[#1a1b1f] mb-3">Screening Summary</h3>
        <div className="flex items-center gap-4">
          <div className="flex-1">
            <div className="flex items-center gap-1.5 mb-1">
              <div className="flex-1 bg-[#efedf3] rounded-full h-3 overflow-hidden flex">
                {records.length > 0 && (
                  <>
                    <div
                      className="bg-[#22c55e] h-3"
                      style={{ width: `${(clearCount / records.length) * 100}%` }}
                    />
                    <div
                      className="bg-[#f59e0b] h-3"
                      style={{ width: `${(reviewCount / records.length) * 100}%` }}
                    />
                    <div
                      className="bg-[#ef4444] h-3"
                      style={{ width: `${(highRiskCount / records.length) * 100}%` }}
                    />
                  </>
                )}
              </div>
            </div>
            <div className="flex items-center gap-4 text-[11px] text-[#414753]">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-[#22c55e]"></span>
                Clear: {clearCount}
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-[#f59e0b]"></span>
                Review: {reviewCount}
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-[#ef4444]"></span>
                High Risk: {highRiskCount}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className="text-center text-[11px] text-[#717785]">
        <p>Ministry of Home Affairs (MHA) · Sashastra Seema Bal (SSB) · Administrative Control Center</p>
      </div>
    </div>
  );
};

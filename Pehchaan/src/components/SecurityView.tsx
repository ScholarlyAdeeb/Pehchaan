import React, { useCallback, useEffect, useState } from 'react';
import { Checkpoint, ScreeningRecord } from '../types';
import { useAuth } from '../contexts/AuthContext';

type Tab = 'users' | 'insider' | 'ledger' | 'registry' | 'incident';

interface ManagedUser {
  id: string; email: string; name: string; role: string; checkpoint_ids: string[];
  must_change_password: boolean; active: boolean; created_at: string;
}

function useApi() {
  const { token } = useAuth();
  return useCallback(async (url: string, init?: RequestInit) => {
    const res = await fetch(url, {
      ...init,
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}`, ...(init?.headers || {}) },
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `HTTP ${res.status}`);
    return body;
  }, [token]);
}

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'users', label: 'Users & checkpoints', icon: 'manage_accounts' },
  { id: 'insider', label: 'Insider alerts', icon: 'person_alert' },
  { id: 'ledger', label: 'Signed batches', icon: 'account_tree' },
  { id: 'registry', label: 'Forgery registry', icon: 'fingerprint' },
  { id: 'incident', label: 'Incident report', icon: 'report' },
];

export const SecurityView: React.FC<{ records: ScreeningRecord[] }> = () => {
  const [tab, setTab] = useState<Tab>('users');
  return (
    <div className="p-4 sm:p-6 space-y-5 max-w-[1400px] mx-auto">
      <div className="pb-4 border-b border-[#efedf3]">
        <h1 className="text-xl font-bold text-[#1a1b1f]">Security &amp; trust</h1>
        <p className="text-xs text-[#414753] mt-0.5">Accounts, insider-threat alerts, signed record batches, the forged-document registry and incident reporting.</p>
      </div>
      <div className="flex flex-wrap gap-1 bg-[#f4f3f8] p-1 rounded-lg w-fit" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md flex items-center gap-1.5 ${tab === t.id ? 'bg-white text-[#0059b5] shadow-xs' : 'text-[#414753] hover:text-[#1a1b1f]'}`}>
            <span className="material-symbols-outlined text-[16px]">{t.icon}</span>{t.label}
          </button>
        ))}
      </div>
      {tab === 'users' && <UsersTab />}
      {tab === 'insider' && <InsiderTab />}
      {tab === 'ledger' && <LedgerTab />}
      {tab === 'registry' && <RegistryTab />}
      {tab === 'incident' && <IncidentTab />}
    </div>
  );
};

const Panel: React.FC<{ title: string; children: React.ReactNode; action?: React.ReactNode }> = ({ title, children, action }) => (
  <section className="bg-white border border-[#efedf3] rounded-xl p-5 space-y-3">
    <div className="flex items-center justify-between gap-3">
      <h2 className="text-xs font-bold uppercase tracking-wider text-[#1a1b1f]">{title}</h2>
      {action}
    </div>
    {children}
  </section>
);

const ErrorLine: React.FC<{ error: string | null }> = ({ error }) =>
  error ? <p className="text-xs text-[#93000a] bg-[#fff1f0] rounded p-2">{error}</p> : null;

const field = 'w-full text-xs px-3 py-2 border border-[#e3e2e7] rounded-lg focus:outline-none focus:border-[#0059b5]';

// ---------------------------------------------------------------- Users
const UsersTab: React.FC = () => {
  const api = useApi();
  const { user: me } = useAuth();
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [checkpoints, setCheckpoints] = useState<Checkpoint[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [secret, setSecret] = useState<{ who: string; password: string } | null>(null);
  const [form, setForm] = useState({ name: '', email: '', role: 'OFFICER', checkpointIds: [] as string[] });
  const [cpForm, setCpForm] = useState({ id: '', name: '', location: '', latitude: '', longitude: '', radiusKm: '5' });

  const load = useCallback(async () => {
    try {
      const [u, c] = await Promise.all([api('/api/admin/users'), api('/api/checkpoints')]);
      setUsers(u); setCheckpoints(c); setError(null);
    } catch (e: any) { setError(e.message); }
  }, [api]);
  useEffect(() => { load(); }, [load]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const out = await api('/api/admin/users', { method: 'POST', body: JSON.stringify(form) });
      setSecret({ who: out.email, password: out.temporaryPassword });
      setForm({ name: '', email: '', role: 'OFFICER', checkpointIds: [] });
      load();
    } catch (err: any) { setError(err.message); }
  };
  const reset = async (u: ManagedUser) => {
    try {
      const out = await api(`/api/admin/users/${u.id}/reset-password`, { method: 'POST' });
      setSecret({ who: u.email, password: out.temporaryPassword });
      load();
    } catch (err: any) { setError(err.message); }
  };
  const toggle = async (u: ManagedUser) => {
    try { await api(`/api/admin/users/${u.id}/active`, { method: 'POST', body: JSON.stringify({ active: !u.active }) }); load(); }
    catch (err: any) { setError(err.message); }
  };
  const saveCheckpoint = async (e: React.FormEvent) => {
    e.preventDefault();
    try { await api('/api/admin/checkpoints', { method: 'POST', body: JSON.stringify(cpForm) }); setCpForm({ id: '', name: '', location: '', latitude: '', longitude: '', radiusKm: '5' }); load(); }
    catch (err: any) { setError(err.message); }
  };

  return (
    <div className="space-y-4">
      <ErrorLine error={error} />
      {secret && (
        <div className="p-3 rounded-lg bg-[#fff4dc] border border-[#ffe4af] text-xs text-[#3d2600] flex flex-wrap items-center justify-between gap-2">
          <span>One-time password for <b>{secret.who}</b>: <code className="font-mono bg-white px-1.5 py-0.5 rounded">{secret.password}</code> — give it to the user in person; they must change it at first sign-in. It is not shown again.</span>
          <button onClick={() => setSecret(null)} className="btn-ghost">Done</button>
        </div>
      )}
      <Panel title={`Accounts (${users.length})`}>
        <ul className="md:hidden divide-y divide-[#f4f3f8]">
          {users.map((u) => (
            <li key={u.id} className="py-3 space-y-1.5 text-xs">
              <div className="flex items-start justify-between gap-3">
                <span className="text-sm font-semibold text-[#1a1b1f]">{u.name}</span>
                {!u.active ? <span className="shrink-0 text-[#93000a] font-semibold">Deactivated</span>
                  : u.must_change_password ? <span className="shrink-0 text-[#8a5600] font-semibold">Must change password</span>
                  : <span className="shrink-0 text-[#006a26]">Active</span>}
              </div>
              <div className="text-[#414753] break-all">{u.email}</div>
              <div className="text-[#5d6370]">{u.role.replace('_', ' ')} · <span className="font-mono">{u.role === 'ADMIN' ? 'all checkpoints' : u.checkpoint_ids.join(', ')}</span></div>
              <div className="flex flex-wrap gap-2 pt-1">
                <button onClick={() => reset(u)} className="btn-ghost min-h-[40px]">Reset password</button>
                {u.id !== me?.userId && <button onClick={() => toggle(u)} className="btn-ghost min-h-[40px]">{u.active ? 'Deactivate' : 'Reactivate'}</button>}
              </div>
            </li>
          ))}
        </ul>
        <div className="hidden md:block overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="text-left text-[#717785] border-b border-[#efedf3]">
              <th className="py-2 pr-3">Name</th><th className="py-2 px-3">Email</th><th className="py-2 px-3">Role</th><th className="py-2 px-3">Checkpoints</th><th className="py-2 px-3">Status</th><th className="py-2 pl-3" />
            </tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-[#f4f3f8]">
                  <td className="py-2 pr-3 font-semibold">{u.name}</td>
                  <td className="py-2 px-3">{u.email}</td>
                  <td className="py-2 px-3">{u.role.replace('_', ' ')}</td>
                  <td className="py-2 px-3 font-mono text-[11px]">{u.role === 'ADMIN' ? 'all' : u.checkpoint_ids.join(', ')}</td>
                  <td className="py-2 px-3">
                    {!u.active ? <span className="text-[#93000a] font-semibold">Deactivated</span>
                      : u.must_change_password ? <span className="text-[#8a5600] font-semibold">Must change password</span>
                      : <span className="text-[#006a26]">Active</span>}
                  </td>
                  <td className="py-2 pl-3 text-right whitespace-nowrap space-x-1">
                    <button onClick={() => reset(u)} className="btn-ghost">Reset password</button>
                    {u.id !== me?.userId && <button onClick={() => toggle(u)} className="btn-ghost">{u.active ? 'Deactivate' : 'Reactivate'}</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel title="Add a user">
          <form onSubmit={create} className="space-y-2">
            <label className="sr-only" htmlFor="nu-name">Name</label>
            <input id="nu-name" required placeholder="Full name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={field} />
            <label className="sr-only" htmlFor="nu-email">Email</label>
            <input id="nu-email" required type="email" placeholder="Official email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className={field} />
            <label className="sr-only" htmlFor="nu-role">Role</label>
            <select id="nu-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} className={field}>
              <option value="OFFICER">Officer</option><option value="POST_INCHARGE">Post In-Charge</option><option value="ADMIN">Admin</option>
            </select>
            {form.role !== 'ADMIN' && (
              <fieldset className="text-xs space-y-1">
                <legend className="text-[#717785] mb-1">Checkpoints</legend>
                {checkpoints.map((cp) => (
                  <label key={cp.id} className="flex items-center gap-2">
                    <input type="checkbox" checked={form.checkpointIds.includes(cp.id)}
                      onChange={(e) => setForm({ ...form, checkpointIds: e.target.checked ? [...form.checkpointIds, cp.id] : form.checkpointIds.filter((x) => x !== cp.id) })} />
                    {cp.name} <span className="font-mono text-[#717785]">{cp.id}</span>
                  </label>
                ))}
              </fieldset>
            )}
            <button type="submit" className="btn-secondary">Create user</button>
            <p className="text-[11px] text-[#717785]">A one-time password is generated; the user must replace it at first sign-in.</p>
          </form>
        </Panel>
        <Panel title={`Checkpoints (${checkpoints.length})`}>
          <ul className="text-xs space-y-1">
            {checkpoints.map((cp) => (
              <li key={cp.id} className="flex flex-wrap gap-x-2">
                <button type="button" className="font-mono text-[#0059b5] hover:underline"
                  onClick={() => setCpForm({ id: cp.id, name: cp.name, location: cp.location || '', latitude: cp.latitude?.toString() ?? '', longitude: cp.longitude?.toString() ?? '', radiusKm: (cp.radius_km ?? 5).toString() })}>
                  {cp.id}
                </button>
                <span>{cp.name}{cp.location ? `, ${cp.location}` : ''}</span>
                <span className={cp.latitude != null ? 'text-[#006a26]' : 'text-[#8a5600]'}>
                  {cp.latitude != null ? `${cp.latitude.toFixed(4)}, ${cp.longitude?.toFixed(4)} · ${cp.radius_km ?? 5} km` : 'no coordinates — cannot be auto-detected'}
                </span>
              </li>
            ))}
          </ul>
          <form onSubmit={saveCheckpoint} className="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-2 border-t border-[#efedf3]">
            <input aria-label="Checkpoint ID" required placeholder="ID, e.g. ICP-RAXAUL" value={cpForm.id} onChange={(e) => setCpForm({ ...cpForm, id: e.target.value })} className={field} />
            <input aria-label="Checkpoint name" required placeholder="Name" value={cpForm.name} onChange={(e) => setCpForm({ ...cpForm, name: e.target.value })} className={field} />
            <input aria-label="Location" placeholder="Location" value={cpForm.location} onChange={(e) => setCpForm({ ...cpForm, location: e.target.value })} className={field} />
            <input aria-label="Latitude" inputMode="decimal" placeholder="Latitude, e.g. 26.9853" value={cpForm.latitude} onChange={(e) => setCpForm({ ...cpForm, latitude: e.target.value })} className={field} />
            <input aria-label="Longitude" inputMode="decimal" placeholder="Longitude, e.g. 84.8554" value={cpForm.longitude} onChange={(e) => setCpForm({ ...cpForm, longitude: e.target.value })} className={field} />
            <input aria-label="Detection radius in km" inputMode="decimal" placeholder="Radius km" value={cpForm.radiusKm} onChange={(e) => setCpForm({ ...cpForm, radiusKm: e.target.value })} className={field} />
            <div className="sm:col-span-3 flex flex-wrap items-center gap-2">
              <button type="submit" className="btn-secondary">Save checkpoint</button>
              <button type="button" className="btn-ghost" onClick={() => navigator.geolocation?.getCurrentPosition(
                (pos) => setCpForm((f) => ({ ...f, latitude: pos.coords.latitude.toFixed(6), longitude: pos.coords.longitude.toFixed(6) })),
                () => setError('Location permission was denied or unavailable.'),
              )}>Use my current location</button>
              <span className="text-[11px] text-[#5d6370]">Officers inside the radius are placed at this checkpoint automatically. Click an ID to edit it.</span>
            </div>
          </form>
        </Panel>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------- Insider
const SEVERITY: Record<string, string> = {
  high: 'bg-[#ffdad6] text-[#93000a]', medium: 'bg-[#ffe4af] text-[#5c3a00]', low: 'bg-[#e9e7ed] text-[#414753]',
};

const InsiderTab: React.FC = () => {
  const api = useApi();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api(`/api/security/insider?days=${days}`).then(setData).catch((e) => setError(e.message)); }, [api, days]);
  return (
    <div className="space-y-4">
      <ErrorLine error={error} />
      <Panel title="Alerts" action={
        <select aria-label="Time window" value={days} onChange={(e) => setDays(Number(e.target.value))} className="text-xs border border-[#e3e2e7] rounded px-2 py-1">
          <option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option>
        </select>}>
        <p className="text-[11px] text-[#717785]">
          Rules: frequent requests to clear flagged travellers (≥3 and ≥30% of flagged), overrides refused by the In-Charge,
          40%+ of screenings between 22:00–05:00 IST, the same document screened 3+ times, and 5+ failed sign-ins.
        </p>
        {!data ? <p className="text-xs text-[#717785]">Loading…</p> : data.alerts.length === 0 ? (
          <p className="text-xs text-[#006a26]">No alerts in this window.</p>
        ) : (
          <ul className="space-y-2">
            {data.alerts.map((a: any, i: number) => (
              <li key={i} className="flex gap-2 items-start text-xs">
                <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${SEVERITY[a.severity]}`}>{a.severity}</span>
                <span><b>{a.officer}</b> — {a.rule}: {a.detail}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      {data && (
        <Panel title="Per-officer activity">
          <div className="overflow-x-auto">
            <table className="w-full text-xs tabular-nums">
              <thead><tr className="text-left text-[#717785] border-b border-[#efedf3]">
                <th className="py-2 pr-3">Officer</th><th className="py-2 px-3 text-right">Screenings</th><th className="py-2 px-3 text-right">Flagged</th>
                <th className="py-2 px-3 text-right">Clear requests on flagged</th><th className="py-2 px-3 text-right">Refused</th><th className="py-2 pl-3 text-right">22:00–05:00</th>
              </tr></thead>
              <tbody>
                {data.officers.map((o: any) => (
                  <tr key={o.uid} className="border-b border-[#f4f3f8]">
                    <td className="py-2 pr-3 font-semibold">{o.officer || o.uid}</td>
                    <td className="py-2 px-3 text-right">{o.scans}</td><td className="py-2 px-3 text-right">{o.flagged}</td>
                    <td className="py-2 px-3 text-right">{o.overrides}</td><td className="py-2 px-3 text-right">{o.refused}</td>
                    <td className="py-2 pl-3 text-right">{o.offHours}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}
    </div>
  );
};

// ---------------------------------------------------------------- Ledger
const LedgerTab: React.FC = () => {
  const api = useApi();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ledgerCheck, setLedgerCheck] = useState<any>(null);
  const load = useCallback(() => api('/api/security/batches').then(setData).catch((e) => setError(e.message)), [api]);
  const checkLedger = async () => {
    setBusy(true);
    try { setLedgerCheck(await api('/api/security/fabric/verify')); } catch (e: any) { setError(e.message); }
    setBusy(false);
  };
  useEffect(() => { load(); }, [load]);
  const seal = async () => {
    setBusy(true);
    try { await api('/api/security/batches/seal', { method: 'POST' }); await load(); } catch (e: any) { setError(e.message); }
    setBusy(false);
  };
  return (
    <div className="space-y-4">
      <ErrorLine error={error} />
      <Panel title="Signed batches" action={
        <button onClick={seal} disabled={busy || !data?.unsealed} className="btn-secondary disabled:opacity-50">
          {busy ? 'Sealing…' : `Seal ${data?.unsealed ?? 0} pending record(s) now`}
        </button>}>
        <p className="text-[11px] text-[#717785] max-w-3xl">
          Every 10 minutes new records are sealed: their hashes form a Merkle tree whose root is signed with this server's
          Ed25519 key{data?.openTimestamps ? ' and timestamped on the Bitcoin blockchain via OpenTimestamps' : ''}. Each record then has a receipt
          (its hash plus the sibling hashes to the root) that proves it existed unchanged at sealing time, without revealing other records.
          {!data?.openTimestamps && ' External timestamping is off; set ANCHOR_OPENTIMESTAMPS=true to also anchor roots publicly.'}
        </p>
        <div className="text-[11px] border border-[#efedf3] rounded p-2.5 space-y-1.5 max-w-3xl">
          <p className="font-semibold text-[#1a1b1f]">Hyperledger Fabric ledger</p>
          {!data?.fabric?.enabled ? (
            <p className="text-[#717785]">Not configured. Batch roots are kept in the database only.</p>
          ) : !data.fabric.reachable ? (
            <p className="text-[#8a5600]">Peer {data.fabric.endpoint} is unreachable ({data.fabric.error}). Sealed batches are anchored when it returns.</p>
          ) : (
            <p className="text-[#006a26]">
              Connected to {data.fabric.endpoint}, channel <b>{data.fabric.channel}</b>, chaincode <b>{data.fabric.chaincode}</b>:
              {' '}{data.fabric.anchors} batch root(s) on the ledger. A root is written once and cannot be changed there.
            </p>
          )}
          {data?.fabric?.enabled && (
            <button onClick={checkLedger} disabled={busy} className="btn-secondary disabled:opacity-50">Compare database with ledger</button>
          )}
          {ledgerCheck && (
            <p className={ledgerCheck.mismatched?.length ? 'text-[#ba1a1a] font-semibold' : 'text-[#1a1b1f]'}>
              {!ledgerCheck.reachable
                ? `Ledger unreachable: ${ledgerCheck.error}`
                : ledgerCheck.mismatched.length
                  ? `ALTERED: batch ${ledgerCheck.mismatched.map((m: any) => `#${m.batch}`).join(', ')} has a different root in the database than on the ledger.`
                  : `${ledgerCheck.checked - ledgerCheck.missing.length} of ${ledgerCheck.checked} batch root(s) match the ledger`
                    + (ledgerCheck.missing.length ? `; ${ledgerCheck.missing.length} not anchored yet.` : '.')}
            </p>
          )}
        </div>
        {!data ? <p className="text-xs text-[#717785]">Loading…</p> : data.batches.length === 0 ? (
          <p className="text-xs text-[#717785]">No batches yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-left text-[#717785] border-b border-[#efedf3]">
                <th className="py-2 pr-3">Batch</th><th className="py-2 px-3">Sealed</th><th className="py-2 px-3 text-right">Records</th><th className="py-2 px-3">Merkle root</th><th className="py-2 px-3">Fabric transaction</th><th className="py-2 pl-3">Public timestamp</th>
              </tr></thead>
              <tbody>
                {data.batches.map((b: any) => (
                  <tr key={b.id} className="border-b border-[#f4f3f8]">
                    <td className="py-2 pr-3 font-mono">#{b.id}</td>
                    <td className="py-2 px-3">{new Date(b.created_at).toLocaleString('en-IN')}</td>
                    <td className="py-2 px-3 text-right tabular-nums">{b.leaf_count}</td>
                    <td className="py-2 px-3 font-mono text-[11px] break-all">{b.merkle_root}</td>
                    <td className="py-2 px-3 font-mono text-[11px]" title={b.fabric_tx || ''}>{b.fabric_tx ? `${b.fabric_tx.slice(0, 16)}…` : 'not anchored'}</td>
                    <td className="py-2 pl-3">{b.external_proof ? 'OpenTimestamps (pending Bitcoin confirmation)' : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data?.publicKey && (
          <details className="text-[11px]"><summary className="cursor-pointer text-[#0059b5] font-semibold">Signing public key</summary>
            <pre className="mt-1 p-2 bg-[#f4f3f8] rounded whitespace-pre-wrap break-all">{data.publicKey}</pre></details>
        )}
      </Panel>
    </div>
  );
};

// ---------------------------------------------------------------- Registry
const RegistryTab: React.FC = () => {
  const api = useApi();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api('/api/security/registry').then(setData).catch((e) => setError(e.message)); }, [api]);
  return (
    <div className="space-y-4">
      <ErrorLine error={error} />
      <Panel title={`Forged-document registry (${data?.entries.length ?? 0})`} action={data && (
        <span className={`text-xs font-semibold px-2 py-1 rounded ${data.valid ? 'bg-[#dcf5e1] text-[#00531d]' : 'bg-[#ffdad6] text-[#93000a]'}`}>
          Registry chain {data.valid ? 'intact' : 'BROKEN'}
        </span>)}>
        <p className="text-[11px] text-[#717785] max-w-3xl">
          When an officer rejects a document with evidence of forgery, only its image fingerprint (perceptual hashes of the page and
          the photo region) and the failed checks are added — no names, numbers or photos. Every new scan is compared against this
          list, so the same forged document presented at another checkpoint is flagged immediately. Entries are hash-chained.
        </p>
        {!data ? <p className="text-xs text-[#717785]">Loading…</p> : data.entries.length === 0 ? (
          <p className="text-xs text-[#717785]">No forgeries registered yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-left text-[#717785] border-b border-[#efedf3]">
                <th className="py-2 pr-3">#</th><th className="py-2 px-3">Added</th><th className="py-2 px-3">Document</th><th className="py-2 px-3">Checkpoint</th><th className="py-2 px-3">Failed checks</th><th className="py-2 pl-3">Fingerprint</th>
              </tr></thead>
              <tbody>
                {data.entries.map((r: any) => (
                  <tr key={r.id} className="border-b border-[#f4f3f8] align-top">
                    <td className="py-2 pr-3 font-mono">{r.id}</td>
                    <td className="py-2 px-3">{new Date(r.created_at).toLocaleString('en-IN')}</td>
                    <td className="py-2 px-3">{r.doc_type}</td>
                    <td className="py-2 px-3 font-mono">{r.checkpoint_id || '—'}</td>
                    <td className="py-2 px-3">{r.tamper_types}</td>
                    <td className="py-2 pl-3 font-mono text-[10.5px] break-all">{r.page_hash.slice(0, 24)}…</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
};

// ---------------------------------------------------------------- Incident
const IncidentTab: React.FC = () => {
  const api = useApi();
  const toLocal = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const [from, setFrom] = useState(toLocal(new Date(Date.now() - 24 * 3600 * 1000)));
  const [to, setTo] = useState(toLocal(new Date()));
  const [summary, setSummary] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const generate = async () => {
    setBusy(true); setError(null);
    try {
      const report = await api(`/api/security/incident-report?from=${encodeURIComponent(new Date(from).toISOString())}&to=${encodeURIComponent(new Date(to).toISOString())}`);
      setSummary(report);
      const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `pehchaan-incident-report-${new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-')}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) { setError(e.message); }
    setBusy(false);
  };

  return (
    <Panel title="Incident report">
      <p className="text-[11px] text-[#717785] max-w-3xl">
        CERT-In Directions (April 2022) require cyber incidents to be reported within 6 hours and logs kept for 180 days. This
        bundles every system event, signed audit entry, officer decision and registry addition in the window, with hash-chain
        integrity and current insider alerts, into one file with its own SHA-256.
      </p>
      <ErrorLine error={error} />
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <label htmlFor="ir-from" className="text-[11px] text-[#717785]">From</label>
          <input id="ir-from" type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)} className={field} />
        </div>
        <div className="space-y-1">
          <label htmlFor="ir-to" className="text-[11px] text-[#717785]">To</label>
          <input id="ir-to" type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)} className={field} />
        </div>
        <button onClick={generate} disabled={busy} className="btn-secondary">{busy ? 'Generating…' : 'Generate & download'}</button>
      </div>
      {summary && (
        <dl className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs pt-2">
          {Object.entries(summary.counts as Record<string, number>).map(([k, v]) => (
            <div key={k}><dt className="text-[10px] uppercase text-[#717785]">{k.replace(/_/g, ' ')}</dt><dd className="font-bold tabular-nums">{v}</dd></div>
          ))}
          <div className="col-span-2 sm:col-span-5"><dt className="text-[10px] uppercase text-[#717785]">Report SHA-256</dt><dd className="font-mono text-[11px] break-all">{summary.report_sha256}</dd></div>
        </dl>
      )}
    </Panel>
  );
};

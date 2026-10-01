import React, { useEffect, useRef, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Checkpoint } from '../types';
import { detectCheckpoint } from './CheckpointSelector';

const METHOD_TEXT: Record<string, string> = {
  gps: 'Detected by location',
  'gps-outside-radius': 'Assigned · you appear to be away from it',
  'only-assignment': 'Your assigned checkpoint',
  global: 'Admin · all checkpoints',
  fallback: 'Please confirm',
  manual: 'Chosen manually',
};

/** Header control: shows the auto-detected checkpoint and lets the user
 *  re-detect or switch among the checkpoints they are assigned to. */
export const CheckpointSwitcher: React.FC = () => {
  const { checkpoint, token, isAdmin, selectCheckpoint } = useAuth();
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<Checkpoint[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open || options || !token) return;
    fetch('/api/checkpoints', { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : [])).then(setOptions).catch(() => setOptions([]));
  }, [open, options, token]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', close);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', close); };
  }, [open]);

  if (!checkpoint) return null;
  const method = checkpoint.detection?.method;
  const needsAttention = method === 'fallback' || method === 'gps-outside-radius';

  const redetect = async () => {
    if (!token) return;
    setBusy(true); setError(null);
    try { selectCheckpoint(await detectCheckpoint(token)); setOpen(false); }
    catch (e: any) { setError(e.message); }
    setBusy(false);
  };
  const choose = (cp: Checkpoint) => {
    selectCheckpoint({ ...cp, detection: { method: 'manual', note: 'Chosen manually from your assigned checkpoints.' } });
    setOpen(false);
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs border min-h-[36px] ${
          needsAttention ? 'border-[#b45309] text-[#fcd34d] bg-[#2a1c05]' : 'border-[#222c3e] text-[#cbd5e1] bg-[#141b28] hover:border-[#2563eb]'
        }`}
      >
        <span className="material-symbols-outlined text-[16px]" aria-hidden="true">{method === 'gps' ? 'my_location' : method === 'global' ? 'public' : 'location_on'}</span>
        <span className="font-semibold max-w-[160px] truncate">{checkpoint.name}</span>
        {checkpoint.detection?.distanceKm !== undefined && method === 'gps' && (
          <span className="text-[#94a3b8] font-mono">{checkpoint.detection.distanceKm} km</span>
        )}
        <span className="material-symbols-outlined text-[16px]" aria-hidden="true">expand_more</span>
      </button>

      {open && (
        <div role="menu" className="absolute left-0 mt-1 w-72 z-50 rounded-lg border border-[#222c3e] bg-[#141b28] shadow-xl p-2 space-y-1 text-xs">
          <div className="px-2 py-1.5 text-[#cbd5e1]">
            <div className="font-semibold">{METHOD_TEXT[method || 'manual']}</div>
            {checkpoint.detection?.note && <div className="text-[#a3aec0] mt-0.5">{checkpoint.detection.note}</div>}
          </div>
          <button role="menuitem" onClick={redetect} disabled={busy}
            className="w-full flex items-center gap-2 px-2 py-2 rounded-md text-[#bfdbfe] hover:bg-[#1e293b] disabled:opacity-50">
            <span className="material-symbols-outlined text-[16px]" aria-hidden="true">my_location</span>
            {busy ? 'Detecting…' : 'Re-detect from my location'}
          </button>
          {error && <p className="px-2 text-[#fca5a5]">{error}</p>}
          <div className="border-t border-[#222c3e] pt-1 mt-1">
            <div className="px-2 py-1 text-[10.5px] uppercase tracking-wide text-[#a3aec0]">Your checkpoints</div>
            {isAdmin && (
              <button role="menuitem" onClick={() => choose({ id: 'GLOBAL', name: 'Global Scope' })}
                className="w-full text-left px-2 py-2 rounded-md text-[#e2e8f0] hover:bg-[#1e293b]">Global scope (all checkpoints)</button>
            )}
            {options === null ? <p className="px-2 py-2 text-[#a3aec0]">Loading…</p> : options.map((cp) => (
              <button key={cp.id} role="menuitem" onClick={() => choose(cp)}
                className={`w-full text-left px-2 py-2 rounded-md hover:bg-[#1e293b] ${cp.id === checkpoint.id ? 'text-[#60a5fa] font-semibold' : 'text-[#e2e8f0]'}`}>
                {cp.name} <span className="font-mono text-[#a3aec0]">{cp.id}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

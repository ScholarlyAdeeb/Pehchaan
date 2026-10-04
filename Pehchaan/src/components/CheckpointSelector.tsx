import React, { useEffect, useRef, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Checkpoint } from '../types';
import { GATE_PRIMARY, GATE_SECONDARY, GateCard, GateEmblem, GateScreen } from './GateScreen';

type Fix = { latitude: number; longitude: number; accuracy: number } | null;

function currentPosition(timeoutMs: number): Promise<Fix> {
  return new Promise((resolve) => {
    if (!('geolocation' in navigator)) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy: pos.coords.accuracy }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: timeoutMs, maximumAge: 5 * 60 * 1000 },
    );
  });
}

/** Resolves the checkpoint from the device location; the server limits the
 *  choice to checkpoints assigned to the account. */
export async function detectCheckpoint(token: string): Promise<Checkpoint> {
  const fix = await currentPosition(8000);
  const res = await fetch('/api/checkpoints/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(fix || {}),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || 'Could not determine your checkpoint.');
  return {
    id: body.id, name: body.name, location: body.location || undefined,
    detection: { method: body.method, distanceKm: body.distanceKm, accuracyM: body.accuracyM, note: body.note },
  };
}

/** Shown briefly after sign-in while the checkpoint is detected. */
export const CheckpointSelector: React.FC = () => {
  const { token, user, selectCheckpoint, logout } = useAuth();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);

  const run = () => {
    if (!token) return;
    setError(null);
    detectCheckpoint(token).then(selectCheckpoint).catch((e) => setError(e.message));
  };

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    run();
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <GateScreen width="max-w-sm">
      <GateCard className="text-center">
        <div className="space-y-4" role="status" aria-live="polite">
          <GateEmblem />
          {!error ? (
            <>
              <div className="flex items-center justify-center gap-2 text-[#0059b5]">
                <span className="relative flex w-2.5 h-2.5" aria-hidden="true">
                  <span className="absolute inset-0 rounded-full bg-[#0071e3]/60 animate-ping motion-reduce:animate-none" />
                  <span className="relative w-2.5 h-2.5 rounded-full bg-[#0071e3]" />
                </span>
                <span className="font-mono text-[10.5px] font-semibold tracking-wider uppercase">Locating</span>
              </div>
              <h1 className="text-[18px] font-semibold text-[#1a1b1f] tracking-tight">Finding your checkpoint…</h1>
              <p className="text-[13px] text-[#414753]">
                {user?.name}, allow location access when asked. Only checkpoints assigned to you can be selected.
              </p>
            </>
          ) : (
            <>
              <span className="material-symbols-outlined text-[36px] text-[#d70015]" aria-hidden="true">location_off</span>
              <h1 className="text-[18px] font-semibold text-[#1a1b1f] tracking-tight">Checkpoint not found</h1>
              <p className="px-3 py-2.5 rounded-xl bg-[#ff3b30]/10 border border-[#ff3b30]/25 text-xs text-[#93000a]">{error}</p>
              <div className="grid grid-cols-2 gap-2 pt-1">
                <button onClick={run} className={GATE_PRIMARY}>
                  <span className="absolute inset-0 bg-gradient-to-b from-white/20 to-transparent pointer-events-none" aria-hidden="true" />
                  <span className="relative">Try again</span>
                </button>
                <button onClick={logout} className={GATE_SECONDARY}>Sign out</button>
              </div>
            </>
          )}
        </div>
      </GateCard>
    </GateScreen>
  );
};

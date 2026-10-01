import React, { useEffect, useRef, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { Checkpoint } from '../types';

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
    <div className="min-h-screen bg-[#0c1017] flex items-center justify-center p-4">
      <div className="w-full max-w-sm text-center space-y-4" role="status" aria-live="polite">
        {!error ? (
          <>
            <span className="material-symbols-outlined text-[40px] text-[#60a5fa] animate-pulse motion-reduce:animate-none" aria-hidden="true">my_location</span>
            <h1 className="text-lg font-bold text-white">Finding your checkpoint…</h1>
            <p className="text-sm text-[#a3aec0]">
              {user?.name}, allow location access when asked. Only checkpoints assigned to you can be selected.
            </p>
          </>
        ) : (
          <>
            <span className="material-symbols-outlined text-[40px] text-[#f87171]" aria-hidden="true">location_off</span>
            <h1 className="text-lg font-bold text-white">Checkpoint not found</h1>
            <p className="text-sm text-[#fca5a5]">{error}</p>
            <div className="flex justify-center gap-2">
              <button onClick={run} className="px-4 py-2.5 rounded-lg bg-[#2563eb] hover:bg-[#1d4ed8] text-white text-sm font-semibold">Try again</button>
              <button onClick={logout} className="px-4 py-2.5 rounded-lg bg-[#1e293b] hover:bg-[#273449] text-white text-sm font-semibold">Sign out</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

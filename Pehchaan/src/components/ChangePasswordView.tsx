import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { GATE_FIELD, GATE_LABEL, GATE_PRIMARY, GateAlert, GateCard, GateEmblem, GateScreen } from './GateScreen';

/** Shown instead of the app when an account must set a new password. */
export const ChangePasswordView: React.FC = () => {
  const { token, user, applySession, logout } = useAuth();
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (next !== confirm) return setError('The new passwords do not match.');
    setBusy(true);
    try {
      const res = await fetch('/api/auth/change-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ currentPassword: current, newPassword: next }),
      });
      const data = await res.json();
      if (!res.ok) setError(data.error || 'Could not change the password.');
      else applySession(data.token, data.user);
    } catch {
      setError('Network error');
    }
    setBusy(false);
  };

  const field = `${GATE_FIELD} px-3.5 font-mono`;
  return (
    <GateScreen>
      <GateCard>
        <form onSubmit={submit} className="space-y-4">
          <div className="text-center space-y-3">
            <GateEmblem />
            <div>
              <h1 className="text-[18px] font-semibold text-[#1a1b1f] tracking-tight">Set a new password</h1>
              <p className="text-[12.5px] text-[#414753] mt-1">
                {user?.name}, your account is using a temporary or published password. Choose a new one to continue.
              </p>
            </div>
          </div>
          {error && <GateAlert tone="error">{error}</GateAlert>}
          <div className="space-y-1.5">
            <label htmlFor="pw-current" className={GATE_LABEL}>Current password</label>
            <input id="pw-current" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} className={field} />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="pw-new" className={GATE_LABEL}>New password</label>
            <input id="pw-new" type="password" autoComplete="new-password" required minLength={12} value={next} onChange={(e) => setNext(e.target.value)} className={field} />
            <p className="text-[11px] text-[#5f5e60]">At least 12 characters, with letters and numbers.</p>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="pw-confirm" className={GATE_LABEL}>Repeat new password</label>
            <input id="pw-confirm" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} className={field} />
          </div>
          <div className="pt-1 space-y-2">
            <button type="submit" disabled={busy} className={`${GATE_PRIMARY} w-full`}>
              <span className="absolute inset-0 bg-gradient-to-b from-white/20 to-transparent pointer-events-none" aria-hidden="true" />
              <span className="relative">{busy ? 'Saving…' : 'Save new password'}</span>
            </button>
            <button type="button" onClick={logout} className="w-full py-2 text-xs font-medium text-[#5f5e60] hover:text-[#0059b5] cursor-pointer">Sign out</button>
          </div>
        </form>
      </GateCard>
    </GateScreen>
  );
};

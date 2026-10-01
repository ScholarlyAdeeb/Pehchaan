import React, { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';

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

  const field = 'w-full text-sm p-3 bg-[#0c1017] border border-[#1b2230] rounded-lg text-white focus:outline-none focus:border-[#2563eb]';
  return (
    <div className="min-h-screen bg-[#0c1017] flex items-center justify-center p-4">
      <form onSubmit={submit} className="w-full max-w-md bg-[#141b28] border border-[#1b2230] rounded-2xl p-6 sm:p-8 space-y-4">
        <div>
          <h1 className="text-lg font-bold text-white">Set a new password</h1>
          <p className="text-xs text-[#94a3b8] mt-1">
            {user?.name}, your account is using a temporary or published password. Choose a new one to continue.
          </p>
        </div>
        {error && <div className="p-3 bg-[#3b1111] border border-[#7f1d1d] rounded-lg text-xs text-[#fca5a5]">{error}</div>}
        <div className="space-y-1">
          <label htmlFor="pw-current" className="text-xs font-semibold text-[#94a3b8]">Current password</label>
          <input id="pw-current" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} className={field} />
        </div>
        <div className="space-y-1">
          <label htmlFor="pw-new" className="text-xs font-semibold text-[#94a3b8]">New password</label>
          <input id="pw-new" type="password" autoComplete="new-password" required minLength={12} value={next} onChange={(e) => setNext(e.target.value)} className={field} />
          <p className="text-[11px] text-[#7a889c]">At least 12 characters, with letters and numbers.</p>
        </div>
        <div className="space-y-1">
          <label htmlFor="pw-confirm" className="text-xs font-semibold text-[#94a3b8]">Repeat new password</label>
          <input id="pw-confirm" type="password" autoComplete="new-password" required value={confirm} onChange={(e) => setConfirm(e.target.value)} className={field} />
        </div>
        <button type="submit" disabled={busy} className="w-full bg-[#2563eb] hover:bg-[#1d4ed8] disabled:opacity-50 text-white py-3 rounded-xl text-sm font-bold">
          {busy ? 'Saving…' : 'Save new password'}
        </button>
        <button type="button" onClick={logout} className="w-full text-xs text-[#94a3b8] hover:text-white">Sign out</button>
      </form>
    </div>
  );
};

import React, { useEffect, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useI18n, Language } from '../contexts/I18nContext';

interface LoginViewProps {
  onNavigatePage?: (page: 'privacy' | 'terms') => void;
}

export const LoginView: React.FC<LoginViewProps> = ({ onNavigatePage }) => {
  const { login } = useAuth();
  const { t, lang, setLang } = useI18n();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [seedMsg, setSeedMsg] = useState('');
  const [seeding, setSeeding] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const [setupAvailable, setSetupAvailable] = useState(false);
  const [setup, setSetup] = useState({ setupCode: '', name: '', email: '', password: '' });

  useEffect(() => {
    fetch('/api/auth/setup').then((r) => r.json()).then((d) => setSetupAvailable(Boolean(d.available))).catch(() => {});
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    const trimmedEmail = email.trim();
    if (!trimmedEmail) {
      setError(t('login.error.email_required') || 'Email is required');
      return;
    }
    if (!password) {
      setError(t('login.error.password_required') || 'Password is required');
      return;
    }
    setIsLoading(true);
    const result = await login(trimmedEmail, password);
    setIsLoading(false);
    if (!result.ok) {
      setError(result.error === 'Network error' ? t('login.error.network') : t('login.error.invalid'));
    }
  };

  const handleSetup = async (e: React.FormEvent) => {
    e.preventDefault();
    setSeeding(true);
    setSeedMsg('');
    setError('');
    try {
      const res = await fetch('/api/auth/setup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(setup),
      });
      const data = await res.json();
      if (res.ok) {
        setSeedMsg(data.message);
        setSetupOpen(false);
        setSetupAvailable(false);
        setEmail(setup.email);
      } else {
        setError(data.error || 'Setup failed');
      }
    } catch {
      setError('Network error');
    }
    setSeeding(false);
  };

  return (
    <div className="min-h-screen bg-[#0c1017] flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-3 mb-3">
            <img src="/icon.svg" alt="PEHCHAAN" className="w-10 h-10 object-contain" />
            <h1 className="text-2xl font-bold text-white tracking-tight">{t('app.name')}</h1>
          </div>
          <p className="text-sm text-[#8a94a6]">{t('login.subtitle')}</p>
          <p className="text-[11px] text-[#2563eb] font-semibold mt-2 tracking-wide uppercase">Sign in to begin screening</p>
          <p className="text-xs text-[#7a889c] mt-1">SIH 2026 — Problem Statement 26188</p>
        </div>

        <div className="bg-[#141b28] border border-[#1b2230] rounded-2xl p-6 sm:p-8 shadow-xl">
          <h2 className="text-lg font-bold text-white mb-6">{t('login.title')}</h2>

          {error && (
            <div className="mb-4 p-3 bg-[#3b1111] border border-[#7f1d1d] rounded-lg text-xs text-[#fca5a5]">
              {error}
            </div>
          )}

          {seedMsg && (
            <div className="mb-4 p-3 bg-[#0b2e13] border border-[#166534] rounded-lg text-xs text-[#86efac]">
              {seedMsg}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-[#94a3b8]">{t('login.email')}</label>
              <input
                type="text"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
                className="w-full text-sm p-3 bg-[#0c1017] border border-[#1b2230] rounded-lg text-white font-mono focus:outline-none focus:border-[#2563eb] placeholder:text-[#3e4a5c]"
                placeholder="officer@pehchaan.gov.in"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-[#94a3b8]">{t('login.password')}</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                className="w-full text-sm p-3 bg-[#0c1017] border border-[#1b2230] rounded-lg text-white font-mono focus:outline-none focus:border-[#2563eb]"
              />
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-[#94a3b8]">{t('login.language')}</label>
              <select
                value={lang}
                onChange={(e) => setLang(e.target.value as Language)}
                className="w-full text-sm p-3 bg-[#0c1017] border border-[#1b2230] rounded-lg text-white focus:outline-none focus:border-[#2563eb]"
              >
                <option value="en">English</option>
                <option value="hi">हिन्दी</option>
                <option value="ne">नेपाली</option>
              </select>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full bg-[#2563eb] hover:bg-[#1d4ed8] disabled:opacity-50 text-white py-3 rounded-xl text-sm font-bold transition-all flex items-center justify-center gap-2 cursor-pointer"
            >
              <span className="material-symbols-outlined text-[18px]">login</span>
              <span>{isLoading ? t('login.signing_in') : t('login.submit')}</span>
            </button>
          </form>

          {setupAvailable && (
            <div className="mt-6 pt-4 border-t border-[#1b2230]">
              {!setupOpen ? (
                <div className="text-center">
                  <p className="text-[11px] text-[#7a889c] mb-2">No accounts exist yet.</p>
                  <button onClick={() => setSetupOpen(true)} className="text-xs text-[#60a5fa] hover:text-[#93c5fd] font-semibold cursor-pointer">
                    First-time setup
                  </button>
                </div>
              ) : (
                <form onSubmit={handleSetup} className="space-y-3">
                  <p className="text-[11px] text-[#94a3b8]">
                    Enter the one-time setup code printed in the server console, then create the administrator account.
                  </p>
                  {([
                    ['setupCode', 'Setup code', 'text', 'off'],
                    ['name', 'Your name', 'text', 'name'],
                    ['email', 'Email', 'email', 'email'],
                    ['password', 'Password (12+ characters, letters and numbers)', 'password', 'new-password'],
                  ] as const).map(([key, label, type, ac]) => (
                    <div key={key} className="space-y-1">
                      <label htmlFor={"setup-" + key} className="text-[11px] font-semibold text-[#94a3b8]">{label}</label>
                      <input
                        id={"setup-" + key}
                        type={type}
                        autoComplete={ac}
                        required
                        value={setup[key]}
                        onChange={(e) => setSetup({ ...setup, [key]: e.target.value })}
                        className="w-full text-sm p-2.5 bg-[#0c1017] border border-[#1b2230] rounded-lg text-white focus:outline-none focus:border-[#2563eb]"
                      />
                    </div>
                  ))}
                  <button type="submit" disabled={seeding} className="w-full bg-[#1e293b] hover:bg-[#273449] text-white py-2.5 rounded-lg text-xs font-bold disabled:opacity-50">
                    {seeding ? 'Creating…' : 'Create administrator'}
                  </button>
                </form>
              )}
            </div>
          )}
        </div>

        <div className="text-center mt-6 space-y-1">
          <p className="text-[10px] text-[#6b7a8e]">
            Ministry of Home Affairs (MHA) — Sashastra Seema Bal (SSB)
          </p>
          <p className="text-[10px] text-[#6b7a8e]">
            <button onClick={() => onNavigatePage?.('privacy')} className="text-[#5b8ef5] hover:underline cursor-pointer">Privacy Policy</button>
            <span className="mx-1">·</span>
            <button onClick={() => onNavigatePage?.('terms')} className="text-[#5b8ef5] hover:underline cursor-pointer">Terms of Use</button>
          </p>
        </div>
      </div>
    </div>
  );
};

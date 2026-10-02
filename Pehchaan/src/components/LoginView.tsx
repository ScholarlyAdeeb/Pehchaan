import React, { useEffect, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useI18n, Language } from '../contexts/I18nContext';

interface LoginViewProps {
  onNavigatePage?: (page: 'privacy' | 'terms') => void;
}

// Entrance timing (ms). The sequence is presentational only: the form is
// mounted and usable from the first frame, and nothing waits for it.
const DOCS_START = 650;
const DOC_STEP = 165;
const FORM_START = 1700;
const FORM_STEP = 45;

const BOOT_DOCUMENTS = ['Aadhaar', 'PAN', 'Passport', 'Visa', 'Driving licence', 'National ID'] as const;

const delay = (ms: number, rise = 4) => ({ '--login-delay': `${ms}ms`, '--login-rise': `${rise}px` }) as React.CSSProperties;

/** A plain outline of a document type; no data, only its general shape. */
const DocumentOutline: React.FC<{ kind: (typeof BOOT_DOCUMENTS)[number] }> = ({ kind }) => {
  const line = (x: number, y: number, w: number) => <path d={`M${x} ${y}h${w}`} />;
  const common = { fill: 'none', stroke: '#5b6b85', strokeWidth: 1.5, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const };
  if (kind === 'Passport') {
    return (
      <svg width="46" height="62" viewBox="0 0 46 62" {...common} aria-hidden="true">
        <rect x="1" y="1" width="44" height="60" rx="5" />
        <circle cx="23" cy="24" r="9" />
        <path d="M14 24h18M23 15c-4 5-4 13 0 18M23 15c4 5 4 13 0 18" />
        {line(13, 44, 20)}{line(16, 50, 14)}
      </svg>
    );
  }
  return (
    <svg width="84" height="54" viewBox="0 0 84 54" {...common} aria-hidden="true">
      <rect x="1" y="1" width="82" height="52" rx="6" />
      {kind === 'Aadhaar' && <><rect x="9" y="12" width="18" height="22" rx="2" />{line(35, 15, 34)}{line(35, 23, 26)}{line(35, 31, 30)}{line(9, 43, 66)}</>}
      {kind === 'PAN' && <>{line(9, 13, 30)}<rect x="9" y="21" width="16" height="18" rx="2" />{line(33, 24, 24)}{line(33, 32, 18)}<rect x="62" y="21" width="13" height="13" rx="1.5" />{line(9, 46, 40)}</>}
      {kind === 'Visa' && <>{line(9, 13, 38)}{line(9, 22, 28)}{line(9, 30, 34)}<circle cx="64" cy="22" r="10" /><path d="M58 22l4 4 8-8" />{line(9, 43, 66)}</>}
      {kind === 'Driving licence' && <><rect x="57" y="11" width="18" height="23" rx="2" />{line(9, 14, 36)}{line(9, 22, 28)}{line(9, 30, 32)}<rect x="9" y="38" width="12" height="8" rx="1.5" />{line(27, 43, 30)}</>}
      {kind === 'National ID' && <><circle cx="19" cy="22" r="7" /><path d="M9 39c2-6 18-6 20 0" />{line(38, 16, 34)}{line(38, 24, 26)}{line(38, 32, 30)}{line(38, 40, 20)}</>}
    </svg>
  );
};

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
          <div className="login-boot-logo relative w-24 sm:w-28 mx-auto mb-4">
            <img src="/logo-mark.svg" alt="" className="w-full h-auto block" />
            <span className="login-boot-sweep" aria-hidden="true" />
          </div>
          <img
            src="/logo-wordmark.svg"
            alt="PEHCHAAN — Identity Verification System"
            className="login-boot-rise w-64 sm:w-72 mx-auto mb-4"
            style={delay(420)}
          />
          <h1 className="sr-only">{t('app.name')}</h1>
          <p className="login-boot-rise text-sm text-[#8a94a6]" style={delay(480)}>{t('login.subtitle')}</p>
          <p className="login-boot-rise text-[11px] text-[#2563eb] font-semibold mt-2 tracking-wide uppercase" style={delay(540)}>Sign in to begin screening</p>
          <p className="login-boot-rise text-xs text-[#7a889c] mt-1" style={delay(600)}>SIH 2026 — Problem Statement 26188</p>
        </div>

        <div className="relative">
        <div className="login-boot-docs" aria-hidden="true">
          {BOOT_DOCUMENTS.map((kind, i) => (
            <div key={kind} className="login-boot-doc" style={delay(DOCS_START + i * DOC_STEP)}>
              <DocumentOutline kind={kind} />
              <span className="text-[10px] font-semibold tracking-[0.22em] uppercase text-[#7a889c]">{kind}</span>
            </div>
          ))}
        </div>
        <div className="login-boot-rise bg-[#141b28] border border-[#1b2230] rounded-2xl p-6 sm:p-8 shadow-xl" style={delay(FORM_START, 8)}>
          <h2 className="login-boot-rise text-lg font-bold text-white mb-6" style={delay(FORM_START + FORM_STEP, 6)}>{t('login.title')}</h2>

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
            <div className="login-boot-rise space-y-1.5" style={delay(FORM_START + FORM_STEP * 2, 6)}>
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

            <div className="login-boot-rise space-y-1.5" style={delay(FORM_START + FORM_STEP * 3, 6)}>
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

            <div className="login-boot-rise space-y-1.5" style={delay(FORM_START + FORM_STEP * 4, 6)}>
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
              style={delay(FORM_START + FORM_STEP * 5, 6)}
              className="login-boot-rise w-full bg-[#2563eb] hover:bg-[#1d4ed8] disabled:opacity-50 text-white py-3 rounded-xl text-sm font-bold transition-colors flex items-center justify-center gap-2 cursor-pointer"
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
        </div>

        <div className="login-boot-rise text-center mt-6 space-y-1" style={delay(FORM_START + FORM_STEP * 6)}>
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

import React, { useEffect, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useI18n, Language } from '../contexts/I18nContext';
import { GATE_FIELD, GATE_LABEL, GateCard, GateScreen } from './GateScreen';
import { DemoLoginsNote, showDemoLogins } from './DemoLoginsNote';

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

const FIELD = GATE_FIELD;
const LABEL = GATE_LABEL;

const FieldIcon: React.FC<{ name: string }> = ({ name }) => (
  <span className="material-symbols-outlined absolute left-3.5 top-1/2 -translate-y-1/2 text-[18px] text-[#5f5e60]/60 pointer-events-none" aria-hidden="true">{name}</span>
);

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
  const [showPassword, setShowPassword] = useState(false);
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

  const pickDemo = (demoEmail: string, demoPassword: string) => {
    setEmail(demoEmail);
    setPassword(demoPassword);
    setError('');
  };

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
    <GateScreen>
        <div className="text-center mb-7">
          <div className="login-boot-logo relative mx-auto mb-4 w-[84px]">
            <div className="absolute -inset-1.5 rounded-[22px] bg-gradient-to-tr from-[#FF671F]/25 via-[#0059b5]/20 to-[#046A38]/25 blur-md opacity-80" aria-hidden="true" />
            <div className="relative rounded-2xl bg-gradient-to-b from-white to-[#f4f3f8] p-1 border border-white/90 shadow-[0_6px_20px_rgba(0,50,130,0.12),0_1px_0_rgba(255,255,255,0.95)_inset]">
              <div className="relative rounded-xl bg-white p-2 shadow-[inset_0_1px_2px_rgba(0,0,0,0.03)]">
                <div className="relative">
                  <img src="/logo-mark-light.svg" alt="" className="w-full h-auto block" />
                  <span className="login-boot-sweep" aria-hidden="true" />
                </div>
              </div>
            </div>
          </div>
          <img
            src="/logo-wordmark-light.svg"
            alt="PEHCHAAN — Identity Verification System"
            className="login-boot-rise w-56 sm:w-64 mx-auto mb-3"
            style={delay(420)}
          />
          <h1 className="sr-only">{t('app.name')}</h1>
          <p className="login-boot-rise text-[12.5px] font-medium text-[#414753] tracking-tight" style={delay(480)}>{t('login.subtitle')}</p>
          <div className="login-boot-rise pt-2 flex justify-center" style={delay(540)}>
            <span className="inline-flex items-center px-3 py-0.5 rounded-full font-mono text-[10.5px] font-semibold tracking-wider uppercase text-[#0059b5] bg-[#0059b5]/[0.08] border border-[#0059b5]/15">
              Sign in to begin screening
            </span>
          </div>
          <p className="login-boot-rise font-mono text-[10.5px] text-[#5f5e60]/80 mt-1.5" style={delay(600)}>SIH 2026 — Problem Statement 26188</p>
        </div>

        <div className="relative">
          <div className="login-boot-docs" aria-hidden="true">
            {BOOT_DOCUMENTS.map((kind, i) => (
              <div key={kind} className="login-boot-doc" style={delay(DOCS_START + i * DOC_STEP)}>
                <DocumentOutline kind={kind} />
                <span className="text-[10px] font-semibold tracking-[0.22em] uppercase text-[#5b6b85]">{kind}</span>
              </div>
            ))}
          </div>

          <GateCard className="login-boot-rise" style={delay(FORM_START, 8)}>
            <h2
              className="login-boot-rise flex items-center gap-1.5 text-[16px] font-semibold text-[#1a1b1f] tracking-tight pb-2 mb-4 border-b border-slate-200/60"
              style={delay(FORM_START + FORM_STEP, 6)}
            >
              <span className="material-symbols-outlined text-[18px] text-[#0059b5]" aria-hidden="true">verified_user</span>
              {t('login.title')}
            </h2>

            {error && (
              <div role="alert" className="mb-4 px-3 py-2.5 rounded-xl bg-[#ff3b30]/10 border border-[#ff3b30]/25 text-xs text-[#93000a]">
                {error}
              </div>
            )}

            {seedMsg && (
              <div className="mb-4 px-3 py-2.5 rounded-xl bg-[#34c759]/10 border border-[#34c759]/30 text-xs text-[#00531c]">
                {seedMsg}
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-3.5">
              <div className="login-boot-rise space-y-1.5" style={delay(FORM_START + FORM_STEP * 2, 6)}>
                <label htmlFor="login-email" className={LABEL}>{t('login.email')}</label>
                <div className="relative">
                  <FieldIcon name="badge" />
                  <input
                    id="login-email"
                    type="text"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    required
                    autoComplete="email"
                    className={`${FIELD} pl-10 pr-3.5 font-mono`}
                    placeholder="officer@pehchaan.gov.in"
                  />
                </div>
              </div>

              <div className="login-boot-rise space-y-1.5" style={delay(FORM_START + FORM_STEP * 3, 6)}>
                <label htmlFor="login-password" className={LABEL}>{t('login.password')}</label>
                <div className="relative">
                  <FieldIcon name="lock" />
                  <input
                    id="login-password"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    autoComplete="current-password"
                    className={`${FIELD} pl-10 pr-11 font-mono`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-label={showPassword ? 'Hide password' : 'Show password'}
                    aria-pressed={showPassword}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 w-9 h-9 flex items-center justify-center rounded-lg text-[#5f5e60]/70 hover:text-[#1a1b1f] hover:bg-slate-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-[#0059b5]/40 cursor-pointer"
                  >
                    <span className="material-symbols-outlined text-[19px]" aria-hidden="true">{showPassword ? 'visibility_off' : 'visibility'}</span>
                  </button>
                </div>
              </div>

              <div className="login-boot-rise space-y-1.5" style={delay(FORM_START + FORM_STEP * 4, 6)}>
                <label htmlFor="login-language" className={LABEL}>{t('login.language')}</label>
                <div className="relative">
                  <FieldIcon name="translate" />
                  <select
                    id="login-language"
                    value={lang}
                    onChange={(e) => setLang(e.target.value as Language)}
                    className={`${FIELD} pl-10 pr-9 appearance-none cursor-pointer`}
                  >
                    <option value="en">English</option>
                    <option value="hi">हिन्दी</option>
                    <option value="ne">नेपाली</option>
                  </select>
                  <span className="material-symbols-outlined absolute right-3 top-1/2 -translate-y-1/2 text-[18px] text-[#5f5e60]/60 pointer-events-none" aria-hidden="true">unfold_more</span>
                </div>
              </div>

              <div className="pt-2">
                <button
                  type="submit"
                  disabled={isLoading}
                  style={delay(FORM_START + FORM_STEP * 5, 6)}
                  className="login-boot-rise group relative w-full overflow-hidden py-3.5 px-6 rounded-xl bg-gradient-to-r from-blue-600 via-[#0059b5] to-blue-700 hover:from-blue-500 hover:to-blue-600 text-white text-[15px] font-semibold flex items-center justify-center gap-2 border border-blue-400/40 shadow-[0_4px_16px_rgba(0,89,181,0.36),0_1px_0_rgba(255,255,255,0.4)_inset] hover:shadow-[0_6px_22px_rgba(0,89,181,0.46)] active:scale-[0.985] disabled:opacity-60 transition-all duration-200 focus:outline-none focus-visible:ring-4 focus-visible:ring-[#0059b5]/25 cursor-pointer"
                >
                  <span className="absolute inset-0 bg-gradient-to-b from-white/20 to-transparent pointer-events-none" aria-hidden="true" />
                  <span className="relative material-symbols-outlined text-[18px]" aria-hidden="true">login</span>
                  <span className="relative tracking-wide">{isLoading ? t('login.signing_in') : t('login.submit')}</span>
                </button>
              </div>
            </form>

            {setupAvailable && (
              <div className="mt-6 pt-4 border-t border-slate-200/70">
                {!setupOpen ? (
                  <div className="text-center">
                    <p className="text-[11px] text-[#5f5e60] mb-2">No accounts exist yet.</p>
                    <button onClick={() => setSetupOpen(true)} className="text-xs text-[#0059b5] hover:text-[#00458f] font-semibold cursor-pointer">
                      First-time setup
                    </button>
                  </div>
                ) : (
                  <form onSubmit={handleSetup} className="space-y-3">
                    <p className="text-[11px] text-[#414753]">
                      Enter the one-time setup code printed in the server console, then create the administrator account.
                    </p>
                    {([
                      ['setupCode', 'Setup code', 'text', 'off'],
                      ['name', 'Your name', 'text', 'name'],
                      ['email', 'Email', 'email', 'email'],
                      ['password', 'Password (12+ characters, letters and numbers)', 'password', 'new-password'],
                    ] as const).map(([key, label, type, ac]) => (
                      <div key={key} className="space-y-1">
                        <label htmlFor={'setup-' + key} className="text-[11px] font-semibold text-[#414753]">{label}</label>
                        <input
                          id={'setup-' + key}
                          type={type}
                          autoComplete={ac}
                          required
                          value={setup[key]}
                          onChange={(e) => setSetup({ ...setup, [key]: e.target.value })}
                          className={`${FIELD} px-3.5`}
                        />
                      </div>
                    ))}
                    <button type="submit" disabled={seeding} className="w-full py-2.5 rounded-xl border border-slate-200 bg-white hover:bg-[#f5f5f7] text-[#1a1b1f] text-xs font-semibold disabled:opacity-50 cursor-pointer">
                      {seeding ? 'Creating…' : 'Create administrator'}
                    </button>
                  </form>
                )}
              </div>
            )}
          </GateCard>
        </div>

        <div className="login-boot-rise text-center mt-6 space-y-1.5" style={delay(FORM_START + FORM_STEP * 6)}>
          <p className="text-[12px] font-medium text-[#414753]">
            Ministry of Home Affairs (MHA) — Sashastra Seema Bal (SSB)
          </p>
          <p className="font-mono text-[11px] text-[#5f5e60]">
            <button onClick={() => onNavigatePage?.('privacy')} className="hover:text-[#0059b5] hover:underline underline-offset-2 cursor-pointer">Privacy Policy</button>
            <span className="mx-2 text-[#5f5e60]/40">•</span>
            <button onClick={() => onNavigatePage?.('terms')} className="hover:text-[#0059b5] hover:underline underline-offset-2 cursor-pointer">Terms of Use</button>
          </p>
        </div>

        {showDemoLogins && (
          <>
            {/* Wide screens: pinned beside the card. Phones: below the footer. */}
            <DemoLoginsNote onPick={pickDemo} className="hidden xl:block fixed right-8 top-1/2 -translate-y-1/2 z-20" />
            <div className="xl:hidden flex justify-center mt-8 mb-2">
              <DemoLoginsNote onPick={pickDemo} className="relative" />
            </div>
          </>
        )}
    </GateScreen>
  );
};

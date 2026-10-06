import React from 'react';

// Shared demo accounts for the SIH prototype, shown on the sign-in page so
// judges can try every role. The server keeps these accounts from being
// locked (DEMO_ACCOUNTS). Build with VITE_SHOW_DEMO_LOGINS=false to hide it.
export const DEMO_LOGINS = [
  { role: 'Officer', email: 'officer@pehchaan.gov.in', password: 'officer123', does: 'Screens documents' },
  { role: 'Post In-Charge', email: 'incharge@pehchaan.gov.in', password: 'incharge123', does: 'Supervises, co-signs' },
  { role: 'Administrator', email: 'admin@pehchaan.gov.in', password: 'ABC@12345678', does: 'Analytics, audit, users' },
] as const;

export const showDemoLogins = import.meta.env.VITE_SHOW_DEMO_LOGINS !== 'false';

export const DemoLoginsNote: React.FC<{ onPick: (email: string, password: string) => void; className?: string }> = ({ onPick, className = '' }) => (
  <aside aria-label="Demo sign-in details" className={`demo-note ${className}`}>
    <span className="demo-note-tape" aria-hidden="true" />
    <p className="demo-note-title">Judges, try it! 👋</p>
    <p className="demo-note-sub">Tap an account to fill the form.</p>
    <ul className="demo-note-list">
      {DEMO_LOGINS.map((a) => (
        <li key={a.email}>
          <button type="button" onClick={() => onPick(a.email, a.password)} className="demo-note-row">
            <span className="demo-note-role">{a.role} <em>· {a.does}</em></span>
            <span className="demo-note-cred">{a.email}</span>
            <span className="demo-note-cred">{a.password}</span>
          </button>
        </li>
      ))}
    </ul>
    <p className="demo-note-foot">Prototype · demo data only</p>
  </aside>
);

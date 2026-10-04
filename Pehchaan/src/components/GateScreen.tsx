import React from 'react';
import { TricolorBackdrop } from './TricolorBackdrop';

// The look shared by every screen before the workspace opens (sign-in,
// session restore, new password, checkpoint detection): the ribbon backdrop
// and a frosted card with a tricolour edge.

export const GATE_FIELD = 'w-full py-2.5 rounded-xl bg-white/80 hover:bg-white/95 focus:bg-white text-[13px] text-[#1a1b1f] '
  + 'placeholder:text-[#9aa1ad] border border-slate-200/80 focus:border-[#0059b5]/60 focus:ring-4 focus:ring-[#0059b5]/10 '
  + 'shadow-[0_1px_2px_rgba(0,0,0,0.03)] focus:outline-none transition-all duration-200';
export const GATE_LABEL = 'text-xs font-semibold text-[#414753] tracking-tight';
export const GATE_PRIMARY = 'group relative overflow-hidden py-3 px-6 rounded-xl bg-gradient-to-r from-blue-600 via-[#0059b5] to-blue-700 '
  + 'hover:from-blue-500 hover:to-blue-600 text-white text-sm font-semibold flex items-center justify-center gap-2 border border-blue-400/40 '
  + 'shadow-[0_4px_16px_rgba(0,89,181,0.36),0_1px_0_rgba(255,255,255,0.4)_inset] hover:shadow-[0_6px_22px_rgba(0,89,181,0.46)] '
  + 'active:scale-[0.985] disabled:opacity-60 transition-all duration-200 focus:outline-none focus-visible:ring-4 focus-visible:ring-[#0059b5]/25 cursor-pointer';
export const GATE_SECONDARY = 'py-3 px-6 rounded-xl border border-slate-200 bg-white/80 hover:bg-white text-[#1a1b1f] text-sm font-semibold '
  + 'transition-colors focus:outline-none focus-visible:ring-4 focus-visible:ring-[#0059b5]/20 cursor-pointer';

export const GateAlert: React.FC<{ tone: 'error' | 'success'; children: React.ReactNode }> = ({ tone, children }) => (
  <div
    role={tone === 'error' ? 'alert' : 'status'}
    className={tone === 'error'
      ? 'px-3 py-2.5 rounded-xl bg-[#ff3b30]/10 border border-[#ff3b30]/25 text-xs text-[#93000a]'
      : 'px-3 py-2.5 rounded-xl bg-[#34c759]/10 border border-[#34c759]/30 text-xs text-[#00531c]'}
  >
    {children}
  </div>
);

/** Frosted card with the tricolour edge. */
export const GateCard: React.FC<{ className?: string; style?: React.CSSProperties; children: React.ReactNode }> = ({ className = '', style, children }) => (
  <div
    className={`relative rounded-3xl px-6 py-7 sm:p-9 bg-white/80 backdrop-blur-2xl border border-white/80 ring-1 ring-white/60 shadow-[0_24px_64px_-12px_rgba(0,35,90,0.14),0_1px_2px_rgba(255,255,255,0.9)_inset] ${className}`}
    style={style}
  >
    <div className="absolute top-0 inset-x-8 h-[3px] rounded-b-full bg-gradient-to-r from-[#FF671F] via-white to-[#046A38] shadow-[0_2px_12px_rgba(255,103,31,0.3)]" aria-hidden="true" />
    {children}
  </div>
);

/** Full-screen page: ribbon backdrop with the content centred above it. */
export const GateScreen: React.FC<{ width?: string; children: React.ReactNode }> = ({ width = 'max-w-md', children }) => (
  <div className="relative min-h-screen overflow-hidden bg-[#f4f5f9] flex items-center justify-center px-4 pt-[calc(2rem+env(safe-area-inset-top))] pb-[calc(2rem+env(safe-area-inset-bottom))]">
    <TricolorBackdrop />
    <div className={`relative z-10 w-full ${width}`}>{children}</div>
  </div>
);

/** The emblem in its haloed tile, sized for the smaller gate screens. */
export const GateEmblem: React.FC<{ size?: number }> = ({ size = 64 }) => (
  <div className="relative mx-auto" style={{ width: size }}>
    <div className="absolute -inset-1.5 rounded-[20px] bg-gradient-to-tr from-[#FF671F]/25 via-[#0059b5]/20 to-[#046A38]/25 blur-md opacity-80" aria-hidden="true" />
    <div className="relative rounded-2xl bg-gradient-to-b from-white to-[#f4f3f8] p-1 border border-white/90 shadow-[0_6px_20px_rgba(0,50,130,0.12),0_1px_0_rgba(255,255,255,0.95)_inset]">
      <div className="rounded-xl bg-white p-1.5">
        <img src="/logo-mark-light.svg" alt="" className="w-full h-auto block" />
      </div>
    </div>
  </div>
);

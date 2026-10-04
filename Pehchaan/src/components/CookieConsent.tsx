import React, { useState, useEffect } from 'react';

interface Props {
  onPrivacyClick?: () => void;
}

export function CookieConsent({ onPrivacyClick }: Props) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    try {
      if (!localStorage.getItem('pehchaan-cookie-consent')) {
        setVisible(true);
      }
    } catch {
      setVisible(true);
    }
  }, []);

  if (!visible) return null;

  const accept = () => {
    try { localStorage.setItem('pehchaan-cookie-consent', '1'); } catch {}
    setVisible(false);
  };

  return (
    <div className="fixed inset-x-0 bottom-0 z-50 px-3 sm:px-4 pb-[calc(0.75rem+env(safe-area-inset-bottom))] pointer-events-none">
      <div role="region" aria-label="Cookie notice" className="pointer-events-auto max-w-3xl mx-auto flex items-center justify-between gap-3 sm:gap-4 flex-wrap rounded-2xl px-4 py-3 bg-white/85 backdrop-blur-xl border border-slate-200/80 shadow-[0_8px_24px_-4px_rgba(0,0,0,0.08),0_2px_6px_-1px_rgba(0,0,0,0.05)]">
        <p className="text-xs text-[#414753] leading-relaxed flex-1 min-w-[14rem]">
          This system uses essential session cookies for authentication and security. No tracking or advertising cookies are used.
          <a href="#" onClick={(e) => { e.preventDefault(); onPrivacyClick?.(); }} className="text-[#0059b5] hover:underline underline-offset-2 ml-1 font-medium">Privacy Policy</a>
        </p>
        <button
          onClick={accept}
          className="min-h-[36px] px-4 bg-[#0071e3] hover:bg-[#0062c4] active:scale-[0.985] text-white text-[13px] font-semibold rounded-lg transition-all whitespace-nowrap focus:outline-none focus-visible:ring-4 focus-visible:ring-[#0071e3]/25 cursor-pointer"
        >
          Understood
        </button>
      </div>
    </div>
  );
}
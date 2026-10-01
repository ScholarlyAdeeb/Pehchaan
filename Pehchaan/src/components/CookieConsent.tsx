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
    <div className="fixed bottom-0 left-0 right-0 z-50 p-4 bg-[#1a1d25] border-t border-[#2e323c]">
      <div className="max-w-3xl mx-auto flex items-center justify-between gap-4 flex-wrap">
        <p className="text-xs text-[#8a94a6] leading-relaxed">
          This system uses essential session cookies for authentication and security. No tracking or advertising cookies are used.
          <a href="#" onClick={(e) => { e.preventDefault(); onPrivacyClick?.(); }} className="text-[#5b8ef5] hover:underline ml-1">Privacy Policy</a>
        </p>
        <button
          onClick={accept}
          className="px-4 py-1.5 bg-[#2563eb] text-white text-xs font-medium rounded hover:bg-[#1d4fd8] transition-colors whitespace-nowrap"
        >
          Understood
        </button>
      </div>
    </div>
  );
}
import React, { useState } from 'react';
import { usePWAInstall } from '../hooks/usePWAInstall';

interface PWAInstallButtonProps {
  compact?: boolean;
}

export const PWAInstallButton: React.FC<PWAInstallButtonProps> = ({ compact = false }) => {
  const { isInstallable, isInstalled, isIOS, install } = usePWAInstall();
  const [showIOSGuide, setShowIOSGuide] = useState(false);

  // If already running as an installed PWA, hide the button
  if (isInstalled) {
    return null;
  }

  // Chromium / Android / Desktop flow
  if (isInstallable) {
    return (
      <button
        onClick={install}
        className={`flex items-center gap-1.5 rounded-lg bg-[#2563eb] text-white hover:bg-[#1d4ed8] font-semibold transition-all shadow-sm cursor-pointer ${
          compact ? 'px-2 py-1 text-[11px]' : 'px-3 py-1.5 text-xs'
        }`}
        title="Install PEHCHAAN PWA on Home Screen"
      >
        <span className="material-symbols-outlined text-[16px]">install_mobile</span>
        <span>Install App</span>
      </button>
    );
  }

  // iOS Safari flow (beforeinstallprompt is not supported by WebKit)
  if (isIOS) {
    return (
      <>
        <button
          onClick={() => setShowIOSGuide(true)}
          className={`flex items-center gap-1.5 rounded-lg bg-[#182236] border border-[#2e3e5b] text-[#93c5fd] hover:text-white font-semibold transition-all cursor-pointer ${
            compact ? 'px-2 py-1 text-[11px]' : 'px-3 py-1.5 text-xs'
          }`}
          title="Add to iPhone/iPad Home Screen"
        >
          <span className="material-symbols-outlined text-[16px]">ios_share</span>
          <span>Add to iOS</span>
        </button>

        {showIOSGuide && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4">
            <div className="w-full max-w-sm rounded-2xl bg-[#0c1017] border border-[#242f44] p-5 shadow-2xl text-white">
              <div className="flex items-center justify-between pb-3 border-b border-[#1b2333]">
                <div className="flex items-center gap-2">
                  <span className="material-symbols-outlined text-[20px] text-[#60a5fa]">phone_iphone</span>
                  <h3 className="text-sm font-bold text-white">Install PEHCHAAN on iOS</h3>
                </div>
                <button
                  onClick={() => setShowIOSGuide(false)}
                  className="text-[#8a94a6] hover:text-white cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[18px]">close</span>
                </button>
              </div>

              <div className="mt-3 space-y-2 text-xs text-[#cbd5e1] leading-relaxed">
                <p className="flex items-start gap-2">
                  <span className="w-5 h-5 rounded-full bg-[#1e293b] text-[#60a5fa] font-bold text-[10px] flex items-center justify-center shrink-0 mt-0.5">
                    1
                  </span>
                  <span>Tap the <strong>Share</strong> icon in Safari's bottom navigation bar.</span>
                </p>
                <p className="flex items-start gap-2">
                  <span className="w-5 h-5 rounded-full bg-[#1e293b] text-[#60a5fa] font-bold text-[10px] flex items-center justify-center shrink-0 mt-0.5">
                    2
                  </span>
                  <span>Scroll down and select <strong>Add to Home Screen</strong>.</span>
                </p>
                <p className="flex items-start gap-2">
                  <span className="w-5 h-5 rounded-full bg-[#1e293b] text-[#60a5fa] font-bold text-[10px] flex items-center justify-center shrink-0 mt-0.5">
                    3
                  </span>
                  <span>Open PEHCHAAN directly from your Home Screen in standalone offline mode!</span>
                </p>
              </div>

              <button
                onClick={() => setShowIOSGuide(false)}
                className="mt-4 w-full rounded-lg bg-[#2563eb] hover:bg-[#1d4ed8] py-2 text-xs font-semibold text-white transition-colors cursor-pointer"
              >
                Got It
              </button>
            </div>
          </div>
        )}
      </>
    );
  }

  // Ambient install indicator for mobile browsers that support PWA
  return (
    <button
      onClick={() => {
        // Fallback for browsers
        if ('serviceWorker' in navigator) {
          alert('To install PEHCHAAN on mobile: tap your browser menu (⋮ or Share) and choose "Install App" or "Add to Home screen".');
        }
      }}
      className={`hidden sm:flex items-center gap-1.5 rounded-lg bg-[#182236] border border-[#22314d] text-[#94a3b8] hover:text-white font-medium transition-all cursor-pointer ${
        compact ? 'px-2 py-1 text-[11px]' : 'px-2.5 py-1 text-xs'
      }`}
      title="Install Mobile App / Add to Home Screen"
    >
      <span className="material-symbols-outlined text-[16px] text-[#60a5fa]">smartphone</span>
      <span>Install PWA</span>
    </button>
  );
};

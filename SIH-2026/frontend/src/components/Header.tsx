import React, { useState } from 'react';
import { ScreenType } from '../types';
import { useAuth } from '../contexts/AuthContext';
import { useI18n, Language } from '../contexts/I18nContext';
import { CheckpointSwitcher } from './CheckpointSwitcher';

interface HeaderProps {
  currentScreen: ScreenType;
  onNavigate: (screen: ScreenType) => void;
  scansCount: number;
  isMobileMenuOpen?: boolean;
  onToggleMobileMenu?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  currentScreen,
  onNavigate,
  scansCount,
  isMobileMenuOpen,
  onToggleMobileMenu,
}) => {
  const { user, checkpoint, logout, isAdmin } = useAuth();
  const { t, lang, setLang } = useI18n();
  const [showProfileMenu, setShowProfileMenu] = useState(false);

  const roleLabel = user?.role ? t(`role.${user.role.toLowerCase()}`) : '';

  return (
    <header className="sticky top-0 z-30 bg-[#0c1017] border-b border-[#1b2230] px-4 py-2.5 shadow-md">
      <div className="max-w-[1920px] mx-auto flex items-center justify-between gap-4">
        <div className="flex items-center gap-2 sm:gap-3">
          <button
            onClick={onToggleMobileMenu}
            className="lg:hidden p-1.5 rounded-lg text-[#94a3b8] hover:text-white hover:bg-[#182133] transition-colors cursor-pointer"
            aria-label="Toggle navigation menu"
          >
            <span className="material-symbols-outlined text-[22px]">
              {isMobileMenuOpen ? 'close' : 'menu'}
            </span>
          </button>

          <button
            onClick={() => onNavigate('overview')}
            className="flex items-center gap-2.5 text-left focus:outline-hidden group cursor-pointer"
          >
            <img
              src="/icon.svg"
              alt="PEHCHAAN Emblem"
              className="w-8 h-8 object-contain rounded-sm"
            />
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-white text-[15px] tracking-tight group-hover:text-[#60a5fa] transition-colors">
                  {t('app.name')}
                </span>
                <span className="px-1.5 py-0.5 text-[10px] font-semibold bg-[#182133] text-[#79a8ff] border border-[#23314d] rounded-sm tracking-wide">
                  SIH 26188
                </span>
              </div>
              <p className="text-[11px] text-[#8a94a6] leading-none mt-0.5">
                {t('app.subtitle')}
              </p>
            </div>
          </button>

          {isAdmin && (
            <div className="hidden xl:flex items-center gap-2 ml-4 pl-4 border-l border-[#1b2230] text-[11px]">
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[#092314] text-[#4ade80] font-medium border border-[#166534]/60">
                <span className="w-1.5 h-1.5 rounded-full bg-[#22c55e] animate-pulse"></span>
                OCR: Tesseract
              </span>
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[#092314] text-[#4ade80] font-medium border border-[#166534]/60">
                <span className="w-1.5 h-1.5 rounded-full bg-[#22c55e] animate-pulse"></span>
                Face: OpenCV+ORB
              </span>
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-[#092314] text-[#4ade80] font-medium border border-[#166534]/60">
                <span className="w-1.5 h-1.5 rounded-full bg-[#22c55e] animate-pulse"></span>
                Forensics: ELA/ORB
              </span>
            </div>
          )}

          {checkpoint && (
            <div className="ml-2 pl-2 sm:ml-3 sm:pl-3 border-l border-[#1b2230]">
              <CheckpointSwitcher />
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden sm:flex items-center gap-1.5 text-xs text-[#94a3b8] bg-[#141b28] px-2.5 py-1 rounded-md border border-[#222c3e]">
            <span className="material-symbols-outlined text-[16px] text-[#60a5fa]">fact_check</span>
            <span>{t('header.scans_today')}:</span>
            <span className="font-semibold text-white font-mono">{scansCount}</span>
          </div>

          <select
            value={lang}
            onChange={(e) => setLang(e.target.value as Language)}
            className="hidden sm:block text-[11px] bg-[#141b28] border border-[#222c3e] text-[#94a3b8] px-2 py-1 rounded-md focus:outline-none focus:border-[#2563eb] cursor-pointer"
          >
            <option value="en">EN</option>
            <option value="hi">HI</option>
            <option value="ne">NE</option>
          </select>

          <div className="h-6 w-px bg-[#1b2230] hidden sm:block"></div>

          <div className="relative">
            <button
              onClick={() => setShowProfileMenu(!showProfileMenu)}
              className="flex items-center gap-2.5 p-1 pr-2 rounded-lg hover:bg-[#182133] transition-colors text-left cursor-pointer"
            >
              <span className="w-7 h-7 rounded-full bg-[#1e3a5f] border border-[#2b3952] flex items-center justify-center">
                <span className="material-symbols-outlined text-[16px] text-[#60a5fa]">person</span>
              </span>
              <div className="hidden md:block leading-tight">
                <div className="text-xs font-semibold text-white">
                  {user?.name || 'User'}
                  {user?.offline && (
                    <span
                      className="ml-2 px-1.5 py-0.5 rounded bg-[#4a3200] text-[#ffd27a] text-[10px] font-semibold"
                      title="The database is unreachable. You were verified from this machine's sealed copy; scans are queued and will sync."
                    >
                      Offline sign-in
                    </span>
                  )}
                </div>
                <div className="text-[10px] text-[#8a94a6]">{roleLabel}</div>
              </div>
              <span className="material-symbols-outlined text-[16px] text-[#717785]">expand_more</span>
            </button>

            {showProfileMenu && (
              <div className="absolute right-0 mt-2 w-56 bg-[#101522] rounded-lg shadow-2xl border border-[#242f44] py-1 text-xs z-50">
                <div className="px-3 py-2 border-b border-[#242f44] bg-[#141b2a]">
                  <p className="font-semibold text-white">{user?.name}</p>
                  <p className="text-[10px] font-mono text-[#8a94a6]">{user?.email}</p>
                  <p className="text-[10px] text-[#60a5fa] mt-0.5">{roleLabel}</p>
                </div>
                <button
                  onClick={() => {
                    setShowProfileMenu(false);
                    logout();
                  }}
                  className="w-full text-left px-3 py-2 hover:bg-[#192236] flex items-center gap-2 text-[#cbd5e1] hover:text-white transition-colors cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[16px] text-[#94a3b8]">logout</span>
                  <span>{t('header.logout')}</span>
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};

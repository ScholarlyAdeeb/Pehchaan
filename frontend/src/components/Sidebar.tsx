import React from 'react';
import { ScreenType } from '../types';
import { useAuth } from '../contexts/AuthContext';
import { useI18n } from '../contexts/I18nContext';

interface SidebarProps {
  currentScreen: ScreenType;
  onNavigate: (screen: ScreenType) => void;
  isMobileOpen?: boolean;
  onCloseMobile?: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  currentScreen,
  onNavigate,
  isMobileOpen = false,
  onCloseMobile,
}) => {
  const { user, isAdmin, isOfficer } = useAuth();
  const { t } = useI18n();
  const role = user?.role;

  const allOperationalNav = [
    { id: 'overview', label: t('nav.overview'), icon: 'grid_view', roles: ['OFFICER', 'POST_INCHARGE', 'ADMIN'] },
    { id: 'new-scan', label: t('nav.new_scan'), icon: 'document_scanner', roles: ['OFFICER', 'ADMIN'] },
    { id: 'screening-report', label: t('nav.screening_report'), icon: 'assignment', roles: ['OFFICER', 'POST_INCHARGE', 'ADMIN'] },
    { id: 'audit-trail', label: t('nav.audit_trail'), icon: 'history_edu', roles: ['POST_INCHARGE', 'ADMIN'] },
    { id: 'system-health-and-docs', label: t('nav.system_health'), icon: 'terminal', roles: ['ADMIN'] },
  ];

  const allAdminNav = [
    { id: 'admin-portal', label: t('nav.admin_portal'), icon: 'security', roles: ['ADMIN'] },
    { id: 'officer-status', label: t('nav.officer_status'), icon: 'groups', roles: ['POST_INCHARGE', 'ADMIN'] },
    { id: 'system-logs', label: t('nav.system_logs'), icon: 'event_note', roles: ['ADMIN'] },
    { id: 'security', label: 'Security & trust', icon: 'shield_lock', roles: ['ADMIN'] },
  ];

  const operationalNav = allOperationalNav.filter(item => role && item.roles.includes(role));
  const adminNav = allAdminNav.filter(item => role && item.roles.includes(role));

  const handleItemClick = (screen: ScreenType) => {
    onNavigate(screen);
    if (onCloseMobile) onCloseMobile();
  };

  const navContent = (
    <div className="flex flex-col justify-between h-full py-4 px-3">
      <div className="space-y-6">
        <div>
          <div className="px-3 mb-2 text-[10px] font-bold tracking-wider text-[#5a677d] uppercase font-mono">
            {t('nav.operational')}
          </div>
          <nav className="space-y-1">
            {operationalNav.map((item) => {
              const isActive = currentScreen === item.id;
              return (
                <button
                  key={item.id}
                  onClick={() => handleItemClick(item.id as ScreenType)}
                  className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-all cursor-pointer ${
                    isActive
                      ? 'bg-[#0059b5] hover:bg-[#0050a3] text-white shadow-md shadow-blue-950/40 font-semibold border border-[#2563eb]/40'
                      : 'text-[#94a3b8] hover:text-white hover:bg-[#151d2c]'
                  }`}
                >
                  <span
                    className={`material-symbols-outlined text-[18px] ${
                      isActive ? 'text-white' : 'text-[#64748b]'
                    }`}
                  >
                    {item.icon}
                  </span>
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        </div>

        {adminNav.length > 0 && (
          <div>
            <div className="px-3 mb-2 text-[10px] font-bold tracking-wider text-[#5a677d] uppercase font-mono">
              {t('nav.administrative')}
            </div>
            <nav className="space-y-1">
              {adminNav.map((item) => {
                const isActive = currentScreen === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => handleItemClick(item.id as ScreenType)}
                    className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs font-medium transition-all cursor-pointer ${
                      isActive
                        ? 'bg-[#0059b5] hover:bg-[#0050a3] text-white shadow-md shadow-blue-950/40 font-semibold border border-[#2563eb]/40'
                        : 'text-[#94a3b8] hover:text-white hover:bg-[#151d2c]'
                    }`}
                  >
                    <span
                      className={`material-symbols-outlined text-[18px] ${
                        isActive ? 'text-white' : 'text-[#64748b]'
                      }`}
                    >
                      {item.icon}
                    </span>
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </nav>
          </div>
        )}
      </div>

      {!isOfficer && (
        <div className="bg-[#111723] border border-[#202b3e] p-3 rounded-xl text-xs shadow-md mt-6">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-[#7d8b9f]">Engine v1.4.2 ENCLAVE</span>
            <span className="w-2 h-2 rounded-full bg-[#22c55e] shadow-[0_0_8px_rgba(34,197,94,0.6)]"></span>
          </div>
          <div className="text-[11px] font-semibold text-white mt-1">All 4 AI Engines Active</div>
          <p className="text-[10px] text-[#8a94a6] mt-0.5">SSB Sentry Layer</p>
        </div>
      )}
    </div>
  );

  return (
    <>
      <aside className="hidden lg:flex w-64 shrink-0 bg-[#0c1017] border-r border-[#1b2230] flex-col justify-between min-h-[calc(100vh-100px)]">
        {navContent}
      </aside>

      {isMobileOpen && (
        <div className="lg:hidden fixed inset-0 z-40 flex">
          <div
            className="fixed inset-0 bg-black/60 backdrop-blur-xs transition-opacity"
            onClick={onCloseMobile}
          />
          <div className="relative w-72 max-w-[85vw] bg-[#0c1017] border-r border-[#1b2230] h-full shadow-2xl z-50 flex flex-col">
            <div className="p-3 border-b border-[#1b2230] flex items-center justify-between">
              <span className="text-xs font-bold font-mono text-[#94a3b8]">PORTAL NAVIGATION</span>
              <button
                onClick={onCloseMobile}
                className="p-1 rounded-lg text-[#94a3b8] hover:text-white hover:bg-[#182133]"
              >
                <span className="material-symbols-outlined text-[20px]">close</span>
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              {navContent}
            </div>
          </div>
        </div>
      )}
    </>
  );
};

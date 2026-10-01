import React from 'react';
import { ScreenType } from '../types';
import { useAuth } from '../contexts/AuthContext';

interface MobileBottomNavProps {
  currentScreen: ScreenType;
  onNavigate: (screen: ScreenType) => void;
  onOpenMobileMenu: () => void;
}

export const MobileBottomNav: React.FC<MobileBottomNavProps> = ({
  currentScreen,
  onNavigate,
  onOpenMobileMenu,
}) => {
  const { user } = useAuth();
  const role = user?.role;

  const allItems = [
    { id: 'overview', label: 'Overview', icon: 'grid_view', roles: ['OFFICER', 'POST_INCHARGE', 'ADMIN'] },
    { id: 'new-scan', label: 'New Scan', icon: 'document_scanner', highlight: true, roles: ['OFFICER', 'ADMIN'] },
    { id: 'screening-report', label: 'Report', icon: 'assignment', roles: ['OFFICER', 'POST_INCHARGE', 'ADMIN'] },
    { id: 'audit-trail', label: 'Audit', icon: 'history_edu', roles: ['POST_INCHARGE', 'ADMIN'] },
  ];

  const items = allItems.filter(item => role && item.roles.includes(role));

  return (
    <nav aria-label="Mobile quick actions" className="lg:hidden fixed bottom-0 left-0 right-0 z-30 bg-[#0c1017]/95 backdrop-blur-md border-t border-[#1b2230] px-2 py-1.5 flex items-center justify-around shadow-2xl">
      {items.map((item) => {
        const isActive = currentScreen === item.id;
        return (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id as ScreenType)}
            className={`flex flex-col items-center justify-center py-1 px-3 rounded-lg transition-all cursor-pointer ${
              item.highlight && !isActive
                ? 'text-[#60a5fa]'
                : isActive
                ? 'text-white bg-[#0059b5]/30 font-semibold'
                : 'text-[#8a94a6] hover:text-[#cbd5e1]'
            }`}
          >
            <span
              className={`material-symbols-outlined text-[20px] ${
                item.highlight && !isActive ? 'text-[#3b82f6]' : isActive ? 'text-[#60a5fa]' : ''
              }`}
            >
              {item.icon}
            </span>
            <span className="text-[10px] mt-0.5">{item.label}</span>
          </button>
        );
      })}

      <button
        onClick={onOpenMobileMenu}
        className="flex flex-col items-center justify-center py-1 px-3 rounded-lg text-[#8a94a6] hover:text-[#cbd5e1] cursor-pointer"
      >
        <span className="material-symbols-outlined text-[20px]">menu</span>
        <span className="text-[10px] mt-0.5">More</span>
      </button>
    </nav>
  );
};

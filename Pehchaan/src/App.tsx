import React, { useState, useCallback, useEffect } from 'react';
import { ScreenType, ScreeningRecord } from './types';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { I18nProvider } from './contexts/I18nContext';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { LoginView } from './components/LoginView';
import { CheckpointSelector } from './components/CheckpointSelector';
import { OverviewView } from './components/OverviewView';
import { NewScanView } from './components/NewScanView';
import { ScreeningReportView } from './components/ScreeningReportView';
import { AuditTrailView } from './components/AuditTrailView';
import { SystemHealthDocsView } from './components/SystemHealthDocsView';
import { AdminPortalView } from './components/AdminPortalView';
import { OfficerStatusView } from './components/OfficerStatusView';
import { SystemLogsView } from './components/SystemLogsView';
import { SecurityView } from './components/SecurityView';
import { ChangePasswordView } from './components/ChangePasswordView';
import { RemoteLocationSyncBar } from './components/RemoteLocationSyncBar';
import { MobileBottomNav } from './components/MobileBottomNav';
import { PrivacyPolicyView } from './components/PrivacyPolicyView';
import { TermsView } from './components/TermsView';
import { NotFoundView } from './components/NotFoundView';
import { CookieConsent } from './components/CookieConsent';
import {
  fetchScansFromNeon,
} from './services/neonSyncService';
import { trackPageView } from './services/analytics';

type PageRoute = 'app' | 'privacy' | 'terms' | 'not-found';

const KNOWN_SCREENS: ScreenType[] = [
  'overview',
  'new-scan',
  'screening-report',
  'audit-trail',
  'system-health-and-docs',
  'admin-portal',
  'officer-status',
  'system-logs',
  'security',
];

interface RouteState {
  page: PageRoute;
  screen: ScreenType;
}

/**
 * Map a pathname onto the app's screen state. The app keeps its screen in
 * React state rather than in a router, so the URL is only ever a mirror of
 * that state - but it has to be a *faithful* mirror, otherwise a mistyped or
 * stale URL silently lands the officer on the overview dashboard instead of
 * telling them the page does not exist.
 */
function parsePath(pathname: string): RouteState {
  const path = pathname.replace(/\/+$/, '') || '/';
  if (path === '/') return { page: 'app', screen: 'overview' };
  if (path === '/privacy') return { page: 'privacy', screen: 'overview' };
  if (path === '/terms') return { page: 'terms', screen: 'overview' };
  const segment = path.slice(1);
  if ((KNOWN_SCREENS as string[]).includes(segment)) {
    return { page: 'app', screen: segment as ScreenType };
  }
  return { page: 'not-found', screen: 'overview' };
}

function pathForScreen(screen: ScreenType): string {
  return screen === 'overview' ? '/' : `/${screen}`;
}

function AuthenticatedApp({
  screen,
  onNavigate,
  onNavigatePage,
}: {
  screen: ScreenType;
  onNavigate: (path: string) => void;
  onNavigatePage: (p: PageRoute) => void;
}) {
  const { user, checkpoint, isAuthenticated, isLoading, isAdmin, hasRole, token } = useAuth();
  const [records, setRecords] = useState<ScreeningRecord[]>([]);
  const [selectedRecord, setSelectedRecord] = useState<ScreeningRecord | null>(null);
  const [scansCount, setScansCount] = useState<number>(0);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [recordsLoaded, setRecordsLoaded] = useState(false);

  const loadNeonRecords = useCallback(async () => {
    if (!token) return;
    try {
      const serverRecords = await fetchScansFromNeon(token);
      setRecords(serverRecords);
      setScansCount(serverRecords.length);
      if (serverRecords[0] && !selectedRecord) {
        setSelectedRecord(serverRecords[0]);
      }
      setRecordsLoaded(true);
    } catch {
      setRecordsLoaded(true);
    }
  }, [token, selectedRecord]);

  React.useEffect(() => {
    if (isAuthenticated && checkpoint && !recordsLoaded) {
      loadNeonRecords();
    }
  }, [isAuthenticated, checkpoint, recordsLoaded, loadNeonRecords]);

  if (isLoading) {
    return (
      <div className="min-h-screen bg-[#0c1017] flex items-center justify-center">
        <div className="text-[#8a94a6] text-sm">Loading...</div>
      </div>
    );
  }

  if (!isAuthenticated) return <LoginView onNavigatePage={onNavigatePage} />;
  if (user?.mustChangePassword) return <ChangePasswordView />;
  if (!checkpoint) return <CheckpointSelector />;

  // The server has already analysed, hashed, stored and audited the scan.
  const handleAddRecord = (newRecord: ScreeningRecord) => {
    setRecords((prev) => [newRecord, ...prev.filter((r) => r.id !== newRecord.id)]);
    setSelectedRecord(newRecord);
    setScansCount((prev) => prev + 1);
  };

  const canAccess = (target: ScreenType): boolean => {
    if (isAdmin) return true;
    const officerScreens: ScreenType[] = ['overview', 'new-scan', 'screening-report'];
    const inchargeScreens: ScreenType[] = ['overview', 'officer-status', 'screening-report', 'audit-trail'];
    if (user?.role === 'OFFICER') return officerScreens.includes(target);
    if (user?.role === 'POST_INCHARGE') return inchargeScreens.includes(target);
    return false;
  };

  const safeNavigate = (next: ScreenType) => {
    if (canAccess(next)) {
      onNavigate(pathForScreen(next));
      setIsMobileMenuOpen(false);
      trackPageView(next);
    }
  };

  // A URL the officer's role does not cover, or a report with nothing to
  // show, renders the 404 page rather than an unexplained blank panel.
  const blockedByRole = !canAccess(screen);
  const reportMissingRecord =
    screen === 'screening-report' && recordsLoaded && !selectedRecord;
  const showNotFound = blockedByRole || reportMissingRecord;

  return (
    <div className="min-h-screen bg-[#0c1017] text-[#f1f5f9] flex flex-col antialiased selection:bg-[#2563eb]/40">
      <Header
        currentScreen={screen}
        onNavigate={safeNavigate}
        scansCount={scansCount}
        isMobileMenuOpen={isMobileMenuOpen}
        onToggleMobileMenu={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
      />

      {hasRole('ADMIN') && <RemoteLocationSyncBar onSyncCompleted={loadNeonRecords} />}

      <div className="flex-1 flex overflow-hidden relative">
        <Sidebar
          currentScreen={screen}
          onNavigate={safeNavigate}
          isMobileOpen={isMobileMenuOpen}
          onCloseMobile={() => setIsMobileMenuOpen(false)}
        />

        <main className="flex-1 overflow-y-auto bg-[#faf8fe] text-[#1a1b1f] pb-16 lg:pb-0">
          {showNotFound ? (
            <NotFoundView onGoHome={() => onNavigate('/')} />
          ) : (
            <>
              {screen === 'overview' && (
                <OverviewView
                  records={records}
                  onNavigate={safeNavigate}
                  onSelectRecord={setSelectedRecord}
                />
              )}

              {screen === 'new-scan' && (
                <NewScanView
                  onNavigate={safeNavigate}
                  onAddRecord={handleAddRecord}
                  onSelectRecord={setSelectedRecord}
                />
              )}

              {screen === 'screening-report' && selectedRecord && (
                <ScreeningReportView
                  currentRecord={selectedRecord}
                  records={records}
                  onSelectRecord={setSelectedRecord}
                  onNavigate={safeNavigate}
                />
              )}

              {screen === 'audit-trail' && (
                <AuditTrailView
                  records={records}
                  onSelectRecord={setSelectedRecord}
                  onNavigate={safeNavigate}
                />
              )}

              {screen === 'system-health-and-docs' && <SystemHealthDocsView />}

              {screen === 'admin-portal' && (
                <AdminPortalView onNavigate={safeNavigate} records={records} />
              )}

              {screen === 'officer-status' && (
                <OfficerStatusView records={records} onNavigate={safeNavigate} />
              )}

              {screen === 'security' && <SecurityView records={records} />}

              {screen === 'system-logs' && <SystemLogsView />}
            </>
          )}
        </main>
      </div>

      <MobileBottomNav
        currentScreen={screen}
        onNavigate={safeNavigate}
        onOpenMobileMenu={() => setIsMobileMenuOpen(true)}
      />
    </div>
  );
}

export default function App() {
  const [route, setRoute] = useState<RouteState>(() =>
    parsePath(window.location.pathname),
  );

  // Keep state and URL in step when the user moves through history.
  useEffect(() => {
    const onPopState = () => setRoute(parsePath(window.location.pathname));
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  const go = useCallback((path: string) => {
    if (window.location.pathname !== path) {
      window.history.pushState(null, '', path);
    }
    setRoute(parsePath(path));
  }, []);

  return (
    <I18nProvider>
      <AuthProvider>
        {route.page === 'privacy' && <PrivacyPolicyView onBack={() => go('/')} />}
        {route.page === 'terms' && <TermsView onBack={() => go('/')} />}
        {route.page === 'not-found' && <NotFoundView onGoHome={() => go('/')} />}
        {route.page === 'app' && (
          <AuthenticatedApp
            screen={route.screen}
            onNavigate={go}
            onNavigatePage={(p) => go(p === 'privacy' ? '/privacy' : '/terms')}
          />
        )}
        <CookieConsent onPrivacyClick={() => go('/privacy')} />
      </AuthProvider>
    </I18nProvider>
  );
}

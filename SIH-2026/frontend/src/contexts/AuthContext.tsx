import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { AuthUser, Checkpoint, UserRole } from '../types';
import { installApiFetch, SESSION_EXPIRED_EVENT, SESSION_MARKER } from '../services/apiFetch';

// Must run before any component fetches: adds the CSRF header and renews expired sessions.
installApiFetch();

interface AuthContextType {
  user: AuthUser | null;
  token: string | null;
  checkpoint: Checkpoint | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  logout: () => void;
  applySession: (token: string | undefined, user: AuthUser) => void;
  selectCheckpoint: (cp: Checkpoint | null) => void;
  isOfficer: boolean;
  isPostIncharge: boolean;
  isAdmin: boolean;
  hasRole: (...roles: UserRole[]) => boolean;
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  token: null,
  checkpoint: null,
  isAuthenticated: false,
  isLoading: true,
  login: async () => ({ ok: false }),
  logout: () => {},
  applySession: () => {},
  selectCheckpoint: () => {},
  isOfficer: false,
  isPostIncharge: false,
  isAdmin: false,
  hasRole: () => false,
});

export const useAuth = () => useContext(AuthContext);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [checkpoint, setCheckpoint] = useState<Checkpoint | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const endSession = useCallback(() => {
    setUser(null);
    setToken(null);
    setCheckpoint(null);
    localStorage.removeItem('pehchaan_checkpoint');
  }, []);

  useEffect(() => {
    // Older builds kept the JWT here, readable by any script on the page. The
    // session is now an HttpOnly cookie; make sure no old copy lingers.
    localStorage.removeItem('pehchaan_token');

    // If the cookies hold a live session (or one that can be renewed) this
    // succeeds; the fetch wrapper renews an expired access token on its own.
    fetch('/api/auth/me')
      .then((res) => (res.ok ? res.json() : Promise.reject()))
      .then((data) => {
        setUser(data.user);
        setToken(SESSION_MARKER);
        const savedCp = localStorage.getItem('pehchaan_checkpoint');
        if (savedCp) {
          try { setCheckpoint(JSON.parse(savedCp)); } catch {}
        }
      })
      .catch(() => localStorage.removeItem('pehchaan_checkpoint'))
      .finally(() => setIsLoading(false));

    window.addEventListener(SESSION_EXPIRED_EVENT, endSession);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, endSession);
  }, [endSession]);

  const login = useCallback(async (email: string, password: string) => {
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        return { ok: false, error: data.error || 'Login failed' };
      }
      setUser(data.user);
      setToken(SESSION_MARKER);
      return { ok: true };
    } catch {
      return { ok: false, error: 'Network error' };
    }
  }, []);

  // `_token` is kept for callers written against the old signature; the
  // server has already replaced the session cookie.
  const applySession = useCallback((_token: string | undefined, newUser: AuthUser) => {
    setToken(SESSION_MARKER);
    setUser(newUser);
  }, []);

  const logout = useCallback(() => {
    fetch('/api/auth/logout', { method: 'POST' }).catch(() => undefined); // revokes the refresh token server-side
    endSession();
  }, [endSession]);

  const selectCheckpoint = useCallback((cp: Checkpoint | null) => {
    setCheckpoint(cp);
    if (cp) {
      localStorage.setItem('pehchaan_checkpoint', JSON.stringify(cp));
    } else {
      localStorage.removeItem('pehchaan_checkpoint');
    }
  }, []);

  const role = user?.role;
  const isOfficer = role === 'OFFICER';
  const isPostIncharge = role === 'POST_INCHARGE';
  const isAdmin = role === 'ADMIN';
  const hasRole = useCallback((...roles: UserRole[]) => !!role && roles.includes(role), [role]);

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        checkpoint,
        isAuthenticated: !!user && !!token,
        isLoading,
        login,
        logout,
        applySession,
        selectCheckpoint,
        isOfficer,
        isPostIncharge,
        isAdmin,
        hasRole,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

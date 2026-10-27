import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, AUTH_EXPIRED_EVENT, clearSession, connectLive, getRole, getToken, isRemembered, setSession, type Authorization, type Overview } from "./api";

// ---------------------------------------------------------------- auth

interface AuthCtx {
  token: string | null;
  role: string | null;
  login: (u: string, p: string, remember?: boolean) => Promise<void>;
  logout: () => void;
}
const AuthContext = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(getToken());
  const [role, setRole] = useState<string | null>(getRole());
  useEffect(() => {
    const onExpired = () => {
      setToken(null);
      setRole(null);
    };
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, []);
  // A remembered session is renewed on every start and twice a day, so it only ends when the user signs out
  // (or does not open the app for 30 days). Network errors keep the current token; a 401 signs out as usual.
  useEffect(() => {
    if (!token || !isRemembered()) return;
    const renew = () =>
      api
        .refreshSession()
        .then((r) => {
          if (r?.token && isRemembered()) setSession(r.token, r.role ?? "", true, false);
        })
        .catch(() => undefined);
    renew();
    const t = window.setInterval(renew, 12 * 3600 * 1000);
    return () => window.clearInterval(t);
  }, [token]);
  const login = useCallback(async (u: string, p: string, remember = false) => {
    const r = await api.login(u, p, remember);
    if (!r || typeof r.token !== "string") throw new Error("Login response missing token");
    setSession(r.token, r.role ?? "", remember);
    setToken(r.token);
    setRole(r.role ?? "");
  }, []);
  const logout = useCallback(() => {
    clearSession();
    setToken(null);
    setRole(null);
  }, []);
  return <AuthContext.Provider value={{ token, role, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(AuthContext);
  if (!c) throw new Error("AuthProvider missing");
  return c;
}

// ---------------------------------------------------------------- live status

interface LiveCtx {
  overview: Overview | null;
  overviewError: string | null;
  overviewAt: Date | null;
  auth: Authorization | null;
  authError: string | null;
  wsConnected: boolean;
  refresh: () => void;
}
const LiveContext = createContext<LiveCtx | null>(null);

/** Overview arrives over /ws/live; REST polling is the fallback while the socket is down. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [overviewError, setOverviewError] = useState<string | null>(null);
  const [overviewAt, setOverviewAt] = useState<Date | null>(null);
  const [auth, setAuth] = useState<Authorization | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [wsConnected, setWs] = useState(false);

  const loadOverview = useCallback(() => {
    api
      .overview()
      .then((o) => {
        setOverview(o);
        setOverviewError(null);
        setOverviewAt(new Date());
      })
      .catch((e: Error) => setOverviewError(e.message));
  }, []);
  const loadAuth = useCallback(() => {
    api
      .authorization()
      .then((a) => {
        setAuth(a);
        setAuthError(null);
      })
      .catch((e: Error) => {
        setAuth(null);
        setAuthError(e.message);
      });
  }, []);
  const refresh = useCallback(() => {
    loadOverview();
    loadAuth();
  }, [loadOverview, loadAuth]);

  useEffect(() => {
    refresh();
    const close = connectLive(
      (m) => {
        const { type: _t, ...rest } = m;
        void _t;
        setOverview((prev) => ({ ...(prev ?? ({} as Overview)), ...rest }) as Overview);
        setOverviewError(null);
        setOverviewAt(new Date());
      },
      setWs,
    );
    const a = window.setInterval(loadAuth, 30000);
    return () => {
      close();
      window.clearInterval(a);
    };
  }, [refresh, loadAuth]);

  useEffect(() => {
    if (wsConnected) return;
    const t = window.setInterval(loadOverview, 10000);
    return () => window.clearInterval(t);
  }, [wsConnected, loadOverview]);

  return <LiveContext.Provider value={{ overview, overviewError, overviewAt, auth, authError, wsConnected, refresh }}>{children}</LiveContext.Provider>;
}

export function useLive(): LiveCtx {
  const c = useContext(LiveContext);
  if (!c) throw new Error("LiveProvider missing");
  return c;
}

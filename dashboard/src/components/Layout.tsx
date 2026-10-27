import { Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api";
import { fmtNum, fmtTime, useApi } from "../lib";
import { useAuth, useLive } from "../state";
import { MAIN_NAV, NAV_GROUPS, MOBILE_TABS, navLabel } from "../nav";
import { useTheme } from "../theme";
import { Icon } from "./icons";
import { PageBoundary } from "./PageBoundary";
import ProfitAlerts from "./ProfitAlerts";
import { ConfirmDialog } from "./ui";

function RealTradingBanner() {
  const { overview, overviewError, auth, authError, refresh } = useLive();
  const [dlg, setDlg] = useState<"stop" | "release" | null>(null);

  const enabled = auth?.real_trading_enabled ?? overview?.real_trading_enabled;
  const known = enabled !== undefined && enabled !== null;
  const estop = overview?.emergency_stop === true;
  const expiry = auth?.grant?.expires_at;

  let cls = "banner-unknown";
  let text = "REAL TRADING STATUS UNKNOWN - status endpoint unavailable";
  if (known && enabled) {
    cls = "banner-enabled";
    text = `REAL TRADING ENABLED${expiry ? ` - grant expires ${fmtTime(expiry)}` : " - grant expiry not reported"}`;
  } else if (known) {
    cls = "banner-disabled";
    text = "REAL TRADING DISABLED";
  }

  return (
    <div className={`banner ${cls}`} role="status" aria-live="polite">
      <div className="banner-text">
        <span className="banner-dot" aria-hidden="true" />
        <strong>{text}</strong>
        <span className="banner-meta">
          {estop && <span className="pill pill-bad">EMERGENCY STOP ACTIVE</span>}
          {overview && <span className="pill pill-neutral">Demo exec: {overview.demo_execution_enabled ? "on" : "off"}</span>}
          {(overviewError || authError) && !known && <span className="small mono">{overviewError ?? authError}</span>}
        </span>
      </div>
      <div className="banner-actions">
        {estop && (
          <button className="btn btn-small btn-ghost" onClick={() => setDlg("release")}>
            Release
          </button>
        )}
        <button className="btn btn-danger estop" onClick={() => setDlg("stop")} aria-label="Emergency stop">
          <Icon name="risk" size={16} />
          <span className="estop-long">EMERGENCY STOP</span>
          <span className="estop-short">STOP</span>
        </button>
      </div>
      <ConfirmDialog
        open={dlg === "stop"}
        title="Activate emergency stop?"
        danger
        withReason
        confirmLabel="Activate emergency stop"
        body={<p>This asks the backend to halt all new entries across every engine and close or block open exposure as configured in risk settings. The action is audited.</p>}
        onConfirm={async (reason) => {
          await api.emergencyStop(true, reason || "dashboard emergency stop");
          refresh();
        }}
        onClose={() => setDlg(null)}
      />
      <ConfirmDialog
        open={dlg === "release"}
        title="Release emergency stop?"
        withReason
        requireText="RELEASE"
        confirmLabel="Release"
        body={<p>Engines may resume according to their modes. Real trading still requires a valid owner grant.</p>}
        onConfirm={async (reason) => {
          await api.emergencyStop(false, reason || "dashboard release");
          refresh();
        }}
        onClose={() => setDlg(null)}
      />
    </div>
  );
}

function PriceTicker() {
  // Real ticks only: hidden until /api/market/state returns a tick.
  const st = useApi(api.market, [], 3000);
  const prev = useRef<number | null>(null);
  const [dir, setDir] = useState<"up" | "down" | "">("");
  const lt = st.data?.last_tick;
  useEffect(() => {
    if (!lt || typeof lt.bid !== "number") return;
    if (prev.current !== null && lt.bid !== prev.current) setDir(lt.bid > prev.current ? "up" : "down");
    prev.current = lt.bid;
  }, [lt?.bid]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!st.data || !lt) return null;
  return (
    <NavLink to="/market" className={`ticker ticker-${dir}`} title={`Last tick ${fmtTime(lt.time)} from ${st.data.broker}`}>
      <span className="ticker-sym">{st.data.symbol}</span>
      <span className="ticker-px">{fmtNum(lt.bid, 2)}</span>
      <span className="ticker-spread">spr {fmtNum(lt.spread, 2)}</span>
    </NavLink>
  );
}

const THEME_ICON = { dark: "moon", light: "sun", auto: "auto" } as const;

export default function Layout() {
  const { role, logout } = useAuth();
  const { wsConnected } = useLive();
  const [theme, cycleTheme] = useTheme();
  const [drawer, setDrawer] = useState(false);
  const loc = useLocation();
  useEffect(() => setDrawer(false), [loc.pathname]);
  const inAdvanced = !MAIN_NAV.some((i) => i.path === loc.pathname);
  const [advancedOpen, setAdvancedOpen] = useState(inAdvanced);
  useEffect(() => {
    if (inAdvanced) setAdvancedOpen(true);
  }, [inAdvanced]);

  return (
    <div className="app">
      <RealTradingBanner />
      <div className="body">
        <nav className={`sidebar ${drawer ? "open" : ""}`} aria-label="Main">
          <div className="sidebar-brand">
            <span className="brand-mark" aria-hidden="true">
              <Icon name="market" size={18} />
            </span>
            <span className="brand-name">
              Gold AI <small>Adaptive Agentic Scalper</small>
            </span>
          </div>
          <div className="nav-group">
            {MAIN_NAV.map((i) => (
              <NavLink key={i.path} to={i.path} end={i.path === "/"} className={({ isActive }) => `nav-link nav-main ${isActive ? "active" : ""}`}>
                <Icon name={i.icon} />
                <span>{i.label}</span>
              </NavLink>
            ))}
          </div>
          <details className="nav-advanced" open={advancedOpen} onToggle={(e) => setAdvancedOpen((e.target as HTMLDetailsElement).open)}>
            <summary>
              <Icon name="chevron" size={14} className="nav-chevron" />
              Advanced
            </summary>
            {NAV_GROUPS.map((g) => (
              <div key={g.title} className="nav-group">
                <div className="nav-group-title">{g.title}</div>
                {g.items.map((i) => (
                  <NavLink key={i.path} to={i.path} end className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
                    <Icon name={i.icon} />
                    <span>{i.label}</span>
                  </NavLink>
                ))}
              </div>
            ))}
          </details>
          <div className="sidebar-foot">
            {role && <span className="pill pill-neutral">{role}</span>}
            <button className="btn btn-small btn-ghost" onClick={logout}>
              <Icon name="logout" size={16} /> Sign out
            </button>
          </div>
        </nav>
        {drawer && <div className="scrim" onClick={() => setDrawer(false)} />}
        <div className="content">
          <header className="topbar">
            <button className="btn btn-icon menu-btn" onClick={() => setDrawer((d) => !d)} aria-label="Toggle navigation" aria-expanded={drawer}>
              <Icon name="more" size={20} />
            </button>
            <div className="topbar-title">
              <span className="brand-mark brand-mark-sm" aria-hidden="true">
                <Icon name="market" size={15} />
              </span>
              <span>{navLabel(loc.pathname) || "Gold AI"}</span>
            </div>
            <div className="topbar-right">
              <PriceTicker />
              <ProfitAlerts />
              <span className={`conn ${wsConnected ? "conn-on" : "conn-off"}`} title={wsConnected ? "Live status stream connected" : "Live stream down, polling every 10 s"}>
                <i />
                <span className="conn-label">{wsConnected ? "Live" : "Polling"}</span>
              </span>
              <button className="btn btn-icon" onClick={cycleTheme} aria-label={`Theme: ${theme}. Switch theme`} title={`Theme: ${theme}`}>
                <Icon name={THEME_ICON[theme]} />
              </button>
            </div>
          </header>
          <main className="main">
            <PageBoundary key={loc.pathname}>
              <Suspense fallback={<div className="state state-loading">Loading...</div>}>
                <Outlet />
              </Suspense>
            </PageBoundary>
          </main>
        </div>
      </div>
      <nav className="bottom-nav" aria-label="Quick">
        {MOBILE_TABS.map((i) => (
          <NavLink key={i.path} to={i.path} end={i.path === "/"} className={({ isActive }) => `bn-link ${isActive ? "active" : ""}`}>
            <Icon name={i.icon} size={20} />
            <span>{i.short}</span>
          </NavLink>
        ))}
        <button className={`bn-link ${drawer ? "active" : ""}`} onClick={() => setDrawer((d) => !d)}>
          <Icon name="more" size={20} />
          <span>More</span>
        </button>
      </nav>
    </div>
  );
}

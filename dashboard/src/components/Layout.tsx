import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api";
import { fmtTime } from "../lib";
import { useAuth, useLive } from "../state";
import { NAV_GROUPS, MOBILE_TABS } from "../nav";
import { ConfirmDialog } from "./ui";

function RealTradingBanner() {
  const { overview, overviewError, auth, authError, wsConnected, overviewAt, refresh } = useLive();
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
        <strong>{text}</strong>
        <span className="banner-meta">
          {estop && <span className="pill pill-bad">EMERGENCY STOP ACTIVE</span>}
          {overview && <span className="pill pill-neutral">Demo exec: {overview.demo_execution_enabled ? "on" : "off"}</span>}
          <span className={`pill ${wsConnected ? "pill-ok" : "pill-warn"}`} title={overviewAt ? `Last status ${overviewAt.toLocaleTimeString()}` : "No status received"}>
            {wsConnected ? "live" : "polling"}
          </span>
          {(overviewError || authError) && !known && <span className="small mono">{overviewError ?? authError}</span>}
        </span>
      </div>
      <div className="banner-actions">
        {estop && (
          <button className="btn btn-small" onClick={() => setDlg("release")}>
            Release
          </button>
        )}
        <button className="btn btn-danger estop" onClick={() => setDlg("stop")} aria-label="Emergency stop">
          EMERGENCY STOP
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

export default function Layout() {
  const { role, logout } = useAuth();
  const [drawer, setDrawer] = useState(false);
  const loc = useLocation();
  useEffect(() => setDrawer(false), [loc.pathname]);

  return (
    <div className="app">
      <RealTradingBanner />
      <div className="topbar">
        <button className="btn btn-icon menu-btn" onClick={() => setDrawer((d) => !d)} aria-label="Toggle navigation" aria-expanded={drawer}>
          <span className="hamburger" />
        </button>
        <div className="brand">
          <span className="brand-mark">Au</span>
          <span className="brand-name">Gold AI Adaptive Agentic Scalper</span>
        </div>
        <div className="topbar-right">
          {role && <span className="pill pill-neutral">{role}</span>}
          <button className="btn btn-small" onClick={logout}>
            Sign out
          </button>
        </div>
      </div>
      <div className="body">
        <nav className={`sidebar ${drawer ? "open" : ""}`} aria-label="Main">
          {NAV_GROUPS.map((g) => (
            <div key={g.title} className="nav-group">
              <div className="nav-group-title">{g.title}</div>
              {g.items.map((i) => (
                <NavLink key={i.path} to={i.path} end={i.path === "/"} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
                  {i.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        {drawer && <div className="scrim" onClick={() => setDrawer(false)} />}
        <main className="main">
          <Outlet />
        </main>
      </div>
      <nav className="bottom-nav" aria-label="Quick">
        {MOBILE_TABS.map((i) => (
          <NavLink key={i.path} to={i.path} end={i.path === "/"} className={({ isActive }) => `bn-link ${isActive ? "active" : ""}`}>
            {i.short}
          </NavLink>
        ))}
        <button className={`bn-link ${drawer ? "active" : ""}`} onClick={() => setDrawer((d) => !d)}>
          More
        </button>
      </nav>
    </div>
  );
}

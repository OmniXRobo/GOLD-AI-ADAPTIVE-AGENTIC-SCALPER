import { lazy, useState, type ComponentType } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Empty, PageHeader } from "./components/ui";
import LandingPage from "./pages/Landing";
import LoginPage from "./pages/Login";
import { nativeApp } from "./native";
import { LiveProvider, useAuth } from "./state";

const RELOAD_KEY = "goldai:chunk-reload";

/** After a redeploy the page scripts get new file names, so an app that stayed open asks for files that no
 *  longer exist (404). Reload once to pick up the new build; the flag stops a reload loop if it still fails. */
function reloadForNewBuild<M>(err: unknown): Promise<M> {
  let last = 0;
  try { last = Number(sessionStorage.getItem(RELOAD_KEY) || 0); } catch { /* storage blocked */ }
  if (Date.now() - last > 60_000) {
    try { sessionStorage.setItem(RELOAD_KEY, String(Date.now())); } catch { /* storage blocked */ }
    window.location.reload();
    return new Promise<M>(() => {});   // the page is going away
  }
  return Promise.reject(err);
}

/** Try a page script again once after a short wait: a busy server or a dropped mobile connection often recovers. */
function retryOnce<M>(load: () => Promise<M>): Promise<M> {
  return load()
    .catch(() => new Promise<M>((ok, fail) => window.setTimeout(() => load().then(ok, fail), 1500)))
    .catch((err) => reloadForNewBuild<M>(err));
}

// Each page group loads on first visit so the first screen paints quickly on phones.
function page<M extends Record<string, unknown>>(load: () => Promise<M>, name: keyof M) {
  return lazy(() => retryOnce(load).then((m) => ({ default: m[name] as ComponentType })));
}
const monitor = () => import("./pages/Monitor");
const control = () => import("./pages/Control");
const learning = () => import("./pages/Learning");
const memories = () => import("./pages/Memories");
const system = () => import("./pages/System");

const OverviewPage = page(() => import("./pages/Overview"), "default");
const HomePage = page(() => import("./pages/Home"), "default");
const AutopilotPage = page(() => import("./pages/Autopilot"), "default");
const AnalysisPage = page(() => import("./pages/Analysis"), "default");
const PracticePage = page(() => import("./pages/Practice"), "default");
const ResultsPage = page(() => import("./pages/Results"), "default");
const LearnPage = page(() => import("./pages/Learn"), "default");
const BrokersPage = page(monitor, "BrokersPage");
const MarketPage = page(monitor, "MarketPage");
const AgentPage = page(monitor, "AgentPage");
const IntelligencePage = page(monitor, "IntelligencePage");
const InstitutionalPage = page(monitor, "InstitutionalPage");
const NewsPage = page(monitor, "NewsPage");
const AuthorizationPage = page(control, "AuthorizationPage");
const ModesPage = page(control, "ModesPage");
const RiskPage = page(control, "RiskPage");
const SignalsPage = page(control, "SignalsPage");
const MaturityPage = page(learning, "MaturityPage");
const SelfHealingPage = page(learning, "SelfHealingPage");
const StrategiesPage = page(learning, "StrategiesPage");
const BacktestingPage = page(memories, "BacktestingPage");
const ForwardPage = page(memories, "ForwardPage");
const MemoryPage = page(memories, "MemoryPage");
const PerformancePage = page(memories, "PerformancePage");
const RealPage = page(memories, "RealPage");
const VirtualPage = page(memories, "VirtualPage");
const AuditPage = page(system, "AuditPage");
const BackupsPage = page(system, "BackupsPage");
const HealthPage = page(system, "HealthPage");
const SettingsPage = page(system, "SettingsPage");

function NotFound() {
  return (
    <>
      <PageHeader title="Not found" />
      <Empty>This page does not exist.</Empty>
    </>
  );
}

export default function App() {
  const { token } = useAuth();
  // The website shows a public front page first; the phone app goes straight to sign-in.
  const [signIn, setSignIn] = useState(nativeApp.available());
  if (!token) return signIn ? <LoginPage /> : <LandingPage onSignIn={() => setSignIn(true)} />;
  return (
    <LiveProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<HomePage />} />
          <Route path="autopilot" element={<AutopilotPage />} />
          <Route path="analysis" element={<AnalysisPage />} />
          <Route path="practice" element={<PracticePage />} />
          <Route path="results" element={<ResultsPage />} />
          <Route path="learn" element={<LearnPage />} />
          <Route path="overview" element={<OverviewPage />} />
          <Route path="brokers" element={<BrokersPage />} />
          <Route path="market" element={<MarketPage />} />
          <Route path="agent" element={<AgentPage />} />
          <Route path="intelligence" element={<IntelligencePage />} />
          <Route path="institutional" element={<InstitutionalPage />} />
          <Route path="news" element={<NewsPage />} />
          <Route path="backtesting" element={<BacktestingPage />} />
          <Route path="forward" element={<ForwardPage />} />
          <Route path="virtual" element={<VirtualPage />} />
          <Route path="real" element={<RealPage />} />
          <Route path="memory" element={<MemoryPage />} />
          <Route path="maturity" element={<MaturityPage />} />
          <Route path="strategies" element={<StrategiesPage />} />
          <Route path="self-healing" element={<SelfHealingPage />} />
          <Route path="risk" element={<RiskPage />} />
          <Route path="modes" element={<ModesPage />} />
          <Route path="signals" element={<SignalsPage />} />
          <Route path="performance" element={<PerformancePage />} />
          <Route path="health" element={<HealthPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="authorization" element={<AuthorizationPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="backups" element={<BackupsPage />} />
          <Route path="index.html" element={<Navigate to="/" replace />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </LiveProvider>
  );
}

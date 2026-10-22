import { lazy, type ComponentType } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Empty, PageHeader } from "./components/ui";
import LoginPage from "./pages/Login";
import { LiveProvider, useAuth } from "./state";

// Each page group loads on first visit so the first screen paints quickly on phones.
function page<M extends Record<string, unknown>>(load: () => Promise<M>, name: keyof M) {
  return lazy(() => load().then((m) => ({ default: m[name] as ComponentType })));
}
const monitor = () => import("./pages/Monitor");
const control = () => import("./pages/Control");
const learning = () => import("./pages/Learning");
const memories = () => import("./pages/Memories");
const system = () => import("./pages/System");

const OverviewPage = page(() => import("./pages/Overview"), "default");
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
  if (!token) return <LoginPage />;
  return (
    <LiveProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<OverviewPage />} />
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

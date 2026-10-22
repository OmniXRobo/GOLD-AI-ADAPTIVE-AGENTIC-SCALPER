import { Navigate, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Empty, PageHeader } from "./components/ui";
import { AgentPage, BrokersPage, InstitutionalPage, IntelligencePage, MarketPage, NewsPage } from "./pages/Monitor";
import { AuthorizationPage, ModesPage, RiskPage, SignalsPage } from "./pages/Control";
import { MaturityPage, SelfHealingPage, StrategiesPage } from "./pages/Learning";
import LoginPage from "./pages/Login";
import { BacktestingPage, ForwardPage, MemoryPage, PerformancePage, RealPage, VirtualPage } from "./pages/Memories";
import OverviewPage from "./pages/Overview";
import { AuditPage, BackupsPage, HealthPage, SettingsPage } from "./pages/System";
import { LiveProvider, useAuth } from "./state";

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

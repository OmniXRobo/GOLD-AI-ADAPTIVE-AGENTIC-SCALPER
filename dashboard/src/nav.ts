export interface NavItem {
  path: string;
  label: string;
  icon: string;
}

export const NAV_GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: "Monitor",
    items: [
      { path: "/", label: "Overview", icon: "overview" },
      { path: "/brokers", label: "Broker Connections", icon: "brokers" },
      { path: "/market", label: "Gold Live Market", icon: "market" },
      { path: "/agent", label: "AI Agent Status", icon: "agent" },
      { path: "/intelligence", label: "Market Intelligence", icon: "intelligence" },
      { path: "/institutional", label: "Institutional Intelligence", icon: "institutional" },
      { path: "/news", label: "Global News", icon: "news" },
    ],
  },
  {
    title: "Trading memories",
    items: [
      { path: "/backtesting", label: "Historical Backtesting", icon: "backtesting" },
      { path: "/forward", label: "Forward Validation", icon: "forward" },
      { path: "/virtual", label: "Live Virtual Trading", icon: "virtual" },
      { path: "/real", label: "Real Trading", icon: "real" },
      { path: "/memory", label: "AI Memory", icon: "memory" },
      { path: "/performance", label: "Performance Analytics", icon: "performance" },
    ],
  },
  {
    title: "Learning",
    items: [
      { path: "/maturity", label: "AI Maturity", icon: "maturity" },
      { path: "/strategies", label: "Strategy Versions", icon: "strategies" },
      { path: "/self-healing", label: "Self-Healing History", icon: "healing" },
    ],
  },
  {
    title: "Control",
    items: [
      { path: "/risk", label: "Risk Management", icon: "risk" },
      { path: "/modes", label: "Trading Modes", icon: "modes" },
      { path: "/signals", label: "Signals and Notifications", icon: "signals" },
      { path: "/authorization", label: "Owner Authorization", icon: "authorization" },
    ],
  },
  {
    title: "System",
    items: [
      { path: "/health", label: "System Health", icon: "health" },
      { path: "/settings", label: "Settings", icon: "settings" },
      { path: "/audit", label: "Audit Logs", icon: "audit" },
      { path: "/backups", label: "Backup and Recovery", icon: "backups" },
    ],
  },
];

export const MOBILE_TABS: (NavItem & { short: string })[] = [
  { path: "/", label: "Overview", short: "Overview", icon: "overview" },
  { path: "/market", label: "Gold Live Market", short: "Market", icon: "market" },
  { path: "/signals", label: "Signals and Notifications", short: "Signals", icon: "signals" },
  { path: "/virtual", label: "Live Virtual Trading", short: "Virtual", icon: "virtual" },
];

/** Page title for the current path, used by the header. */
export function navLabel(pathname: string): string {
  for (const g of NAV_GROUPS) for (const i of g.items) if (i.path === pathname) return i.label;
  return "";
}

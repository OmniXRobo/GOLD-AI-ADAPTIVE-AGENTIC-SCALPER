export interface NavItem {
  path: string;
  label: string;
}

export const NAV_GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: "Monitor",
    items: [
      { path: "/", label: "Overview" },
      { path: "/brokers", label: "Broker Connections" },
      { path: "/market", label: "Gold Live Market" },
      { path: "/agent", label: "AI Agent Status" },
      { path: "/intelligence", label: "Market Intelligence" },
      { path: "/institutional", label: "Institutional Intelligence" },
      { path: "/news", label: "Global News" },
    ],
  },
  {
    title: "Trading memories",
    items: [
      { path: "/backtesting", label: "Historical Backtesting" },
      { path: "/forward", label: "Forward Validation" },
      { path: "/virtual", label: "Live Virtual Trading" },
      { path: "/real", label: "Real Trading" },
      { path: "/memory", label: "AI Memory" },
      { path: "/performance", label: "Performance Analytics" },
    ],
  },
  {
    title: "Learning",
    items: [
      { path: "/maturity", label: "AI Maturity" },
      { path: "/strategies", label: "Strategy Versions" },
      { path: "/self-healing", label: "Self-Healing History" },
    ],
  },
  {
    title: "Control",
    items: [
      { path: "/risk", label: "Risk Management" },
      { path: "/modes", label: "Trading Modes" },
      { path: "/signals", label: "Signals and Notifications" },
      { path: "/authorization", label: "Owner Authorization" },
    ],
  },
  {
    title: "System",
    items: [
      { path: "/health", label: "System Health" },
      { path: "/settings", label: "Settings" },
      { path: "/audit", label: "Audit Logs" },
      { path: "/backups", label: "Backup and Recovery" },
    ],
  },
];

export const MOBILE_TABS: (NavItem & { short: string })[] = [
  { path: "/", label: "Overview", short: "Overview" },
  { path: "/market", label: "Gold Live Market", short: "Market" },
  { path: "/virtual", label: "Live Virtual Trading", short: "Virtual" },
  { path: "/risk", label: "Risk Management", short: "Risk" },
];

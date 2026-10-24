/**
 * Typed client for the GOLD AI ADAPTIVE AGENTIC SCALPER FastAPI backend.
 *
 * Every value the dashboard shows comes through this module. Nothing here
 * invents data: on failure the caller receives an ApiError and must render an
 * explicit error / empty state.
 */

import { nativeApp } from "./native";

// ---------------------------------------------------------------- domains

export type Domain = "historical" | "forward" | "virtual" | "real";
export const DOMAINS: Domain[] = ["historical", "forward", "virtual", "real"];

/** Badge text required for every trade table / metric card. */
export const DOMAIN_BADGE: Record<Domain, string> = {
  historical: "SIMULATED (historical backtest)",
  forward: "SIMULATED (walk-forward OOS)",
  virtual: "SIMULATED (live virtual, estimated fills)",
  real: "ACTUAL BROKER FILLS",
};

export const DOMAIN_TITLE: Record<Domain, string> = {
  historical: "Memory A - Historical backtest",
  forward: "Memory B - Walk-forward (historical out-of-sample)",
  virtual: "Memory C - Live virtual trading",
  real: "Memory D - Real broker executions",
};

// ---------------------------------------------------------------- types

export type Json = string | number | boolean | null | Json[] | { [k: string]: Json };
/** Numeric metric; backend serializes +inf as the string "inf" and NaN as null. */
export type Num = number | "inf" | null;

export interface LoginResponse {
  token: string;
  role: string;
}

export interface Health {
  status?: string;
  [k: string]: unknown;
}

export interface VirtualEngineStatus {
  broker: string;
  symbol: string;
  /** "scalp" or "swing"; each style is its own engine with its own virtual account and memory. */
  style?: string;
  timeframes?: string[];
  ready?: boolean;
  equity?: number;
  open_positions?: number;
  ticks_processed?: number;
  decisions?: number;
  model_version?: string;
  strategy_version?: string;
  learning_started?: string | null;
  last_tick?: string | null;
  fills?: string;
  [k: string]: unknown;
}

export interface MemoryCounts {
  historical: number;
  forward: number;
  virtual: number;
  real: number;
}

export interface Run {
  run_id: string;
  domain: Domain | string;
  kind: string;
  broker: string;
  symbol: string;
  data_source?: string;
  data_hash?: string;
  period_start?: string | null;
  period_end?: string | null;
  strategy_version?: string;
  model_version_start?: string;
  model_version_end?: string;
  params?: Record<string, unknown>;
  metrics?: Metrics;
  created_at?: string;
  [k: string]: unknown;
}

export interface Overview {
  memory_counts: MemoryCounts;
  real_trading_enabled: boolean;
  demo_execution_enabled: boolean;
  emergency_stop: boolean;
  virtual_engines: VirtualEngineStatus[];
  latest_runs: Run[];
  [k: string]: unknown;
}

export interface LiveStatusMessage extends Partial<Overview> {
  type: "status";
}

export interface BrokerStatus {
  broker: string;
  symbol: string;
  connected: boolean;
  account?: string | number | null;
  trade_mode?: string | null;
  spread?: number | null;
  latency_ms?: number | null;
  [k: string]: unknown;
}

export interface LastTick {
  time: string;
  bid: number;
  ask: number;
  spread: number;
}

export interface MarketState {
  broker: string;
  symbol: string;
  ready: boolean;
  regime: string | null;
  features: Record<string, number | null>;
  last_tick: LastTick | null;
  [k: string]: unknown;
}

export interface Instrument {
  broker: string;
  symbol: string;
  instrument: string;
  asset_class: string;
  pip_size: number | null;
  digits: number;
  trades_weekends: boolean;
  sessions_utc: [number, number][];
  max_spread_points: number;
  trade_mode: string;
  ready: boolean;
  regime: string | null;
  last_tick: LastTick | null;
  open_positions: number;
  /** Trade styles running on this instrument. */
  styles?: { style: string; ready: boolean; open_positions: number; timeframes: string[]; max_hold_seconds: number }[];
}

export interface Trade {
  trade_id: string;
  /** Canonical instrument (EURUSD for EURUSD.sd) and its pip size, from the server. */
  instrument?: string;
  pip_size?: number | null;
  run_id?: string | null;
  broker: string;
  account?: string;
  symbol: string;
  side: string;
  lots: number;
  strategy_version?: string;
  model_version?: string;
  entry_time: string;
  entry_price: number;
  exit_time?: string | null;
  exit_price?: number | null;
  exit_reason?: string | null;
  stop_loss?: number;
  take_profit?: number;
  commission?: number;
  swap?: number;
  spread_cost?: number;
  slippage_cost?: number;
  gross_pnl?: number;
  net_pnl: number;
  initial_risk_money?: number;
  r_multiple?: number | null;
  is_estimated_fill?: boolean;
  context?: Record<string, unknown>;
  explanation?: string;
  /** "scalp" or "swing" (older trades are scalping). */
  style?: string;
  [k: string]: unknown;
}

export interface RegimeStat {
  trades: number;
  net: number;
  wins: number;
}

export interface Metrics {
  total_trades: number;
  winning_trades?: number;
  losing_trades?: number;
  win_rate: number;
  net_profit: number;
  gross_profit?: number;
  gross_loss?: number;
  profit_factor: Num;
  max_drawdown: number;
  max_drawdown_pct?: number;
  avg_r_multiple: number;
  expectancy: number;
  sharpe_per_trade?: Num;
  total_commission?: number;
  total_swap?: number;
  total_spread_cost?: number;
  total_slippage_cost?: number;
  monthly: Record<string, number>;
  by_regime: Record<string, RegimeStat>;
  exit_reasons?: Record<string, number>;
  ending_equity?: number;
  /** Optional: only shown when the backend provides them. */
  by_broker?: Record<string, Partial<Metrics> & { trades?: number; net?: number }>;
  calibration?: CalibrationBucket[] | Record<string, unknown>;
  active_positions?: number;
  [k: string]: unknown;
}

export interface CalibrationBucket {
  bucket?: string;
  predicted?: number;
  observed?: number;
  count?: number;
  [k: string]: unknown;
}

export interface TradesResponse {
  domain: Domain;
  label: string;
  simulated: boolean;
  trades: Trade[];
  metrics: Metrics;
}

export interface BacktestRequest {
  source: "db" | "synthetic";
  broker: string;
  symbol: string;
  start?: string;
  end?: string;
  params?: Record<string, unknown>;
}

export interface BacktestResult {
  run_id?: string;
  metrics?: Metrics;
  trades?: Trade[];
  label?: string;
  [k: string]: unknown;
}

export interface WalkForwardRequest extends BacktestRequest {
  train_days?: number;
  validation_days?: number;
  test_days?: number;
  anchored?: boolean;
}

export interface WalkForwardFold {
  fold?: { index?: number; train?: [string, string]; validation?: [string, string]; test?: [string, string] } | number;
  selected?: string | null;
  train_metrics?: Partial<Metrics>;
  validation_metrics?: Partial<Metrics>;
  test_metrics?: Partial<Metrics>;
  candidate_scores?: Record<string, number | null>;
  notes?: string[];
  [k: string]: unknown;
}

export interface WalkForwardReport {
  folds: WalkForwardFold[];
  verdict: string;
  overfit_flags: string[];
  selection_stability: number;
  label: string;
  oos_trades?: number;
  oos_net?: number;
  oos_expectancy?: number;
  run_ids?: string[];
  [k: string]: unknown;
}

export interface ModelInfo {
  version: string;
  strategy_version: string;
  parent?: string | null;
  stage: string;
  created_at: string;
  notes?: string;
  [k: string]: unknown;
}

export interface MaturityGate {
  name: string;
  passed: boolean;
  observed: unknown;
  threshold: unknown;
  [k: string]: unknown;
}

export interface MaturityStages {
  observation_ready: boolean;
  data_sufficient: boolean;
  statistically_validated: boolean;
  operationally_ready: boolean;
  live_authorized: boolean;
}

export interface Maturity {
  score: number | null;
  gates: MaturityGate[];
  stages: MaturityStages;
  uncertainty: Record<string, unknown>;
  required_tests: string[];
  explanation: string;
  [k: string]: unknown;
}

export interface SelfHealing {
  history: Record<string, unknown>[];
  current_diagnosis: Record<string, unknown> | null;
}

export interface HealthCheck {
  name: string;
  status: string;
  detail?: string | null;
}

export interface SystemHealth {
  overall: string;
  checks: HealthCheck[];
}

export interface Signal {
  id: string | number;
  time?: string;
  broker?: string;
  symbol?: string;
  side?: string;
  confidence?: number;
  entry?: number;
  stop_loss?: number;
  take_profit?: number;
  lots?: number;
  explanation?: string;
  status?: string;
  /** One-time action token issued by the backend for this signal. */
  token?: string;
  action_token?: string;
  domain?: string;
  /** Fields as the backend's Signal.to_dict sends them. */
  timestamp?: string;
  expiry?: string;
  suggested_lots?: number;
  risk_reward?: number;
  reason?: string;
  instrument?: string;
  asset_class?: string | null;
  pip_size?: number | null;
  digits?: number;
  sl_pips?: number | null;
  tp_pips?: number | null;
  style?: string;
  style_label?: string;
  max_hold_seconds?: number | null;
  [k: string]: unknown;
}

export interface Technical {
  broker: string;
  symbol: string;
  timeframe: string;
  bars: number;
  last_close: number | null;
  last_bar_time: string | null;
  rsi14: number | null;
  macd: { macd: number; signal: number; histogram: number } | null;
  stochastic: { k: number; d: number } | null;
  bollinger: { upper: number; middle: number; lower: number } | null;
  ma50: number | null;
  ma200: number | null;
  pressure: { buy_pct: number; sell_pct: number; bars: number } | null;
  votes: Record<string, number>;
  score: number | null;
  label: string;
  support: number | null;
  resistance: number | null;
  bars_missing: Record<string, number>;
  note: string;
}

export type SignalAction = "approve" | "reject" | "ignore" | "manual";

export interface NewsEvent {
  time: string;
  title: string;
  currency?: string | null;
  forecast?: number | string | null;
  previous?: number | string | null;
  actual?: number | string | null;
  category?: string;
  impact?: string;
  uncertainty?: number | string | null;
  [k: string]: unknown;
}

export interface NewsResponse {
  events: NewsEvent[];
  blackout_active: boolean;
  [k: string]: unknown;
}

export interface Institutional {
  available: boolean;
  features: Record<string, unknown>;
  reason?: string;
}

export interface RiskResponse {
  config: Record<string, unknown>;
  state: Record<string, unknown>;
}

export interface Grant {
  granted_at?: string;
  granted_by?: string;
  expires_at?: string;
  accounts?: string[];
  max_lots?: number;
  [k: string]: unknown;
}

export interface Authorization {
  real_trading_enabled: boolean;
  grant: Grant | null;
  account_allowlist: string[];
  [k: string]: unknown;
}

export interface GrantRequest {
  password: string;
  phrase: string;
  accounts: string[];
  max_lots: number;
  hours: number;
}

export interface AuditEntry {
  time: string;
  actor: string;
  action: string;
  detail: Record<string, unknown>;
}

export interface Backup {
  name?: string;
  path?: string;
  created_at?: string;
  size_bytes?: number;
  [k: string]: unknown;
}

export type Settings = Record<string, unknown>;

// ---------------------------------------------------------------- transport

const TOKEN_KEY = "gold_ai_token";
const ROLE_KEY = "gold_ai_role";

function safeStorage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return safeStorage()?.getItem(TOKEN_KEY) ?? null;
}
export function getRole(): string | null {
  return safeStorage()?.getItem(ROLE_KEY) ?? null;
}
export function setSession(token: string, role: string): void {
  safeStorage()?.setItem(TOKEN_KEY, token);
  safeStorage()?.setItem(ROLE_KEY, role);
  nativeApp.onSession(token);
}
export function clearSession(): void {
  safeStorage()?.removeItem(TOKEN_KEY);
  safeStorage()?.removeItem(ROLE_KEY);
}

export const AUTH_EXPIRED_EVENT = "gold-ai:auth-expired";

export class ApiError extends Error {
  constructor(public status: number, message: string, public path: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (e) {
    throw new ApiError(0, `Network error: ${(e as Error).message}`, path);
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    if (res.status === 401 && path !== "/api/auth/login") {
      clearSession();
      window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
    }
    const detail =
      data && typeof data === "object" && "detail" in data
        ? JSON.stringify((data as { detail: unknown }).detail)
        : typeof data === "string" && data
          ? data.slice(0, 300)
          : res.statusText;
    throw new ApiError(res.status, `${res.status} ${detail}`, path);
  }
  return data as T;
}

const get = <T,>(p: string) => request<T>("GET", p);
const post = <T,>(p: string, b?: unknown) => request<T>("POST", p, b ?? {});
const enc = encodeURIComponent;

// ---------------------------------------------------------------- endpoints

export const api = {
  login: (username: string, password: string) => post<LoginResponse>("/api/auth/login", { username, password }),
  health: () => get<Health>("/api/health"),
  overview: () => get<Overview>("/api/overview"),
  brokers: () => get<BrokerStatus[]>("/api/brokers"),
  market: (symbol?: string | null) => get<MarketState>(`/api/market/state${symbol ? `?symbol=${enc(symbol)}` : ""}`),
  instruments: () => get<Instrument[]>("/api/instruments"),
  trades: (domain: Domain, limit = 200, symbol?: string | null) =>
    get<TradesResponse>(`/api/trades/${domain}?limit=${limit}${symbol ? `&symbol=${enc(symbol)}` : ""}`),
  runs: (domain: "historical" | "forward") => get<Run[]>(`/api/runs?domain=${domain}`),
  backtest: (req: BacktestRequest) => post<BacktestResult>("/api/backtest", req),
  walkforward: (req: WalkForwardRequest) => post<WalkForwardReport>("/api/walkforward", req),
  models: () => get<ModelInfo[]>("/api/models"),
  promote: (version: string) => post<unknown>(`/api/models/${enc(version)}/promote`),
  rollback: (version: string) => post<unknown>(`/api/models/${enc(version)}/rollback`),
  maturity: (broker?: string) => get<Maturity>(`/api/maturity${broker ? `?broker=${enc(broker)}` : ""}`),
  selfHealing: () => get<SelfHealing>("/api/self-healing"),
  systemHealth: () => get<SystemHealth>("/api/system/health"),
  signals: () => get<Signal[]>("/api/signals"),
  revokeDeviceTokens: () => post<{ ok: boolean }>("/api/auth/device-token/revoke-all", {}),
  signalAction: (id: string | number, action: SignalAction, token: string) =>
    post<unknown>(`/api/signals/${enc(String(id))}/action`, { action, token }),
  news: () => get<NewsResponse>("/api/news"),
  technical: (tf: string, symbol?: string | null) =>
    get<Technical>(`/api/analysis/technical?tf=${enc(tf)}${symbol ? `&symbol=${enc(symbol)}` : ""}`),
  institutional: () => get<Institutional>("/api/institutional"),
  risk: () => get<RiskResponse>("/api/risk"),
  emergencyStop: (active: boolean, reason: string) => post<unknown>("/api/emergency-stop", { active, reason }),
  authorization: () => get<Authorization>("/api/authorization"),
  grant: (req: GrantRequest) => post<unknown>("/api/authorization/grant", req),
  revoke: () => post<unknown>("/api/authorization/revoke"),
  audit: (limit = 200) => get<AuditEntry[]>(`/api/audit?limit=${limit}`),
  backups: () => get<Backup[]>("/api/backups"),
  createBackup: () => post<Backup>("/api/backups"),
  settings: () => get<Settings>("/api/settings"),
};

/** Opens /ws/live; reconnects with backoff until the returned closer is called. */
export function connectLive(onMessage: (m: LiveStatusMessage) => void, onState: (connected: boolean) => void): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let delay = 1000;
  let timer: number | undefined;
  const open = () => {
    const token = getToken();
    if (!token || closed) return;
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    ws = new WebSocket(`${proto}//${window.location.host}/ws/live?token=${enc(token)}`);
    ws.onopen = () => {
      delay = 1000;
      onState(true);
    };
    ws.onmessage = (ev) => {
      try {
        const m = JSON.parse(String(ev.data));
        if (m && m.type === "status") onMessage(m as LiveStatusMessage);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = () => {
      onState(false);
      if (!closed) {
        timer = window.setTimeout(open, delay);
        delay = Math.min(delay * 2, 30000);
      }
    };
    ws.onerror = () => ws?.close();
  };
  open();
  return () => {
    closed = true;
    if (timer) window.clearTimeout(timer);
    ws?.close();
  };
}

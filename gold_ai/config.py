"""Application configuration.

Loaded from environment variables (prefix GOLDAI_) and an optional JSON file.
Real-money execution is OFF by default and cannot be enabled from config alone:
it additionally requires a live owner authorization grant (see security.authorization).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from .instruments import DEFAULT_SYMBOLS


class RiskConfig(BaseModel):
    max_open_positions: int = 1                # spec: ONE OPEN TRADE AT A TIME
    max_open_positions_global: int = 1
    max_lots_per_trade: float = 0.10
    risk_per_trade_pct: float = 0.5            # % of equity at risk per trade
    max_daily_loss_pct: float = 2.0
    max_drawdown_pct: float = 10.0
    max_spread_points: int = 60                # XAUUSD point is typically 0.01
    max_slippage_points: int = 30
    min_risk_reward: float = 1.2
    min_confidence: float = 0.55
    block_minutes_before_high_impact: int = 15
    block_minutes_after_high_impact: int = 15
    allowed_sessions_utc: list[tuple[float, float]] = Field(default_factory=lambda: [(0, 24)])
    max_tick_age_seconds: float = 10.0
    # High-impact events in these currencies black out trading; empty = every currency (gold default).
    news_currencies: list[str] = Field(default_factory=list)
    # --- risk engine v2 (docs/AGENTIC_REDESIGN.md §5). Values are illustrative research defaults, not live
    # recommendations: live settings wait for the owner's account size and risk tolerance.
    max_weekly_loss_pct: float = 4.0
    max_consecutive_losses: int = 3            # then cool down
    loss_cooldown_minutes: float = 60.0
    reentry_after_loss_minutes: float = 5.0    # no immediate re-entry after any loss (revenge trading)
    max_trades_per_day: int = 20               # overtrading cap
    min_minutes_between_entries: float = 2.0
    max_latency_ms: float = 1500.0             # applied when execution latency is measured
    max_vol_ratio: float = 3.0                 # short/long tick volatility; above = abnormal volatility
    max_spread_z: float = 4.0                  # spread z-score vs recent spreads; above = abnormal widening
    min_ev_after_cost_r: float = 0.05          # model proposals need this expectancy after costs (R)
    max_margin_use_pct: float = 30.0           # required margin / free margin, when margin data is known
    duplicate_window_seconds: float = 60.0
    observation_minutes: float = 5.0           # after start, demo/real execution waits; virtual is allowed
    # Owner-preferred sessions in local time (empty = no local restriction), e.g. [["18:00", "19:00"]].
    local_timezone: str = "Asia/Dubai"
    allowed_sessions_local: list[tuple[str, str]] = Field(default_factory=list)


class CostConfig(BaseModel):
    slippage_points_entry: int = 5             # conservative estimate, adverse
    slippage_points_exit: int = 5
    stop_slippage_extra_points: int = 10       # stops fill worse than limits
    triple_swap_weekday: int | None = 2        # Wednesday rollover charged x3 (metals/forex); None for crypto


class Settings(BaseModel):
    env: str = "development"
    database_url: str = "sqlite:///./data/gold_ai.db"
    data_dir: str = "./data"
    secret_key: str = "change-me-in-production"
    owner_username: str = "owner"
    # Execution safety. Both must be true AND an unexpired owner grant must exist.
    real_trading_enabled: bool = False
    demo_execution_enabled: bool = False
    account_allowlist: list[str] = Field(default_factory=list)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    costs: CostConfig = Field(default_factory=CostConfig)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None
    whatsapp_token: str | None = None
    whatsapp_phone_id: str | None = None
    whatsapp_recipient: str | None = None
    push_webhook_url: str | None = None
    # Economic-calendar files read by the news agent (e.g. Common\Files\goldai_calendar.csv written by
    # mql5/GoldAICalendar.mq5). Re-read on every refresh.
    news_calendar_files: list[str] = Field(default_factory=list)
    # Instruments the live service analyses (signals + virtual trades only), canonical names; each is matched
    # to the broker's own symbol (e.g. EURUSD -> EURUSD.sd) and skipped if the broker does not offer it.
    symbols: list[str] = Field(default_factory=lambda: list(DEFAULT_SYMBOLS))
    # Signal styles run for every instrument, each as its own virtual engine with separate memory:
    # "scalp" (M1/M5/M15 bars, held up to 1 h) and "swing" (M15/H1/H4 bars, held up to 3 days).
    trade_styles: list[str] = Field(default_factory=lambda: ["scalp", "swing"])
    # Candidate rules the live-virtual engines may take trades from: "momentum" (momentum continuation) and
    # "rejection" (support/resistance wick rejection). Momentum is off: the root-cause audit found it made
    # ~97% of the losing virtual trades (docs/ROOT_CAUSE_AUDIT.md). An empty list stops new virtual entries.
    virtual_entry_rules: list[str] = Field(default_factory=lambda: ["rejection"])
    # Forward research lanes (gold_ai/engines/research_lanes.py): research setups traded virtually on live quotes,
    # simulation only, labelled, no signals. Defaults: the intraday setups that were not negative on research
    # round 3's test split, with the variant chosen on validation (docs/research/README.md).
    # Evidence a research lane needs before the owner may promote it to champion (agents/strategy_selector.py
    # PromotionCriteria field names; empty = the strict defaults).
    promotion_criteria: dict = Field(default_factory=dict)
    research_lane_symbols: list[str] = Field(default_factory=lambda: ["XAUUSD"])
    research_lanes: list[dict] = Field(default_factory=lambda: [
        # Round 5's one variant that was not negative on any split (train -0.00R, validation +0.15R, test +0.12R,
        # 63 test trades). It was not the variant chosen on validation, so this is a hypothesis for forward testing.
        {"setup": "failed_breakout", "risk_reward": 1.5, "tf_scale": "intraday", "trigger_tf": "M5",
         "max_hold_seconds": 8 * 3600, "min_bb_bw_pctile": 0.6},
        {"setup": "trend_pullback", "risk_reward": 1.5, "tf_scale": "intraday", "trigger_tf": "M5",
         "max_hold_seconds": 8 * 3600},
        {"setup": "breakout", "risk_reward": 2.0, "tf_scale": "intraday", "max_hold_seconds": 4 * 3600},
    ])
    # Per-symbol changes to gold_ai.instruments limits, e.g. {"BTCUSD": {"max_spread_pips": 40}}.
    instrument_overrides: dict[str, dict] = Field(default_factory=dict)


def load_settings(path: str | os.PathLike | None = None) -> Settings:
    data: dict = {}
    path = path or os.environ.get("GOLDAI_CONFIG")
    if path and Path(path).exists():
        data = json.loads(Path(path).read_text())
    for key in Settings.model_fields:
        env_val = os.environ.get(f"GOLDAI_{key.upper()}")
        if env_val is not None:
            field = Settings.model_fields[key]
            if field.annotation is bool:
                data[key] = env_val.lower() in ("1", "true", "yes")
            elif field.annotation in (str, str | None):
                data[key] = env_val
    return Settings(**data)

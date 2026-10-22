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
    allowed_sessions_utc: list[tuple[int, int]] = Field(default_factory=lambda: [(0, 24)])
    max_tick_age_seconds: float = 10.0


class CostConfig(BaseModel):
    slippage_points_entry: int = 5             # conservative estimate, adverse
    slippage_points_exit: int = 5
    stop_slippage_extra_points: int = 10       # stops fill worse than limits


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

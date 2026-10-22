"""ENGINE A — Historical backtesting. Results are written to Memory A only."""
from __future__ import annotations

import copy
import uuid
from dataclasses import asdict, dataclass

from ..agents.decision import ModelState, StrategyParams, TradingDecisionAgent
from ..config import Settings
from ..domain import MemoryDomain, SimTrade, SymbolSpec, Tick
from ..memory.store import MemoryStore
from ..risk.engine import NewsEvent, RiskEngine
from .loop import LoopStats, TradingLoop, data_hash
from .metrics import compute_metrics, json_safe


@dataclass
class BacktestResult:
    run_id: str
    trades: list[SimTrade]
    metrics: dict
    stats: LoopStats
    model_start: str
    model_end: str
    final_model: ModelState
    data_hash: str
    data_source: str


def run_backtest(settings: Settings, spec: SymbolSpec, ticks: list[Tick], *, params: StrategyParams,
                 model: ModelState | None = None, learn: bool = True, starting_equity: float = 10_000.0,
                 news: list[NewsEvent] | None = None, data_source: str = "unknown", seed: int = 0,
                 store: MemoryStore | None = None, domain: MemoryDomain = MemoryDomain.HISTORICAL,
                 kind: str = "backtest", account: str = "backtest") -> BacktestResult:
    """Deterministic for a given (ticks, params, model, seed). Input model is never mutated."""
    if not ticks:
        raise ValueError("no ticks supplied")
    if any(b.time < a.time for a, b in zip(ticks, ticks[1:])):
        raise ValueError("ticks must be time-ordered")
    model = copy.deepcopy(model) if model else ModelState()
    agent = TradingDecisionAgent(params, model, seed=seed)
    model_start = model.version()
    risk = RiskEngine.create(settings.risk, spec, starting_equity)
    risk.news = list(news or [])
    loop = TradingLoop(settings, spec, agent, broker=spec.broker, account=account,
                       starting_equity=starting_equity, learn=learn, simulation=True, risk=risk)
    trades = loop.run(ticks)
    trades += loop.finish()
    metrics = compute_metrics(trades, starting_equity)
    run_id = f"{kind}-{uuid.uuid4().hex[:12]}"
    dh = data_hash(ticks)
    if store is not None:
        store.save_trades(domain, trades, run_id)
        store.save_run(run_id=run_id, domain=domain.value, kind=kind, broker=spec.broker, symbol=spec.symbol,
                       data_source=data_source, data_hash=dh, period_start=ticks[0].time,
                       period_end=ticks[-1].time, strategy_version=params.version(),
                       model_version_start=model_start, model_version_end=agent.model.version(),
                       params=asdict(params), metrics=json_safe({k: v for k, v in metrics.items()}))
    return BacktestResult(run_id, trades, metrics, loop.stats, model_start, agent.model.version(),
                          agent.model, dh, data_source)

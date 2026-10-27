"""Persistent Memory Agent: SQLAlchemy storage (PostgreSQL in production, SQLite for dev/tests).

Four logical memory domains are kept in four physically separate trade tables so
a query on one can never accidentally mix in another. Nothing in this module
deletes learning history; archival is an explicit owner action (see backup.py).
The model registry and audit log are append-only.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

from sqlalchemy import (JSON, Boolean, DateTime, Float, Index, Integer, String, Text, create_engine, event,
                        func, select)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ..domain import ExitReason, MemoryDomain, Side, SimTrade, Tick


class Base(DeclarativeBase):
    pass


class TradeMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trade_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    broker: Mapped[str] = mapped_column(String(64), index=True)
    account: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(4))
    lots: Mapped[float] = mapped_column(Float)
    strategy_version: Mapped[str] = mapped_column(String(64), index=True)
    model_version: Mapped[str] = mapped_column(String(64), index=True)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    entry_price: Mapped[float] = mapped_column(Float)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    swap: Mapped[float] = mapped_column(Float, default=0.0)
    spread_cost: Mapped[float] = mapped_column(Float, default=0.0)
    slippage_cost: Mapped[float] = mapped_column(Float, default=0.0)
    gross_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    initial_risk_money: Mapped[float] = mapped_column(Float, default=0.0)
    is_estimated_fill: Mapped[bool] = mapped_column(Boolean, default=True)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    explanation: Mapped[str] = mapped_column(Text, default="")


class HistoricalTrade(TradeMixin, Base):
    __tablename__ = "mem_a_historical_trades"


class ForwardTrade(TradeMixin, Base):
    __tablename__ = "mem_b_forward_trades"


class VirtualTrade(TradeMixin, Base):
    __tablename__ = "mem_c_virtual_trades"


class RealTrade(TradeMixin, Base):
    __tablename__ = "mem_d_real_trades"


TRADE_TABLES = {
    MemoryDomain.HISTORICAL: HistoricalTrade,
    MemoryDomain.FORWARD: ForwardTrade,
    MemoryDomain.VIRTUAL: VirtualTrade,
    MemoryDomain.REAL: RealTrade,
}


class TickRow(Base):
    __tablename__ = "ticks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    broker: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    bid: Mapped[float] = mapped_column(Float)
    ask: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(32), default="mt5")  # mt5 | csv | synthetic
    # Every tick read is "this broker + symbol in a time range, in time order". With tens of millions of rows
    # the single-column indexes made each such read scan the symbol's whole history and sort it.
    __table_args__ = (Index("ix_ticks_broker_symbol_time", "broker", "symbol", "time"),)


class DecisionRow(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(16), index=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    broker: Mapped[str] = mapped_column(String(64))
    side: Mapped[str] = mapped_column(String(4))
    confidence: Mapped[float] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    model_version: Mapped[str] = mapped_column(String(64), default="")
    risk_verdict: Mapped[dict] = mapped_column(JSON, default=dict)


class ModelVersion(Base):
    """Immutable model registry. Rows are never updated except `stage` transitions, which are audited."""

    __tablename__ = "model_registry"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    strategy_version: Mapped[str] = mapped_column(String(64))
    parent_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stage: Mapped[str] = mapped_column(String(32), default="candidate")  # candidate|validated|approved|retired|rejected
    params: Mapped[dict] = mapped_column(JSON)
    state: Mapped[dict] = mapped_column(JSON)
    notes: Mapped[str] = mapped_column(Text, default="")


class RunRow(Base):
    """A reproducible backtest / walk-forward / virtual session run."""

    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    domain: Mapped[str] = mapped_column(String(16), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    broker: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(32))
    data_source: Mapped[str] = mapped_column(String(32))
    data_hash: Mapped[str] = mapped_column(String(64))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    strategy_version: Mapped[str] = mapped_column(String(64))
    model_version_start: Mapped[str] = mapped_column(String(64))
    model_version_end: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict] = mapped_column(JSON)
    metrics: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditRow(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class KVRow(Base):
    """Small persistent key/value state (learning session start, emergency stop flag, ...)."""

    __tablename__ = "kv_state"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; all stored times are UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class MemoryStore:
    def __init__(self, url: str):
        if url.startswith("sqlite:///") and not url.startswith("sqlite:///:memory:"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        # SQLite allows one writer at a time; with one collector + engine per instrument the startup
        # backfills overlap, so writers wait up to 30 s for the lock instead of the default 5 s.
        connect_args = {"timeout": 30} if url.startswith("sqlite") else {}
        # One collector and one or two engines per instrument plus research lanes all read at start-up;
        # SQLite connections are cheap, so the pool must not be the bottleneck (default 5 + 10 overflow).
        pool_args = ({"pool_size": 40, "max_overflow": 20}
                     if url.startswith("sqlite") and ":memory:" not in url else {})
        self.engine = create_engine(url, future=True, connect_args=connect_args, **pool_args)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _pragmas(conn, _):  # pragma: no cover - trivial
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=30000")
                conn.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        # create_all adds indexes only with new tables; add ones introduced later to existing databases
        # (one-off: building it on tens of millions of ticks takes several minutes).
        for ix in TickRow.__table__.indexes:
            ix.create(self.engine, checkfirst=True)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    # -- trades ------------------------------------------------------------------
    def save_trade(self, domain: MemoryDomain, t: SimTrade, run_id: str | None = None) -> None:
        if domain == MemoryDomain.REAL and t.is_estimated_fill:
            raise ValueError("real-trading memory accepts only actual broker fills")
        if domain != MemoryDomain.REAL and not t.is_estimated_fill:
            raise ValueError("simulated memories must not contain actual broker fills")
        table = TRADE_TABLES[domain]
        with self.Session.begin() as s:
            row = s.scalar(select(table).where(table.trade_id == t.trade_id))
            if row is None:
                row = table(trade_id=t.trade_id)
                s.add(row)
            row.run_id = run_id
            for k in ("broker", "account", "symbol", "lots", "strategy_version", "model_version", "entry_time",
                      "entry_price", "exit_time", "exit_price", "stop_loss", "take_profit", "commission", "swap",
                      "spread_cost", "slippage_cost", "gross_pnl", "net_pnl", "initial_risk_money",
                      "is_estimated_fill", "explanation"):
                setattr(row, k, getattr(t, k))
            row.side = t.side.value
            row.exit_reason = t.exit_reason.value if t.exit_reason else None
            row.context = json.loads(json.dumps(t.context, default=str))

    def save_trades(self, domain: MemoryDomain, trades: Iterable[SimTrade], run_id: str | None = None) -> int:
        n = 0
        for t in trades:
            self.save_trade(domain, t, run_id)
            n += 1
        return n

    def load_trades(self, domain: MemoryDomain, run_id: str | None = None, broker: str | None = None,
                    limit: int | None = None, symbols: list[str] | None = None) -> list[SimTrade]:
        table = TRADE_TABLES[domain]
        q = select(table).order_by(table.entry_time)
        if run_id:
            q = q.where(table.run_id == run_id)
        if broker:
            q = q.where(table.broker == broker)
        if symbols is not None:
            q = q.where(table.symbol.in_(symbols))
        if limit:
            q = q.limit(limit)
        with self.Session() as s:
            return [self._to_trade(r) for r in s.scalars(q)]

    def recent_closed_trades(self, domain: MemoryDomain, limit: int = 50, min_net_pnl: float | None = None,
                             since: datetime | None = None) -> list[SimTrade]:
        """Closed trades, newest exit first; `min_net_pnl` keeps only trades that made more than it."""
        table = TRADE_TABLES[domain]
        q = select(table).where(table.exit_time.is_not(None)).order_by(table.exit_time.desc()).limit(limit)
        if min_net_pnl is not None:
            q = q.where(table.net_pnl > min_net_pnl)
        if since is not None:
            q = q.where(table.exit_time > since)
        with self.Session() as s:
            return [self._to_trade(r) for r in s.scalars(q)]

    def count_trades(self, domain: MemoryDomain) -> int:
        table = TRADE_TABLES[domain]
        with self.Session() as s:
            return s.scalar(select(func.count()).select_from(table)) or 0

    @staticmethod
    def _to_trade(r: TradeMixin) -> SimTrade:
        return SimTrade(
            trade_id=r.trade_id, broker=r.broker, account=r.account, symbol=r.symbol, side=Side(r.side),
            lots=r.lots, entry_time=_aware(r.entry_time), entry_price=r.entry_price,
            stop_loss=r.stop_loss, take_profit=r.take_profit, strategy_version=r.strategy_version,
            model_version=r.model_version, is_estimated_fill=r.is_estimated_fill,
            exit_time=_aware(r.exit_time), exit_price=r.exit_price,
            exit_reason=ExitReason(r.exit_reason) if r.exit_reason else None, commission=r.commission,
            swap=r.swap, slippage_cost=r.slippage_cost, spread_cost=r.spread_cost, gross_pnl=r.gross_pnl,
            net_pnl=r.net_pnl, initial_risk_money=r.initial_risk_money, context=r.context or {},
            explanation=r.explanation,
        )

    # -- ticks -----------------------------------------------------------------
    def save_ticks(self, broker: str, symbol: str, ticks: Iterable[Tick], source: str) -> int:
        rows = [TickRow(broker=broker, symbol=symbol, time=t.time, bid=t.bid, ask=t.ask, volume=t.volume,
                        source=source) for t in ticks]
        with self.Session.begin() as s:
            s.add_all(rows)
        return len(rows)

    def load_ticks(self, broker: str, symbol: str, start: datetime | None = None, end: datetime | None = None,
                   source: str | None = None) -> list[Tick]:
        q = select(TickRow).where(TickRow.broker == broker, TickRow.symbol == symbol).order_by(TickRow.time)
        if start:
            q = q.where(TickRow.time >= start)
        if end:
            q = q.where(TickRow.time < end)
        if source:
            q = q.where(TickRow.source == source)
        with self.Session() as s:
            return [Tick(_aware(r.time), r.bid, r.ask, r.volume) for r in s.scalars(q)]

    def iter_ticks(self, broker: str, symbol: str, start: datetime, end: datetime,
                   chunk: timedelta = timedelta(hours=6)) -> Iterator[Tick]:
        """Ticks in [start, end) loaded a chunk at a time, so weeks of history never sit in memory at once."""
        t = start
        while t < end:
            stop = min(t + chunk, end)
            yield from self.load_ticks(broker, symbol, t, stop)
            t = stop

    def tick_range(self, broker: str, symbol: str, start: datetime | None = None,
                   end: datetime | None = None) -> tuple[datetime, datetime] | None:
        """Time of the first and last stored tick within the optional bounds."""
        q = select(func.min(TickRow.time), func.max(TickRow.time)).where(TickRow.broker == broker,
                                                                          TickRow.symbol == symbol)
        if start:
            q = q.where(TickRow.time >= start)
        if end:
            q = q.where(TickRow.time < end)
        with self.Session() as s:
            a, z = s.execute(q).one()
        return (_aware(a), _aware(z)) if a else None

    def first_tick_time(self, broker: str, symbol: str) -> datetime | None:
        with self.Session() as s:
            t = s.scalar(select(func.min(TickRow.time)).where(TickRow.broker == broker, TickRow.symbol == symbol))
        return _aware(t) if t else None

    def trade_symbols(self, domain: MemoryDomain) -> list[str]:
        table = TRADE_TABLES[domain]
        with self.Session() as s:
            return sorted(x for x in s.scalars(select(table.symbol).distinct()) if x)

    def tick_stats(self) -> list[dict]:
        q = select(TickRow.broker, TickRow.symbol, TickRow.source, func.count(), func.min(TickRow.time),
                   func.max(TickRow.time)).group_by(TickRow.broker, TickRow.symbol, TickRow.source)
        with self.Session() as s:
            return [{"broker": b, "symbol": sy, "source": src, "count": c, "first": _aware(a), "last": _aware(z)}
                    for b, sy, src, c, a, z in s.execute(q)]

    # -- decisions, runs, models, audit, kv ----------------------------------------
    def save_decision(self, domain: MemoryDomain, broker: str, d, risk: dict | None = None) -> None:
        with self.Session.begin() as s:
            s.add(DecisionRow(domain=domain.value, time=d.time, broker=broker, side=d.side.value,
                              confidence=d.confidence, explanation=d.explanation,
                              features={k: float(v) for k, v in d.features.items()},
                              model_version=d.proposal.model_version if d.proposal else "",
                              risk_verdict=risk or {}))

    def save_run(self, **kw) -> None:
        kw.setdefault("created_at", _now())
        with self.Session.begin() as s:
            s.add(RunRow(**kw))

    def list_runs(self, domain: MemoryDomain | None = None) -> list[dict]:
        q = select(RunRow).order_by(RunRow.created_at.desc())
        if domain:
            q = q.where(RunRow.domain == domain.value)
        with self.Session() as s:
            return [{c.name: getattr(r, c.name) for c in RunRow.__table__.columns} for r in s.scalars(q)]

    def register_model(self, version: str, strategy_version: str, params: dict, state: dict,
                       parent: str | None = None, stage: str = "candidate", notes: str = "") -> bool:
        """Insert-only. Returns False if the version already exists (immutability)."""
        with self.Session.begin() as s:
            if s.scalar(select(ModelVersion).where(ModelVersion.version == version)) is not None:
                return False
            s.add(ModelVersion(version=version, strategy_version=strategy_version, parent_version=parent,
                               created_at=_now(), stage=stage, params=params, state=state, notes=notes))
        return True

    def set_model_stage(self, version: str, stage: str, actor: str, reason: str = "") -> None:
        with self.Session.begin() as s:
            m = s.scalar(select(ModelVersion).where(ModelVersion.version == version))
            if m is None:
                raise KeyError(version)
            old = m.stage
            m.stage = stage
            s.add(AuditRow(time=_now(), actor=actor, action="model_stage",
                           detail={"version": version, "from": old, "to": stage, "reason": reason}))

    def get_model(self, version: str) -> dict | None:
        with self.Session() as s:
            m = s.scalar(select(ModelVersion).where(ModelVersion.version == version))
            return None if m is None else {c.name: getattr(m, c.name) for c in ModelVersion.__table__.columns}

    def list_models(self) -> list[dict]:
        with self.Session() as s:
            return [{"version": m.version, "strategy_version": m.strategy_version, "parent": m.parent_version,
                     "stage": m.stage, "created_at": _aware(m.created_at), "notes": m.notes}
                    for m in s.scalars(select(ModelVersion).order_by(ModelVersion.created_at))]

    def audit(self, actor: str, action: str, detail: dict | None = None) -> None:
        with self.Session.begin() as s:
            s.add(AuditRow(time=_now(), actor=actor, action=action,
                           detail=json.loads(json.dumps(detail or {}, default=str))))

    def audit_log(self, limit: int = 200) -> list[dict]:
        with self.Session() as s:
            q = select(AuditRow).order_by(AuditRow.id.desc()).limit(limit)
            return [{"time": _aware(a.time), "actor": a.actor, "action": a.action, "detail": a.detail}
                    for a in s.scalars(q)]

    def kv_get(self, key: str, default=None):
        with self.Session() as s:
            r = s.get(KVRow, key)
            return default if r is None else r.value.get("v")

    def kv_set(self, key: str, value) -> None:
        with self.Session.begin() as s:
            r = s.get(KVRow, key)
            if r is None:
                s.add(KVRow(key=key, value={"v": value}, updated_at=_now()))
            else:
                r.value = {"v": value}
                r.updated_at = _now()

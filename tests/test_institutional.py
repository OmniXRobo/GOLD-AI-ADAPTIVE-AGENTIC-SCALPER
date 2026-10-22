from datetime import datetime, timedelta, timezone

import pytest

from gold_ai.agents.institutional import (NEUTRAL, BookSnapshot, CotCsvSource, CotRecord, FuturesQuote,
                                          InstitutionalConfig, InstitutionalFlowAgent, TradePrint)
from gold_ai.domain import Tick

T0 = datetime(2024, 6, 12, 14, 0, tzinfo=timezone.utc)


def s(sec):
    return T0 + timedelta(seconds=sec)


def test_no_sources_is_unavailable_and_neutral():
    agent = InstitutionalFlowAgent()
    f = agent.features(T0)
    assert f.available is False and f.sources == []
    for k, v in NEUTRAL.items():
        assert f.values[k] == v
    assert all(f.values[f"inst_{k}_available"] == 0.0 for k in ("book", "prints", "basis", "oi", "cot", "sweep"))
    # spot ticks alone never turn into "institutional" flow features
    for i in range(10):
        agent.on_spot_tick(Tick(s(i), 2400.0, 2400.2, volume=500))
    f = agent.features(s(10))
    assert f.available is False and f.values["inst_book_imbalance"] == 0.0
    assert f.values["inst_aggressive_buy_ratio"] == 0.5


def test_book_imbalance_and_staleness():
    class Depth:
        def latest_book(self):
            return BookSnapshot(T0, bids=((2400.0, 30), (2399.9, 10)), asks=((2400.1, 10), (2400.2, 0)))

    agent = InstitutionalFlowAgent(depth=Depth())
    agent.poll(T0)
    f = agent.features(T0)
    assert f.available and f.sources == ["depth"]
    assert f.values["inst_book_imbalance"] == pytest.approx((40 - 10) / 50)
    assert f.values["inst_book_available"] == 1.0
    stale = agent.features(s(120))
    assert stale.values["inst_book_imbalance"] == 0.0 and stale.values["inst_book_available"] == 0.0


def test_aggressive_ratio_with_and_without_aggressor_flag():
    prints = [TradePrint(s(1), 2400.0, 5, "buy"), TradePrint(s(2), 2400.1, 3, "sell"),
              TradePrint(s(3), 2400.2, 2), TradePrint(s(4), 2400.1, 1), TradePrint(s(5), 2400.1, 9)]

    class Src:
        def prints_since(self, since):
            return [p for p in prints if p.time >= since]

    agent = InstitutionalFlowAgent(prints=Src())
    agent.poll(s(5))
    # buy: 5 + 2 (uptick) ; sell: 3 + 1 (downtick) ; zero tick ignored
    assert agent.features(s(5)).values["inst_aggressive_buy_ratio"] == pytest.approx(7 / 11)
    assert agent.features(s(500)).values["inst_prints_available"] == 0.0   # window elapsed


def test_basis_zscore_and_open_interest():
    cfg = InstitutionalConfig(basis_min_samples=5, oi_lookback_seconds=60)
    agent = InstitutionalFlowAgent(cfg=cfg, push_feed=True)
    for i in range(20):
        t = s(i * 10)
        agent.on_spot_tick(Tick(t, 2400.0, 2400.2))
        basis = 12.0 + (0.1 if i % 2 else -0.1)
        agent.on_futures_quote(FuturesQuote(t, "GCQ4", 2400.1 + basis - 0.1, 2400.1 + basis + 0.1,
                                            open_interest=100_000 + i * 100))
    t = s(200)
    agent.on_spot_tick(Tick(t, 2400.0, 2400.2))
    agent.on_futures_quote(FuturesQuote(t, "GCQ4", 2414.0, 2414.2, open_interest=102_000))
    f = agent.features(t)
    assert f.values["inst_basis"] == pytest.approx(14.0)
    assert f.values["inst_basis_z"] > 3
    # 60s back from t=200 -> quote at t=140 (OI 101_400)
    assert f.values["inst_oi_change"] == pytest.approx(600)
    assert f.values["inst_oi_change_pct"] == pytest.approx(600 / 101_400 * 100)


def test_basis_needs_min_samples():
    agent = InstitutionalFlowAgent(push_feed=True)
    agent.on_spot_tick(Tick(T0, 2400.0, 2400.2))
    agent.on_futures_quote(FuturesQuote(T0, "GC", 2410.0, 2410.2))
    f = agent.features(T0)
    assert f.values["inst_basis"] == pytest.approx(10.0) and f.values["inst_basis_z"] == 0.0


def test_cot_percentile_respects_release_lag(tmp_path):
    p = tmp_path / "cot.csv"
    rows = ["Market_and_Exchange_Names,Report_Date_as_YYYY-MM-DD,M_Money_Positions_Long_All,"
            "M_Money_Positions_Short_All,Open_Interest_All"]
    nets = [10, 50, 30, 20, 90]
    for i, n in enumerate(nets):
        d = (datetime(2024, 1, 2) + timedelta(weeks=i)).date().isoformat()
        rows.append(f'GOLD - COMMODITY EXCHANGE INC.,{d},"{100 + n:,}",100,500000')
    rows.append("SILVER - COMMODITY EXCHANGE INC.,2024-02-27,999999,0,1")
    p.write_text("\n".join(rows) + "\n")
    recs = CotCsvSource(p).reports()
    assert len(recs) == 5 and recs[-1].net == 90
    agent = InstitutionalFlowAgent(cot=CotCsvSource(p))
    agent.poll(datetime(2024, 3, 1, tzinfo=timezone.utc))
    assert agent.features(datetime(2024, 3, 1, tzinfo=timezone.utc)).values["inst_cot_mm_net_pct"] == 1.0
    # on the Tuesday of the last report it is not yet published: latest usable net=20 -> 2/4
    f = agent.features(datetime(2024, 1, 30, tzinfo=timezone.utc))
    assert f.values["inst_cot_mm_net_pct"] == pytest.approx(0.5)


def test_cot_simple_columns(tmp_path):
    p = tmp_path / "cot.csv"
    p.write_text("date,mm_long,mm_short\n2024-01-02,10,5\n2024-01-09,12,1\n")
    assert [r.net for r in CotCsvSource(p).reports()] == [5, 11]
    agent = InstitutionalFlowAgent()
    agent.load_cot([CotRecord(T0, 1, 0)])
    assert agent.features(T0 + timedelta(days=30)).values["inst_cot_mm_net_pct"] == 0.5   # unconfigured


def _ticks(agent, mids):
    for i, m in enumerate(mids):
        agent.on_spot_tick(Tick(s(i * 5), m - 0.1, m + 0.1))


def test_liquidity_sweep_high_and_low():
    cfg = InstitutionalConfig(sweep_reversal_seconds=20, sweep_min_pierce=0.3)
    agent = InstitutionalFlowAgent(cfg=cfg)
    # range 2400-2402 for a while, spike to 2403 and back to 2401.5 within 20s
    _ticks(agent, [2400, 2401, 2402, 2401, 2400.5, 2401, 2403, 2401.5])
    f = agent.features(s(35))
    assert f.values["spot_liquidity_sweep"] == -1.0 and f.values["inst_sweep_available"] == 1.0
    assert f.available is False    # sweep is spot price action, not institutional data

    agent = InstitutionalFlowAgent(cfg=cfg)
    _ticks(agent, [2401, 2400, 2402, 2401, 2401.5, 2401, 2399.2, 2400.6])
    assert agent.features(s(35)).values["spot_liquidity_sweep"] == 1.0

    agent = InstitutionalFlowAgent(cfg=cfg)
    _ticks(agent, [2400, 2401, 2402, 2401, 2400.5, 2401, 2403, 2403.5])   # breakout, no reversal
    assert agent.features(s(35)).values["spot_liquidity_sweep"] == 0.0

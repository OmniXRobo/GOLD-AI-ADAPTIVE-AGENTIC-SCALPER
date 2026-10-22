from datetime import datetime, timedelta, timezone

from gold_ai.collector import TickCollector
from gold_ai.domain import Tick
from gold_ai.market.ingest import QualityReport, load_tick_file


def test_mt5_export_parse_and_carry_forward(tmp_path):
    p = tmp_path / "ticks.csv"
    p.write_text("<DATE>\t<TIME>\t<BID>\t<ASK>\t<LAST>\t<VOLUME>\t<FLAGS>\n"
                 "2024.01.02\t01:00:00.100\t2063.10\t2063.30\t\t\t6\n"
                 "2024.01.02\t01:00:00.400\t2063.15\t\t\t\t2\n"
                 "2024.01.02\t01:00:01.000\t\t2063.40\t\t\t4\n")
    ticks = load_tick_file(p, tz_offset_hours=2)
    assert len(ticks) == 3
    assert ticks[0].time == datetime(2024, 1, 1, 23, 0, 0, 100000, tzinfo=timezone.utc)
    assert ticks[1].bid == 2063.15 and ticks[1].ask == 2063.30
    assert ticks[2].ask == 2063.40


def test_validation_drops_bad_rows(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text("time,bid,ask\n"
                 "2024-01-02T00:00:00Z,2000,2000.2\n"
                 "2024-01-02T00:00:01Z,0,2000.2\n"          # nonpositive
                 "2024-01-02T00:00:02Z,2000.5,2000.1\n"     # crossed
                 "2024-01-02T00:00:03Z,2100,2100.2\n"       # spike, reverted next
                 "2024-01-02T00:00:04Z,2000.1,2000.3\n"
                 "2024-01-02T00:00:00Z,2000.1,2000.3\n")    # out of order
    rep = QualityReport()
    ticks = load_tick_file(p, report=rep)
    assert [t.bid for t in ticks] == [2000, 2000.1]
    assert rep.dropped_nonpositive == 1 and rep.dropped_crossed == 1
    assert rep.dropped_spikes == 1 and rep.dropped_out_of_order == 1


def test_persistent_gap_is_kept(tmp_path):
    p = tmp_path / "g.csv"
    p.write_text("time,bid,ask\n2024-01-02T00:00:00Z,2000,2000.2\n2024-01-02T00:00:01Z,2050,2050.2\n"
                 "2024-01-02T00:00:02Z,2051,2051.2\n")
    assert len(load_tick_file(p)) == 3


class FakeConn:
    def __init__(self, ticks):
        self.ticks = ticks
        self.calls = []

    def ticks_range(self, symbol, start, end):
        self.calls.append((start, end))
        return [t for t in self.ticks if start <= t.time <= end]


def test_collector_resumes_from_cursor(store):
    t0 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    ticks = [Tick(t0 + timedelta(seconds=i), 2000 + i, 2000.2 + i) for i in range(10)]
    conn = FakeConn(ticks)
    c = TickCollector(conn, store, "exness", "XAUUSDm", backfill=timedelta(seconds=30))
    assert c.collect_once(now=t0 + timedelta(seconds=4.5)) == 5
    c2 = TickCollector(conn, store, "exness", "XAUUSDm")   # restart
    assert c2.collect_once(now=t0 + timedelta(seconds=20)) == 5
    stored = store.load_ticks("exness", "XAUUSDm")
    assert len(stored) == 10 and len({t.time for t in stored}) == 10

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


def test_backfill_stops_at_first_stored_tick(store):
    from gold_ai.collector import backfill_history
    t0 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    ticks = [Tick(t0 + timedelta(minutes=i), 2000 + i, 2000.2 + i) for i in range(60)]
    store.save_ticks("exness", "XAUUSDm", ticks[40:], source="mt5")          # live collector already has these
    n = backfill_history(FakeConn(ticks), store, "exness", "XAUUSDm", t0, chunk=timedelta(minutes=7))
    assert n == 40
    stored = store.load_ticks("exness", "XAUUSDm")
    assert len(stored) == 60 and len({t.time for t in stored}) == 60


def test_collector_catches_up_in_short_slices(store):
    """After a long gap the collector copies `max_span` at a time instead of hours in one read and one write."""
    t0 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    ticks = [Tick(t0 + timedelta(seconds=i), 2000 + i % 7, 2000.2 + i % 7) for i in range(0, 3600, 2)]
    conn = FakeConn(ticks)
    c = TickCollector(conn, store, "exness", "XAUUSDm", backfill=timedelta(hours=1), max_span=timedelta(minutes=10))
    now = t0 + timedelta(hours=1)
    total, calls = 0, 0
    while True:
        total += c.collect_once(now=now)
        calls += 1
        if not c.behind:
            break
    assert calls == 6 and total == len(ticks)
    assert all(end - start <= timedelta(minutes=10) for start, end in conn.calls)
    assert len(store.load_ticks("exness", "XAUUSDm")) == len(ticks)


def test_collector_skips_an_empty_slice(store):
    t0 = datetime(2024, 1, 6, tzinfo=timezone.utc)          # weekend gap, then ticks
    ticks = [Tick(t0 + timedelta(minutes=50, seconds=i), 2000.0, 2000.2) for i in range(10)]
    conn = FakeConn(ticks)
    c = TickCollector(conn, store, "exness", "XAUUSDm", backfill=timedelta(hours=1), max_span=timedelta(minutes=10))
    c.empty_confirm = timedelta(0)
    got = sum(c.collect_once(now=t0 + timedelta(hours=1)) for _ in range(10))   # 4 empty slices, each confirmed
    assert got == 10 and len(c.skipped) == 4


class LateHistoryConn(FakeConn):
    """A terminal still downloading history: the first request for a range answers nothing."""
    def __init__(self, ticks):
        super().__init__(ticks)
        self.asked = set()

    def ticks_range(self, symbol, start, end):
        if start not in self.asked:
            self.asked.add(start)
            return []
        return super().ticks_range(symbol, start, end)


def test_collector_does_not_skip_on_a_single_empty_answer(store):
    t0 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    ticks = [Tick(t0 + timedelta(minutes=i), 2000.0, 2000.2) for i in range(60)]
    c = TickCollector(LateHistoryConn(ticks), store, "exness", "XAUUSDm", backfill=timedelta(hours=1),
                      max_span=timedelta(minutes=15))
    now = t0 + timedelta(hours=1)
    got = sum(c.collect_once(now=now) for _ in range(20))
    assert got == 60 and c.skipped == []


class SecondsConn(FakeConn):
    """Like MT5: copy_ticks_range only takes whole seconds, so the start is floored."""
    def ticks_range(self, symbol, start, end):
        return super().ticks_range(symbol, start.replace(microsecond=0), end)


def test_collector_passes_a_break_after_a_fractional_second_tick(store):
    t0 = datetime(2024, 1, 2, 21, 58, 59, 984000, tzinfo=timezone.utc)   # last tick before the daily break
    ticks = [Tick(t0 - timedelta(milliseconds=500), 2000.0, 2000.2), Tick(t0, 2000.1, 2000.3),
             Tick(t0 + timedelta(hours=1, minutes=1), 2001.0, 2001.2)]
    conn = SecondsConn(ticks)
    c = TickCollector(conn, store, "exness", "XAUUSDm", backfill=timedelta(seconds=5), max_span=timedelta(minutes=15))
    now = t0 + timedelta(seconds=1)
    assert c.collect_once(now=now) == 2
    now = t0 + timedelta(hours=1, minutes=2)
    c.empty_confirm = timedelta(0)
    got = 0
    for _ in range(10):
        got += c.collect_once(now=now)
        if not c.behind:
            break
    assert got == 1 and not c.behind
    stored = store.load_ticks("exness", "XAUUSDm")
    assert len(stored) == 3 and len({t.time for t in stored}) == 3   # nothing stored twice


def test_save_ticks_commits_in_batches(store):
    t0 = datetime(2024, 1, 2, tzinfo=timezone.utc)
    ticks = [Tick(t0 + timedelta(milliseconds=i), 2000.0, 2000.2) for i in range(12_345)]
    assert store.save_ticks("exness", "XAUUSDm", ticks, source="mt5", batch=5000) == 12_345
    assert len(store.load_ticks("exness", "XAUUSDm")) == 12_345
    r = store.checkpoint("TRUNCATE")
    assert r is None or set(r) == {"busy", "wal_pages", "checkpointed"}

from datetime import datetime, timedelta, timezone

import pytest

from gold_ai.domain import Tick
from gold_ai.memory.store import MemoryStore
from gold_ai.memory.tick_archive import TickArchive, archive_old_ticks


@pytest.fixture
def store(tmp_path):
    s = MemoryStore(f"sqlite:///{tmp_path / 'db.sqlite'}")
    s.tick_archive = TickArchive(tmp_path / "archive")
    return s


def _ticks(t0, n, step=timedelta(hours=6)):
    return [Tick(t0 + i * step, 2000.0 + i, 2000.3 + i, 0.0) for i in range(n)]


def test_old_days_move_to_archive_and_load_ticks_still_sees_them(store, tmp_path):
    t0 = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
    ticks = _ticks(t0, 40)                                  # 10 days, 4 ticks a day
    store.save_ticks("equiti", "XAUUSD.sd", ticks, source="mt5")
    store.save_ticks("equiti", "EURUSD.sd", ticks[:8], source="mt5")
    cutoff = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
    done = archive_old_ticks(store, store.tick_archive, cutoff)
    assert done == {"equiti:XAUUSD.sd": 20, "equiti:EURUSD.sd": 8}
    assert store.first_db_tick_time("equiti", "XAUUSD.sd") == datetime(2026, 10, 6, 1, tzinfo=timezone.utc)
    assert len(store.tick_archive.days("equiti", "XAUUSD.sd")) == 5
    # Readers see the full history, in order, nothing twice.
    got = store.load_ticks("equiti", "XAUUSD.sd")
    assert [t.time for t in got] == [t.time for t in ticks] and got[3].bid == ticks[3].bid
    part = store.load_ticks("equiti", "XAUUSD.sd", t0 + timedelta(days=3), t0 + timedelta(days=7))
    assert [t.time for t in part] == [t.time for t in ticks[12:28]]
    assert store.first_tick_time("equiti", "XAUUSD.sd") == t0
    assert store.tick_range("equiti", "XAUUSD.sd") == (t0, ticks[-1].time)
    assert store.load_ticks("equiti", "EURUSD.sd") and store.first_db_tick_time("equiti", "EURUSD.sd") is None
    # Running again archives nothing new and never touches the archive files.
    assert archive_old_ticks(store, store.tick_archive, cutoff) == {}


def test_archiving_a_day_twice_does_not_duplicate(store):
    t0 = datetime(2026, 10, 1, 1, tzinfo=timezone.utc)
    store.save_ticks("equiti", "XAUUSD.sd", _ticks(t0, 2), source="mt5")
    archive_old_ticks(store, store.tick_archive, t0 + timedelta(days=2))
    store.save_ticks("equiti", "XAUUSD.sd", _ticks(t0, 3), source="mt5")    # same day re-collected + one more
    archive_old_ticks(store, store.tick_archive, t0 + timedelta(days=2))
    assert len(store.load_ticks("equiti", "XAUUSD.sd")) == 3


def test_tick_pairs(store):
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for b, s in [("exness", "XAUUSDm"), ("equiti", "XAUUSD.sd"), ("equiti", "EURUSD.sd")]:
        store.save_ticks(b, s, _ticks(t0, 2), source="mt5")
    assert store.tick_pairs() == [("equiti", "EURUSD.sd"), ("equiti", "XAUUSD.sd"), ("exness", "XAUUSDm")]

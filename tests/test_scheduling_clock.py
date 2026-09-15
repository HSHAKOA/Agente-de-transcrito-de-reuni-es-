from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from meeting_transcriber.scheduling.clock import ManualClock, SystemClock


def test_system_clock_returns_aware_utc_now():
    clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_manual_clock_starts_at_given_instant():
    start = datetime(2026, 9, 15, 22, 0, tzinfo=timezone.utc)
    clock = ManualClock(start)
    assert clock.now() == start


def test_manual_clock_defaults_to_real_now_when_unset():
    clock = ManualClock()
    assert clock.now().tzinfo is not None


def test_manual_clock_rejects_naive_datetime():
    with pytest.raises(ValueError):
        ManualClock(datetime(2026, 9, 15, 22, 0))


def test_manual_clock_set_changes_now():
    clock = ManualClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    new_time = datetime(2026, 6, 1, tzinfo=timezone.utc)
    clock.set(new_time)
    assert clock.now() == new_time


def test_manual_clock_set_rejects_naive_datetime():
    clock = ManualClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(ValueError):
        clock.set(datetime(2026, 6, 1))


def test_manual_clock_advance_by_seconds():
    clock = ManualClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    result = clock.advance(seconds=90)
    assert result == datetime(2026, 1, 1, 0, 1, 30, tzinfo=timezone.utc)
    assert clock.now() == result


def test_manual_clock_advance_by_named_kwargs():
    clock = ManualClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    clock.advance(hours=5, minutes=30)
    assert clock.now() == datetime(2026, 1, 1, 5, 30, tzinfo=timezone.utc)


def test_manual_clock_never_advances_on_its_own():
    """Ao contrario de um relogio de verdade, ManualClock so muda quando
    set/advance sao chamados -- garante que os testes do engine nunca
    dependem, nem por acidente, de tempo real passando durante a execucao."""
    clock = ManualClock(datetime(2026, 1, 1, tzinfo=timezone.utc))
    first = clock.now()
    import time

    time.sleep(0.05)
    second = clock.now()
    assert first == second

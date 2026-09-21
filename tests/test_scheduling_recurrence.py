from __future__ import annotations

from datetime import datetime, timezone

import pytest

from meeting_transcriber.scheduling.models import (
    RECURRENCE_CUSTOM_DAYS,
    RECURRENCE_DAILY,
    RECURRENCE_ONCE,
    RECURRENCE_WEEKDAYS,
    RECURRENCE_WEEKLY,
    Recurrence,
    Schedule,
)
from meeting_transcriber.scheduling.recurrence import (
    InvalidTimeZone,
    iter_occurrences,
    next_occurrence,
    occurrence_window_for_date,
    resolve_zone,
    to_schedule_zone,
)


def _schedule(**overrides) -> Schedule:
    defaults = dict(
        id="sch_1",
        title="Aula de Calculo",
        scheduled_date="2026-09-15",
        start_time="19:00",
        end_time="20:40",
        timezone="America/Sao_Paulo",
        meetings_root="D:\\Reunioes\\Faculdade",
        recurrence=Recurrence(type=RECURRENCE_ONCE),
    )
    defaults.update(overrides)
    return Schedule(**defaults)


def test_resolve_zone_valid():
    resolve_zone("America/Sao_Paulo")


def test_resolve_zone_invalid_raises():
    with pytest.raises(InvalidTimeZone):
        resolve_zone("Nao/Existe")


def test_to_schedule_zone_converts_utc_to_the_named_zone():
    moment = datetime(2026, 9, 15, 22, 0, tzinfo=timezone.utc)
    assert to_schedule_zone(moment, "America/Sao_Paulo").strftime("%H:%M") == "19:00"
    assert to_schedule_zone(moment, "Asia/Tokyo").strftime("%H:%M") == "07:00"


def test_to_schedule_zone_invalid_name_falls_back_instead_of_raising():
    """Uma mensagem de erro nunca pode derrubar o tick do scheduler."""
    moment = datetime(2026, 9, 15, 22, 0, tzinfo=timezone.utc)
    result = to_schedule_zone(moment, "Nao/Existe")
    assert result.tzinfo is not None
    assert result == moment  # mesmo instante, so muda a representacao


def test_occurrence_window_same_day():
    tz = resolve_zone("America/Sao_Paulo")
    start, end = occurrence_window_for_date(__import__("datetime").date(2026, 9, 15), "19:00", "20:40", tz)
    assert start < end
    assert (end - start).total_seconds() == 100 * 60
    assert start.tzinfo is not None


def test_occurrence_window_crosses_midnight():
    tz = resolve_zone("America/Sao_Paulo")
    day = __import__("datetime").date(2026, 9, 15)
    start, end = occurrence_window_for_date(day, "23:00", "01:00", tz)
    assert end > start
    assert (end - start).total_seconds() == 2 * 3600
    # o fim cai no dia seguinte no horario local
    assert end.astimezone(tz).date() == day + __import__("datetime").timedelta(days=1)


def test_once_produces_single_occurrence_on_its_date():
    schedule = _schedule()
    range_start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    range_end = datetime(2026, 10, 1, tzinfo=timezone.utc)
    occs = iter_occurrences(schedule, range_start, range_end)
    assert len(occs) == 1
    assert occs[0].occurrence_date.isoformat() == "2026-09-15"


def test_once_outside_range_produces_nothing():
    schedule = _schedule()
    range_start = datetime(2026, 10, 1, tzinfo=timezone.utc)
    range_end = datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert iter_occurrences(schedule, range_start, range_end) == []


def test_daily_produces_one_per_day():
    schedule = _schedule(recurrence=Recurrence(type=RECURRENCE_DAILY))
    range_start = datetime(2026, 9, 15, tzinfo=timezone.utc)
    range_end = datetime(2026, 9, 20, tzinfo=timezone.utc)
    occs = iter_occurrences(schedule, range_start, range_end, limit=10)
    dates = [o.occurrence_date.isoformat() for o in occs]
    assert dates == ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18", "2026-09-19"]


def test_daily_never_before_anchor_date():
    schedule = _schedule(scheduled_date="2026-09-15", recurrence=Recurrence(type=RECURRENCE_DAILY))
    range_start = datetime(2026, 9, 1, tzinfo=timezone.utc)  # antes da ancora
    range_end = datetime(2026, 9, 17, tzinfo=timezone.utc)
    occs = iter_occurrences(schedule, range_start, range_end, limit=10)
    assert all(o.occurrence_date.isoformat() >= "2026-09-15" for o in occs)
    assert occs[0].occurrence_date.isoformat() == "2026-09-15"


def test_weekdays_skips_weekend():
    # 2026-09-15 e uma terca-feira
    schedule = _schedule(scheduled_date="2026-09-14", recurrence=Recurrence(type=RECURRENCE_WEEKDAYS))
    range_start = datetime(2026, 9, 14, tzinfo=timezone.utc)
    range_end = datetime(2026, 9, 22, tzinfo=timezone.utc)
    occs = iter_occurrences(schedule, range_start, range_end, limit=10)
    weekdays = {o.occurrence_date.weekday() for o in occs}
    assert weekdays.issubset({0, 1, 2, 3, 4})
    assert 5 not in weekdays and 6 not in weekdays


def test_weekly_specific_day_only():
    # segunda-feira = 0; 2026-09-14 e segunda
    schedule = _schedule(
        scheduled_date="2026-09-14", start_time="19:00", end_time="20:00",
        recurrence=Recurrence(type=RECURRENCE_WEEKLY, days=[0]),
    )
    range_start = datetime(2026, 9, 14, tzinfo=timezone.utc)
    range_end = datetime(2026, 10, 5, tzinfo=timezone.utc)
    occs = iter_occurrences(schedule, range_start, range_end, limit=10)
    assert all(o.occurrence_date.weekday() == 0 for o in occs)
    assert len(occs) == 3  # 14, 21, 28 de setembro


def test_custom_days_multiple_weekdays():
    # segunda(0), terca(1), quarta(2), quinta(3)
    schedule = _schedule(
        scheduled_date="2026-09-14",
        recurrence=Recurrence(type=RECURRENCE_CUSTOM_DAYS, days=[0, 1, 2, 3]),
    )
    range_start = datetime(2026, 9, 14, tzinfo=timezone.utc)
    range_end = datetime(2026, 9, 21, tzinfo=timezone.utc)
    occs = iter_occurrences(schedule, range_start, range_end, limit=20)
    weekdays = {o.occurrence_date.weekday() for o in occs}
    assert weekdays == {0, 1, 2, 3}


def test_next_occurrence_after_now():
    schedule = _schedule(scheduled_date="2026-09-14", recurrence=Recurrence(type=RECURRENCE_DAILY))
    # 19:00 America/Sao_Paulo == 22:00 UTC -- "after" cai depois do horario
    # de 16/09 (22:00 UTC), entao a proxima ocorrencia so no dia seguinte.
    after = datetime(2026, 9, 16, 23, 0, tzinfo=timezone.utc)
    occ = next_occurrence(schedule, after)
    assert occ is not None
    assert occ.occurrence_date.isoformat() == "2026-09-17"


def test_next_occurrence_none_when_once_already_passed():
    schedule = _schedule(scheduled_date="2026-09-15")
    after = datetime(2026, 9, 16, tzinfo=timezone.utc)
    assert next_occurrence(schedule, after) is None


def test_iter_occurrences_respects_limit():
    schedule = _schedule(recurrence=Recurrence(type=RECURRENCE_DAILY))
    range_start = datetime(2026, 9, 15, tzinfo=timezone.utc)
    range_end = datetime(2027, 9, 15, tzinfo=timezone.utc)
    occs = iter_occurrences(schedule, range_start, range_end, limit=3)
    assert len(occs) == 3

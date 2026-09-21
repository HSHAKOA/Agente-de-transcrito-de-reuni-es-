from __future__ import annotations

from datetime import datetime, timezone

import pytest

from meeting_transcriber.scheduling.conflicts import find_conflicts, first_conflict_message
from meeting_transcriber.scheduling.models import STATUS_CANCELLED, Recurrence, Schedule


def _schedule(id_, start_time, end_time, **overrides) -> Schedule:
    defaults = dict(
        id=id_,
        title=f"Reuniao {id_}",
        scheduled_date="2026-09-15",
        start_time=start_time,
        end_time=end_time,
        timezone="America/Sao_Paulo",
        meetings_root="D:\\Reunioes",
        recurrence=Recurrence(),
    )
    defaults.update(overrides)
    return Schedule(**defaults)


NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)


def test_overlapping_windows_conflict():
    a = _schedule("a", "19:00", "20:00")
    b = _schedule("b", "19:30", "21:00")
    conflicts = find_conflicts(b, [a], NOW)
    assert len(conflicts) == 1
    assert conflicts[0].other_schedule.id == "a"


def test_adjacent_windows_do_not_conflict():
    a = _schedule("a", "19:00", "20:00")
    b = _schedule("b", "20:00", "21:00")
    assert find_conflicts(b, [a], NOW) == []


def test_non_overlapping_windows_do_not_conflict():
    a = _schedule("a", "19:00", "20:00")
    b = _schedule("b", "21:00", "22:00")
    assert find_conflicts(b, [a], NOW) == []


def test_cancelled_schedule_never_conflicts():
    a = _schedule("a", "19:00", "20:00", status=STATUS_CANCELLED)
    b = _schedule("b", "19:00", "20:00")
    assert find_conflicts(b, [a], NOW) == []


def test_schedule_does_not_conflict_with_itself():
    a = _schedule("a", "19:00", "20:00")
    assert find_conflicts(a, [a], NOW) == []


def test_conflict_message_matches_expected_format():
    a = _schedule("a", "19:00", "20:00", title="Projeto ERP")
    b = _schedule("b", "19:30", "21:00")
    message = first_conflict_message(b, [a], NOW)
    assert message is not None
    assert "Projeto ERP" in message
    assert "Altere um dos horarios" in message


@pytest.mark.parametrize("tz_name", ["America/Sao_Paulo", "Asia/Tokyo"])
def test_conflict_message_shows_times_in_the_schedules_own_timezone(tz_name):
    """O horario citado e o de parede do agendamento ("19:00"), nunca o do
    computador que roda o app -- duas zonas com offsets diferentes pra o
    teste nao passar por coincidencia com o fuso da maquina (o CI roda em
    UTC)."""
    a = _schedule("a", "19:00", "20:00", timezone=tz_name)
    b = _schedule("b", "19:30", "21:00", timezone=tz_name)
    message = first_conflict_message(b, [a], NOW)
    assert "15/09 19:00 - 20:00" in message


def test_no_conflict_message_when_no_overlap():
    a = _schedule("a", "19:00", "20:00")
    b = _schedule("b", "21:00", "22:00")
    assert first_conflict_message(b, [a], NOW) is None

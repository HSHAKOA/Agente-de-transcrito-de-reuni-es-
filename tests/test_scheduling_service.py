from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from meeting_transcriber.scheduling.models import STATUS_CANCELLED, STATUS_RECORDING, ScheduleRun
from meeting_transcriber.scheduling.service import ScheduleService, ValidationError
from meeting_transcriber.scheduling.store import ScheduleStore


def _body(tmp_path: Path, **overrides) -> dict:
    body = dict(
        title="Aula de Calculo",
        scheduled_date="2026-09-15",
        start_time="19:00",
        end_time="20:40",
        timezone="America/Sao_Paulo",
        meetings_root=str(tmp_path / "Faculdade"),
        system_audio_enabled=True,
        microphone_enabled=False,
    )
    body.update(overrides)
    return body


@pytest.fixture
def service(tmp_path: Path) -> ScheduleService:
    store = ScheduleStore(tmp_path / "schedules.json")
    fixed_now = lambda: datetime(2026, 9, 1, tzinfo=timezone.utc)
    return ScheduleService(store, now_fn=fixed_now)


def test_create_valid_schedule(service: ScheduleService, tmp_path: Path):
    schedule = service.create(_body(tmp_path))
    assert schedule.id.startswith("sch_")
    assert schedule.title == "Aula de Calculo"
    assert service.get(schedule.id) is not None


def test_create_rejects_no_audio_source(service: ScheduleService, tmp_path: Path):
    with pytest.raises(ValidationError):
        service.create(_body(tmp_path, system_audio_enabled=False, microphone_enabled=False))


def test_create_rejects_end_before_start(service: ScheduleService, tmp_path: Path):
    with pytest.raises(ValidationError):
        service.create(_body(tmp_path, start_time="19:00", end_time="08:00"))  # 13h, estoura o teto


def test_create_allows_overnight_window(service: ScheduleService, tmp_path: Path):
    schedule = service.create(_body(tmp_path, start_time="23:00", end_time="01:00"))
    assert schedule.start_time == "23:00"


def test_create_detects_conflict_with_existing(service: ScheduleService, tmp_path: Path):
    service.create(_body(tmp_path, title="Projeto ERP", start_time="19:00", end_time="20:00"))
    with pytest.raises(ValidationError, match="Projeto ERP"):
        service.create(_body(tmp_path, title="Outra", start_time="19:30", end_time="21:00"))


def test_create_allows_non_overlapping(service: ScheduleService, tmp_path: Path):
    service.create(_body(tmp_path, title="Projeto ERP", start_time="19:00", end_time="20:00"))
    schedule = service.create(_body(tmp_path, title="Outra", start_time="20:00", end_time="21:00"))
    assert schedule.title == "Outra"


def test_list_all_returns_created_schedules(service: ScheduleService, tmp_path: Path):
    service.create(_body(tmp_path, title="A"))
    service.create(_body(tmp_path, title="B", start_time="21:00", end_time="22:00"))
    titles = {s.title for s in service.list_all()}
    assert titles == {"A", "B"}


def test_update_changes_fields(service: ScheduleService, tmp_path: Path):
    schedule = service.create(_body(tmp_path))
    updated = service.update(schedule.id, _body(tmp_path, title="Novo Titulo"))
    assert updated.title == "Novo Titulo"
    assert service.get(schedule.id).title == "Novo Titulo"


def test_update_resets_current_run(service: ScheduleService, tmp_path: Path):
    schedule = service.create(_body(tmp_path))
    schedule.current_run = ScheduleRun(
        occurrence_date="2026-09-15", scheduled_start_at="x", scheduled_end_at="y",
    )
    service._store.save(schedule)
    updated = service.update(schedule.id, _body(tmp_path, start_time="20:00", end_time="21:00"))
    assert updated.current_run is None


def test_update_refuses_when_recording(service: ScheduleService, tmp_path: Path):
    schedule = service.create(_body(tmp_path))
    schedule.current_run = ScheduleRun(
        occurrence_date="2026-09-15", scheduled_start_at="x", scheduled_end_at="y", status=STATUS_RECORDING,
    )
    service._store.save(schedule)
    with pytest.raises(ValidationError):
        service.update(schedule.id, _body(tmp_path, title="Outro"))


def test_update_unknown_schedule_raises(service: ScheduleService, tmp_path: Path):
    with pytest.raises(ValidationError):
        service.update("nao-existe", _body(tmp_path))


def test_update_checks_conflict_excluding_self(service: ScheduleService, tmp_path: Path):
    schedule = service.create(_body(tmp_path, title="A", start_time="19:00", end_time="20:00"))
    # editar mantendo o mesmo horario nao deve "conflitar consigo mesmo"
    updated = service.update(schedule.id, _body(tmp_path, title="A", start_time="19:00", end_time="20:00"))
    assert updated.title == "A"


def test_update_still_detects_conflict_with_others(service: ScheduleService, tmp_path: Path):
    service.create(_body(tmp_path, title="Projeto ERP", start_time="19:00", end_time="20:00"))
    other = service.create(_body(tmp_path, title="Outra", start_time="21:00", end_time="22:00"))
    with pytest.raises(ValidationError, match="Projeto ERP"):
        service.update(other.id, _body(tmp_path, title="Outra", start_time="19:30", end_time="21:30"))


def test_cancel_marks_cancelled(service: ScheduleService, tmp_path: Path):
    schedule = service.create(_body(tmp_path))
    cancelled = service.cancel(schedule.id)
    assert cancelled.status == STATUS_CANCELLED


def test_cancel_refuses_when_recording(service: ScheduleService, tmp_path: Path):
    schedule = service.create(_body(tmp_path))
    schedule.current_run = ScheduleRun(
        occurrence_date="2026-09-15", scheduled_start_at="x", scheduled_end_at="y", status=STATUS_RECORDING,
    )
    service._store.save(schedule)
    with pytest.raises(ValidationError):
        service.cancel(schedule.id)


def test_cancel_unknown_schedule_raises(service: ScheduleService):
    with pytest.raises(ValidationError):
        service.cancel("nao-existe")


def test_cancelled_schedule_no_longer_conflicts(service: ScheduleService, tmp_path: Path):
    schedule = service.create(_body(tmp_path, title="A", start_time="19:00", end_time="20:00"))
    service.cancel(schedule.id)
    new = service.create(_body(tmp_path, title="B", start_time="19:00", end_time="20:00"))
    assert new.title == "B"

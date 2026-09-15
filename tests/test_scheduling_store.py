from __future__ import annotations

from pathlib import Path

from meeting_transcriber.scheduling.models import Recurrence, Schedule
from meeting_transcriber.scheduling.store import ScheduleStore


def _schedule(id_="sch_1") -> Schedule:
    return Schedule(
        id=id_,
        title="Aula de Calculo",
        scheduled_date="2026-09-15",
        start_time="19:00",
        end_time="20:40",
        timezone="America/Sao_Paulo",
        meetings_root="D:\\Reunioes\\Faculdade",
        recurrence=Recurrence(),
    )


def test_list_all_empty_when_file_missing(tmp_path: Path):
    store = ScheduleStore(tmp_path / "schedules.json")
    assert store.list_all() == []


def test_save_then_get_round_trips(tmp_path: Path):
    store = ScheduleStore(tmp_path / "schedules.json")
    schedule = _schedule()
    store.save(schedule)
    loaded = store.get("sch_1")
    assert loaded is not None
    assert loaded.title == "Aula de Calculo"
    assert loaded.timezone == "America/Sao_Paulo"


def test_save_is_atomic_no_leftover_tmp_files(tmp_path: Path):
    store = ScheduleStore(tmp_path / "schedules.json")
    store.save(_schedule())
    store.save(_schedule())
    assert list(tmp_path.glob("*.tmp-*")) == []


def test_list_all_sorted_by_created_at(tmp_path: Path):
    store = ScheduleStore(tmp_path / "schedules.json")
    a = _schedule("a")
    a.created_at = "2026-01-01T00:00:00"
    b = _schedule("b")
    b.created_at = "2025-01-01T00:00:00"
    store.save(a)
    store.save(b)
    ids = [s.id for s in store.list_all()]
    assert ids == ["b", "a"]


def test_delete_removes_schedule(tmp_path: Path):
    store = ScheduleStore(tmp_path / "schedules.json")
    store.save(_schedule())
    assert store.delete("sch_1") is True
    assert store.get("sch_1") is None


def test_delete_returns_false_when_not_found(tmp_path: Path):
    store = ScheduleStore(tmp_path / "schedules.json")
    assert store.delete("nao-existe") is False


def test_corrupted_entry_is_skipped_not_fatal(tmp_path: Path):
    path = tmp_path / "schedules.json"
    store = ScheduleStore(path)
    store.save(_schedule("good"))
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    data["broken"] = {"id": "broken"}  # faltando campos obrigatorios
    path.write_text(json.dumps(data), encoding="utf-8")

    schedules = store.list_all()
    assert [s.id for s in schedules] == ["good"]


def test_current_run_and_history_round_trip(tmp_path: Path):
    from meeting_transcriber.scheduling.models import STATUS_RECORDING, ScheduleRun

    store = ScheduleStore(tmp_path / "schedules.json")
    schedule = _schedule()
    schedule.current_run = ScheduleRun(
        occurrence_date="2026-09-15",
        scheduled_start_at="2026-09-15T22:00:00+00:00",
        scheduled_end_at="2026-09-15T23:40:00+00:00",
        status=STATUS_RECORDING,
        meeting_id="2026-09-15_1900_Aula_ab12ef",
    )
    store.save(schedule)

    loaded = store.get(schedule.id)
    assert loaded.current_run is not None
    assert loaded.current_run.status == STATUS_RECORDING
    assert loaded.current_run.meeting_id == "2026-09-15_1900_Aula_ab12ef"

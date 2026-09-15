from __future__ import annotations

from pathlib import Path

import pytest

from meeting_transcriber.storage.db import connect
from meeting_transcriber.storage.repository import MeetingRepository


@pytest.fixture
def repo(tmp_path: Path) -> MeetingRepository:
    conn = connect(tmp_path / "meetings.db")
    return MeetingRepository(conn)


def _meeting(id_="m1", **overrides) -> dict:
    data = dict(
        id=id_,
        title="Reuniao de teste",
        status="completed",
        started_at="2026-09-15T19:00:00+00:00",
        finished_at="2026-09-15T20:00:00+00:00",
        duration_seconds=3600.0,
        root_directory="D:\\Reunioes",
        meeting_directory=f"D:\\Reunioes\\{id_}",
        language="pt",
        model="small",
        system_audio_enabled=True,
        system_device_id=None,
        system_device_name=None,
        microphone_enabled=False,
        microphone_device_id=None,
        microphone_device_name=None,
    )
    data.update(overrides)
    return data


def test_upsert_then_get_round_trips(repo: MeetingRepository):
    repo.upsert_meeting(_meeting())
    loaded = repo.get_meeting("m1")
    assert loaded is not None
    assert loaded["title"] == "Reuniao de teste"
    assert loaded["created_at"] is not None
    assert loaded["deleted_at"] is None


def test_upsert_twice_updates_instead_of_duplicating(repo: MeetingRepository):
    repo.upsert_meeting(_meeting(title="Original"))
    repo.upsert_meeting(_meeting(title="Atualizado"))
    assert repo.get_meeting("m1")["title"] == "Atualizado"
    assert repo.count_meetings() == 1


def test_get_meeting_returns_none_when_not_found(repo: MeetingRepository):
    assert repo.get_meeting("nao-existe") is None


def test_list_meetings_orders_by_started_at_desc(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", started_at="2026-09-01T00:00:00+00:00"))
    repo.upsert_meeting(_meeting("m2", started_at="2026-09-15T00:00:00+00:00"))
    ids = [m["id"] for m in repo.list_meetings()]
    assert ids == ["m2", "m1"]


def test_list_meetings_filters_by_status(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", status="completed"))
    repo.upsert_meeting(_meeting("m2", status="failed"))
    result = repo.list_meetings(status="failed")
    assert [m["id"] for m in result] == ["m2"]


def test_list_meetings_pagination(repo: MeetingRepository):
    for i in range(5):
        repo.upsert_meeting(_meeting(f"m{i}", started_at=f"2026-09-{i+1:02d}T00:00:00+00:00"))
    page1 = repo.list_meetings(limit=2, offset=0)
    page2 = repo.list_meetings(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert {m["id"] for m in page1}.isdisjoint({m["id"] for m in page2})


def test_list_meetings_excludes_deleted_by_default(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    repo.soft_delete_meeting("m1")
    assert repo.list_meetings() == []
    assert len(repo.list_meetings(include_deleted=True)) == 1


def test_count_meetings_matches_list_length(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    repo.upsert_meeting(_meeting("m2"))
    assert repo.count_meetings() == 2


def test_soft_delete_never_removes_the_row(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    assert repo.soft_delete_meeting("m1") is True
    loaded = repo.get_meeting("m1")
    assert loaded is not None
    assert loaded["deleted_at"] is not None


def test_soft_delete_returns_false_when_not_found(repo: MeetingRepository):
    assert repo.soft_delete_meeting("nao-existe") is False


def test_soft_delete_twice_returns_false_second_time(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    assert repo.soft_delete_meeting("m1") is True
    assert repo.soft_delete_meeting("m1") is False


def test_replace_segments_then_list(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    repo.replace_segments("m1", [
        {"start_seconds": 0.0, "end_seconds": 5.0, "text": "ola"},
        {"start_seconds": 5.0, "end_seconds": 10.0, "text": "mundo", "speaker_label": "Você"},
    ])
    segments = repo.list_segments("m1")
    assert [s["text"] for s in segments] == ["ola", "mundo"]
    assert segments[1]["speaker_label"] == "Você"
    assert segments[0]["sequence"] == 0


def test_replace_segments_is_idempotent_no_duplication(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    repo.replace_segments("m1", [{"start_seconds": 0.0, "end_seconds": 5.0, "text": "primeira versao"}])
    repo.replace_segments("m1", [{"start_seconds": 0.0, "end_seconds": 5.0, "text": "segunda versao"}])
    segments = repo.list_segments("m1")
    assert len(segments) == 1
    assert segments[0]["text"] == "segunda versao"


def test_search_meetings_by_title(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", title="Reuniao Projeto ERP"))
    repo.upsert_meeting(_meeting("m2", title="Aula de Calculo"))
    results = repo.search_meetings("ERP")
    assert [m["id"] for m in results] == ["m1"]


def test_search_meetings_by_segment_text(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", title="Reuniao A"))
    repo.replace_segments("m1", [{"start_seconds": 0, "end_seconds": 1, "text": "vamos falar de orcamento"}])
    repo.upsert_meeting(_meeting("m2", title="Reuniao B"))
    repo.replace_segments("m2", [{"start_seconds": 0, "end_seconds": 1, "text": "assunto totalmente diferente"}])

    results = repo.search_meetings("orcamento")
    assert [m["id"] for m in results] == ["m1"]


def test_search_meetings_empty_query_returns_nothing(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    assert repo.search_meetings("") == []


def test_search_meetings_no_match_returns_empty(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", title="Reuniao A"))
    assert repo.search_meetings("termo-que-nao-existe-em-nada") == []


def test_search_meetings_excludes_deleted(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", title="Reuniao Especial"))
    repo.soft_delete_meeting("m1")
    assert repo.search_meetings("Especial") == []


def test_search_meetings_handles_special_characters_safely(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", title='Titulo com "aspas" e * asterisco'))
    # nao deveria lancar excecao nenhuma, mesmo com sintaxe especial do FTS5
    repo.search_meetings('"aspas" * (parenteses) OR AND NOT -algo')

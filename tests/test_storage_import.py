from __future__ import annotations

from pathlib import Path

import pytest

from meeting_transcriber.session import MeetingSession
from meeting_transcriber.storage.db import connect
from meeting_transcriber.storage.import_filesystem import (
    SPEAKER_LABEL_MICROPHONE,
    SPEAKER_LABEL_MIXED,
    SPEAKER_LABEL_SYSTEM,
    import_all,
    import_meeting,
    parse_markdown_segments,
)
from meeting_transcriber.storage.repository import MeetingRepository


@pytest.fixture
def repo(tmp_path: Path) -> MeetingRepository:
    conn = connect(tmp_path / "meetings.db")
    return MeetingRepository(conn)


def _make_meeting_dir(tmp_path: Path, meeting_id: str, **overrides) -> Path:
    base_dir = tmp_path / "roots" / "raiz1"
    transcript_path = tmp_path / f"{meeting_id}.md"
    session = MeetingSession.create(
        base_dir=base_dir,
        title=overrides.pop("title", "Reuniao de Teste"),
        model="small",
        language="pt",
        device="cpu",
        transcript_path=transcript_path,
        meeting_id=meeting_id,
        **overrides,
    )
    transcript_path.write_text(
        "# Titulo\n\n## Transcricao\n\n"
        "**[00:00:00]** Primeiro segmento.\n\n"
        "**[00:00:05]** Segundo segmento.\n\n"
        "---\n\n*Duracao total gravada: 00:00:10*\n",
        encoding="utf-8",
    )
    session.mark_chunk_recorded(0, session.chunks_dir / "chunk_00000.wav", 0.0, 10.0)
    session.mark_recording()
    session.mark_chunk_transcribed(0, 10.0)
    session.mark_completed()
    return session.meeting_dir


def test_parse_markdown_segments_extracts_start_and_text():
    text = "**[00:01:05]** Ola mundo.\n\n**[00:02:10]** Segunda fala.\n\n"
    segments = parse_markdown_segments(text)
    assert len(segments) == 2
    assert segments[0]["start_seconds"] == 65.0
    assert segments[0]["text"] == "Ola mundo."
    assert segments[0]["end_seconds"] == 130.0  # aproximado pelo inicio do proximo
    assert segments[1]["end_seconds"] == 130.0  # ultimo -- igual ao proprio inicio (sem "proximo" pra usar)


def test_parse_markdown_segments_ignores_header_and_footer():
    text = "# Titulo\n\n- **Modelo:** small\n\n**[00:00:00]** Real.\n\n---\n\n*Duracao total: 00:00:05*\n"
    segments = parse_markdown_segments(text)
    assert len(segments) == 1
    assert segments[0]["text"] == "Real."


def test_parse_markdown_segments_empty_text_returns_empty_list():
    assert parse_markdown_segments("") == []


def test_import_meeting_creates_meeting_and_segments(tmp_path: Path, repo: MeetingRepository):
    meeting_dir = _make_meeting_dir(tmp_path, "reuniao-1", system_audio_enabled=True, microphone_enabled=False)
    result = import_meeting(repo, meeting_dir)

    assert result.ok is True
    assert result.segments_imported == 2

    meeting = repo.get_meeting("reuniao-1")
    assert meeting["title"] == "Reuniao de Teste"
    assert meeting["status"] == "completed"

    segments = repo.list_segments("reuniao-1")
    assert [s["text"] for s in segments] == ["Primeiro segmento.", "Segundo segmento."]


def test_import_meeting_labels_speaker_by_microphone_channel(tmp_path: Path, repo: MeetingRepository):
    meeting_dir = _make_meeting_dir(
        tmp_path, "reuniao-mic", system_audio_enabled=False, microphone_enabled=True
    )
    import_meeting(repo, meeting_dir)
    segments = repo.list_segments("reuniao-mic")
    assert all(s["speaker_label"] == SPEAKER_LABEL_MICROPHONE for s in segments)


def test_import_meeting_labels_speaker_by_system_channel(tmp_path: Path, repo: MeetingRepository):
    meeting_dir = _make_meeting_dir(
        tmp_path, "reuniao-sys", system_audio_enabled=True, microphone_enabled=False
    )
    import_meeting(repo, meeting_dir)
    segments = repo.list_segments("reuniao-sys")
    assert all(s["speaker_label"] == SPEAKER_LABEL_SYSTEM for s in segments)


def test_import_meeting_labels_mixed_when_both_sources_enabled(tmp_path: Path, repo: MeetingRepository):
    meeting_dir = _make_meeting_dir(
        tmp_path, "reuniao-dual", system_audio_enabled=True, microphone_enabled=True
    )
    import_meeting(repo, meeting_dir)
    segments = repo.list_segments("reuniao-dual")
    assert all(s["speaker_label"] == SPEAKER_LABEL_MIXED for s in segments)


def test_import_meeting_never_invents_a_person_name(tmp_path: Path, repo: MeetingRepository):
    """Missao, secao H.5: nunca rotular como um nome de pessoa sem
    evidencia real -- so os rotulos de canal conhecidos."""
    meeting_dir = _make_meeting_dir(tmp_path, "reuniao-x", system_audio_enabled=True, microphone_enabled=True)
    import_meeting(repo, meeting_dir)
    segments = repo.list_segments("reuniao-x")
    allowed = {SPEAKER_LABEL_MICROPHONE, SPEAKER_LABEL_SYSTEM, SPEAKER_LABEL_MIXED, None}
    assert all(s["speaker_label"] in allowed for s in segments)


def test_import_meeting_is_idempotent(tmp_path: Path, repo: MeetingRepository):
    meeting_dir = _make_meeting_dir(tmp_path, "reuniao-2")
    import_meeting(repo, meeting_dir)
    import_meeting(repo, meeting_dir)
    assert repo.count_meetings() == 1
    assert len(repo.list_segments("reuniao-2")) == 2


def test_import_meeting_missing_state_json_reports_failure_without_raising(tmp_path: Path, repo: MeetingRepository):
    empty_dir = tmp_path / "pasta-vazia"
    empty_dir.mkdir()
    result = import_meeting(repo, empty_dir)
    assert result.ok is False
    assert "state.json" in result.message


def test_import_meeting_missing_transcript_file_still_imports_metadata(tmp_path: Path, repo: MeetingRepository):
    meeting_dir = _make_meeting_dir(tmp_path, "reuniao-3")
    # apaga o .md depois de criar a sessao -- simula um arquivo removido manualmente
    transcript_path = tmp_path / "reuniao-3.md"
    transcript_path.unlink()
    result = import_meeting(repo, meeting_dir)
    assert result.ok is True
    assert result.segments_imported == 0
    assert repo.get_meeting("reuniao-3") is not None


def test_import_all_continues_after_one_meeting_fails(tmp_path: Path, repo: MeetingRepository):
    root = tmp_path / "roots" / "raiz1"
    good_dir = _make_meeting_dir(tmp_path, "boa")
    broken_dir = root / "quebrada"
    broken_dir.mkdir(parents=True)
    (broken_dir / "state.json").write_text("{ nao e json valido", encoding="utf-8")

    results = import_all(repo, [root])

    by_id = {r.meeting_id: r for r in results}
    assert by_id["boa"].ok is True
    assert by_id["quebrada"].ok is False
    assert repo.get_meeting("boa") is not None
    assert repo.get_meeting("quebrada") is None


def test_import_all_skips_folders_without_state_json(tmp_path: Path, repo: MeetingRepository):
    root = tmp_path / "roots" / "raiz1"
    _make_meeting_dir(tmp_path, "valida")
    (root / "nao-e-reuniao").mkdir(parents=True)

    results = import_all(repo, [root])
    assert [r.meeting_id for r in results] == ["valida"]


def test_import_all_handles_nonexistent_root_gracefully(tmp_path: Path, repo: MeetingRepository):
    assert import_all(repo, [tmp_path / "nao-existe"]) == []


def test_import_all_is_idempotent_across_multiple_runs(tmp_path: Path, repo: MeetingRepository):
    root = tmp_path / "roots" / "raiz1"
    _make_meeting_dir(tmp_path, "reuniao-4")
    import_all(repo, [root])
    import_all(repo, [root])
    assert repo.count_meetings() == 1

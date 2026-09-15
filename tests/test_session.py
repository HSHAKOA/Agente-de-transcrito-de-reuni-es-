import os
import sys
from pathlib import Path

import pytest

from meeting_transcriber.session import (
    CHUNK_FAILED,
    CHUNK_TRANSCRIBED,
    STATUS_COMPLETED,
    STATUS_CREATED,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    STATUS_PROCESSING,
    STATUS_RECORDING,
    MeetingSession,
    find_meeting_dir_across_roots,
    is_pid_running,
    is_valid_meeting_id,
    list_sessions,
    mark_interrupted_sessions,
    new_meeting_id,
    sanitize_title_for_folder,
)


def test_new_meeting_id_is_unique_and_valid(tmp_path: Path):
    ids = {new_meeting_id() for _ in range(20)}
    assert len(ids) == 20
    assert all(is_valid_meeting_id(i) for i in ids)


def test_is_valid_meeting_id_rejects_path_traversal():
    assert not is_valid_meeting_id("../../etc")
    assert not is_valid_meeting_id("..\\..\\windows")
    assert not is_valid_meeting_id("a/b")
    assert not is_valid_meeting_id("")
    assert not is_valid_meeting_id(None)


# -- nome de pasta legivel a partir do titulo --------------------------

@pytest.mark.parametrize(
    "title,expected",
    [
        ("Reuniao Projeto ERP", "Reuniao-Projeto-ERP"),
        ("  espacos   nas   pontas  ", "espacos-nas-pontas"),
        ('Titulo com < > : " / \\ | ? *', "Titulo-com"),
    ],
)
def test_sanitize_title_for_folder_basic_cases(title, expected):
    assert sanitize_title_for_folder(title) == expected


@pytest.mark.parametrize("reserved", ["CON", "con", "NUL", "COM1", "lpt1"])
def test_sanitize_title_for_folder_avoids_windows_reserved_names(reserved):
    assert sanitize_title_for_folder(reserved) == "Reuniao"


def test_sanitize_title_for_folder_never_empty():
    assert sanitize_title_for_folder("") == "Reuniao"
    assert sanitize_title_for_folder("...") == "Reuniao"
    assert sanitize_title_for_folder("///") == "Reuniao"
    assert sanitize_title_for_folder(None) == "Reuniao"  # tipo inesperado tambem nao quebra


def test_sanitize_title_for_folder_truncates_long_titles():
    result = sanitize_title_for_folder("x" * 200, max_length=50)
    assert len(result) <= 50


def test_sanitize_title_for_folder_strips_trailing_dot_and_space():
    # Windows rejeita nomes de pasta terminados em ponto ou espaco
    assert not sanitize_title_for_folder("Titulo.").endswith(".")
    assert not sanitize_title_for_folder("Titulo ").endswith(" ")


def test_new_meeting_id_without_title_keeps_old_compact_format():
    meeting_id = new_meeting_id()
    assert is_valid_meeting_id(meeting_id)
    assert "_" not in meeting_id  # formato antigo: so digitos e hifens


def test_new_meeting_id_with_title_is_human_readable_and_valid():
    meeting_id = new_meeting_id(title="Reuniao com Cliente X")
    assert is_valid_meeting_id(meeting_id)
    assert "Reuniao-com-Cliente-X" in meeting_id


def test_new_meeting_id_with_title_never_exceeds_regex_length_limit():
    meeting_id = new_meeting_id(title="x" * 300)
    assert is_valid_meeting_id(meeting_id)  # regex ja garante <= 80, so confirma que nao estoura


def test_new_meeting_id_with_same_title_is_still_unique():
    ids = {new_meeting_id(title="Reuniao Recorrente") for _ in range(20)}
    assert len(ids) == 20


def test_create_writes_metadata_and_state(tmp_path: Path):
    session = MeetingSession.create(
        base_dir=tmp_path,
        title="Reuniao de teste",
        model="small",
        language="pt",
        device="cpu",
        transcript_path=tmp_path / "out.md",
        meeting_id="20260101-000000-abcdef",
    )
    assert session.meeting_dir.exists()
    assert session.chunks_dir.exists()
    assert session.metadata_path.exists()
    assert session.state_path.exists()
    assert session.state["status"] == STATUS_CREATED
    assert session.metadata["title"] == "Reuniao de teste"
    assert session.metadata["root_directory"] == str(tmp_path.resolve())
    assert session.metadata["meeting_directory"] == str(session.meeting_dir.resolve())
    assert session.metadata["system_audio_device"] is None
    assert session.metadata["microphone_device"] is None


def test_full_lifecycle_marks_completed(tmp_path: Path):
    session = MeetingSession.create(
        base_dir=tmp_path, title="T", model="small", language="pt", device="cpu"
    )
    session.mark_recording()
    assert session.state["status"] == STATUS_RECORDING
    assert session.state["started_at"] is not None

    chunk_path = session.chunks_dir / "chunk_00000.wav"
    chunk_path.write_bytes(b"x")
    session.mark_chunk_recorded(0, chunk_path, start_offset_seconds=0.0, duration_seconds=30.0)
    assert session.state["chunk_count"] == 1
    assert session.state["chunks_recorded"] == 1
    assert session.state["chunks"][0]["path"] == "chunks/chunk_00000.wav"

    session.mark_chunk_transcribed(0, end_offset_seconds=30.0)
    assert session.state["status"] == STATUS_PROCESSING
    assert session.state["chunks_transcribed"] == 1
    assert session.state["duration"] == 30.0
    assert session.state["chunks"][0]["status"] == CHUNK_TRANSCRIBED

    session.mark_completed()
    assert session.state["status"] == STATUS_COMPLETED
    assert session.state["finished_at"] is not None


def test_completed_downgrades_to_interrupted_when_chunk_failed(tmp_path: Path):
    session = MeetingSession.create(
        base_dir=tmp_path, title="T", model="small", language="pt", device="cpu"
    )
    chunk_path = session.chunks_dir / "chunk_00000.wav"
    chunk_path.write_bytes(b"x")
    session.mark_chunk_recorded(0, chunk_path, 0.0, 30.0)
    session.mark_chunk_failed(0, "boom")

    assert session.state["chunks"][0]["status"] == CHUNK_FAILED
    assert session.state["chunks"][0]["retry_count"] == 1

    session.mark_completed()
    assert session.state["status"] == STATUS_INTERRUPTED


def test_completed_downgrades_to_interrupted_when_chunk_never_attempted(tmp_path: Path):
    """Um chunk gravado mas nunca sequer tentado (ex.: --resume interrompido
    antes de chegar nele) tambem precisa impedir "completed" -- nao so um
    chunk que falhou explicitamente."""
    session = MeetingSession.create(
        base_dir=tmp_path, title="T", model="small", language="pt", device="cpu"
    )
    chunk_path = session.chunks_dir / "chunk_00000.wav"
    chunk_path.write_bytes(b"x")
    session.mark_chunk_recorded(0, chunk_path, 0.0, 30.0)  # nunca marcado transcrito nem falho

    session.mark_completed()
    assert session.state["status"] == STATUS_INTERRUPTED


def test_mark_failed_sets_error_and_status(tmp_path: Path):
    session = MeetingSession.create(
        base_dir=tmp_path, title="T", model="small", language="pt", device="cpu"
    )
    session.mark_failed("modelo nao carregou")
    assert session.state["status"] == STATUS_FAILED
    assert session.state["error"] == "modelo nao carregou"


def test_pending_chunks_excludes_transcribed(tmp_path: Path):
    session = MeetingSession.create(
        base_dir=tmp_path, title="T", model="small", language="pt", device="cpu"
    )
    for i in range(3):
        p = session.chunks_dir / f"chunk_{i:05d}.wav"
        p.write_bytes(b"x")
        session.mark_chunk_recorded(i, p, float(i * 30), 30.0)
    session.mark_chunk_transcribed(0, 30.0)
    session.mark_chunk_failed(1, "erro")

    pending = session.pending_chunks()
    pending_indexes = {c.index for c in pending}
    assert pending_indexes == {1, 2}


def test_load_round_trips_state(tmp_path: Path):
    created = MeetingSession.create(
        base_dir=tmp_path, title="T", model="small", language="pt", device="cpu"
    )
    created.mark_recording()

    loaded = MeetingSession.load(created.meeting_dir)
    assert loaded.state["status"] == STATUS_RECORDING
    assert loaded.metadata["model"] == "small"


def test_state_json_is_never_left_corrupted_after_write(tmp_path: Path):
    """A escrita atomica usa um arquivo temporario + os.replace: mesmo lendo
    o arquivo logo apos escrever, ele deve sempre estar valido (nunca
    parcialmente escrito)."""
    session = MeetingSession.create(
        base_dir=tmp_path, title="T", model="small", language="pt", device="cpu"
    )
    for i in range(5):
        session.mark_chunk_recorded(i, session.chunks_dir / f"c{i}.wav", float(i), 1.0)
        # nenhum arquivo .tmp-* deve sobrar no diretorio
        leftovers = list(session.meeting_dir.glob("*.tmp-*"))
        assert leftovers == []


def test_mark_interrupted_sessions_detects_stuck_recording(tmp_path: Path):
    live = MeetingSession.create(base_dir=tmp_path, title="Ao vivo", model="small", language="pt", device="cpu")
    live.mark_recording()  # simula processo que morreu no meio da gravacao

    done = MeetingSession.create(base_dir=tmp_path, title="Completa", model="small", language="pt", device="cpu")
    done.mark_recording()
    done.mark_completed()

    recovered = mark_interrupted_sessions(tmp_path)
    recovered_ids = {r["meeting_id"] for r in recovered}
    assert recovered_ids == {live.state["meeting_id"]}

    reloaded_live = MeetingSession.load(live.meeting_dir)
    assert reloaded_live.state["status"] == STATUS_INTERRUPTED
    reloaded_done = MeetingSession.load(done.meeting_dir)
    assert reloaded_done.state["status"] == STATUS_COMPLETED  # nao mexe no que ja estava terminado


def test_mark_interrupted_sessions_is_idempotent(tmp_path: Path):
    live = MeetingSession.create(base_dir=tmp_path, title="Ao vivo", model="small", language="pt", device="cpu")
    live.mark_recording()

    first = mark_interrupted_sessions(tmp_path)
    second = mark_interrupted_sessions(tmp_path)
    assert len(first) == 1
    assert len(second) == 0  # ja estava "interrupted", nao e mais "ao vivo"


def test_mark_interrupted_sessions_ignores_missing_dir(tmp_path: Path):
    assert mark_interrupted_sessions(tmp_path / "nao-existe") == []


def test_mark_interrupted_sessions_tolerates_corrupted_state_json(tmp_path: Path):
    bad_dir = tmp_path / "corrompida"
    bad_dir.mkdir()
    (bad_dir / "state.json").write_text("{ nao e json valido", encoding="utf-8")

    # nao deve levantar excecao nem derrubar o scan das demais sessoes
    assert mark_interrupted_sessions(tmp_path) == []


def test_list_sessions_orders_most_recent_first(tmp_path: Path):
    first = MeetingSession.create(
        base_dir=tmp_path, title="Primeira", model="small", language="pt", device="cpu",
        meeting_id="20260101-000000-aaaaaa",
    )
    second = MeetingSession.create(
        base_dir=tmp_path, title="Segunda", model="small", language="pt", device="cpu",
        meeting_id="20260102-000000-bbbbbb",
    )
    sessions = list_sessions(tmp_path)
    assert [s["meeting_id"] for s in sessions] == [second.state["meeting_id"], first.state["meeting_id"]]


# -- pid tracking (recovery, B.1) ---------------------------------------

def test_mark_recording_stores_current_pid(tmp_path: Path):
    session = MeetingSession.create(base_dir=tmp_path, title="T", model="small", language="pt", device="cpu")
    session.mark_recording()
    assert session.state["pid"] == os.getpid()


# -- find_meeting_dir_across_roots (recovery multi-root, B.1) -----------

def test_find_meeting_dir_across_roots_finds_in_second_root(tmp_path: Path):
    root_a = tmp_path / "A"
    root_b = tmp_path / "B"
    session = MeetingSession.create(
        base_dir=root_b, title="T", model="small", language="pt", device="cpu",
        meeting_id="20260101-000000-aaaaaa",
    )
    found = find_meeting_dir_across_roots("20260101-000000-aaaaaa", [root_a, root_b])
    assert found == session.meeting_dir


def test_find_meeting_dir_across_roots_returns_none_when_not_found(tmp_path: Path):
    root_a = tmp_path / "A"
    root_a.mkdir()
    assert find_meeting_dir_across_roots("nao-existe-em-lugar-nenhum", [root_a]) is None


def test_find_meeting_dir_across_roots_skips_missing_root_without_raising(tmp_path: Path):
    missing_root = tmp_path / "nao-existe"
    real_root = tmp_path / "real"
    session = MeetingSession.create(
        base_dir=real_root, title="T", model="small", language="pt", device="cpu",
        meeting_id="20260101-000000-bbbbbb",
    )
    found = find_meeting_dir_across_roots("20260101-000000-bbbbbb", [missing_root, real_root])
    assert found == session.meeting_dir


# -- is_pid_running (recovery safety net, B.1) ---------------------------

@pytest.mark.skipif(sys.platform != "win32", reason="is_pid_running so tem implementacao real no Windows")
def test_is_pid_running_true_for_current_process():
    assert is_pid_running(os.getpid()) is True


@pytest.mark.skipif(sys.platform != "win32", reason="is_pid_running so tem implementacao real no Windows")
def test_is_pid_running_false_for_almost_certainly_unused_pid():
    # PID acima do limite pratico do Windows -- extremamente improvavel de existir
    assert is_pid_running(999_999) is False


def test_is_pid_running_none_for_missing_pid():
    assert is_pid_running(None) is None


def test_is_pid_running_none_on_unsupported_platform(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert is_pid_running(os.getpid()) is None

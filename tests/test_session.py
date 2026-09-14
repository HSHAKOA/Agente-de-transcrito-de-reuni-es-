from pathlib import Path

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
    is_valid_meeting_id,
    list_sessions,
    mark_interrupted_sessions,
    new_meeting_id,
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

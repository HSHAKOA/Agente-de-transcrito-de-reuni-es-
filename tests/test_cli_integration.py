"""Testes de integracao do loop principal (cli.run) de ponta a ponta, com
gravacao e Whisper substituidos por dublês -- sem hardware de audio, sem
baixar/rodar nenhum modelo de verdade. O objetivo e provar que
recorder -> fila -> transcriber -> markdown -> session realmente se
encaixam, nao so cada peca isolada.
"""

from __future__ import annotations

import argparse
import os
import queue
import threading
from pathlib import Path

import pytest

from meeting_transcriber import cli
from meeting_transcriber.recorder import RecordedChunk
from meeting_transcriber.session import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    MeetingSession,
)
from meeting_transcriber.transcriber import Segment


def _make_args(tmp_path: Path, **overrides) -> argparse.Namespace:
    defaults = dict(
        output=tmp_path / "saida.md",
        title="Reuniao de teste",
        model="small",
        device="cpu",
        language="pt",
        chunk_seconds=60,
        no_keep_audio=False,
        work_dir=None,
        meeting_dir=None,
        resume=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


def _fake_recording_worker_factory(num_chunks: int, chunk_seconds: float = 30.0):
    """Substitui recorder.recording_worker: escreve `num_chunks` .wav vazios
    reais em disco (pra existir de verdade) e os enfileira, ignorando
    stop_event -- o teste quer controlar exatamente o que e "gravado"."""

    def _worker(session_dir: Path, chunk_seconds_arg, stop_event, out_queue, on_chunk_recorded=None, **kwargs):
        session_dir.mkdir(parents=True, exist_ok=True)
        for i in range(num_chunks):
            path = session_dir / f"chunk_{i:05d}.wav"
            path.write_bytes(b"RIFF....WAVEfake")  # so precisa existir; Transcriber e fake tambem
            chunk = RecordedChunk(
                path=path, index=i, start_offset_seconds=i * chunk_seconds, duration_seconds=chunk_seconds
            )
            out_queue.put(chunk)
            if on_chunk_recorded is not None:
                on_chunk_recorded(chunk)
        out_queue.put(None)

    return _worker


class _FakeTranscriber:
    """Substitui transcriber.Transcriber: devolve um segmento fixo por
    chunk, sem carregar nenhum modelo Whisper de verdade."""

    fail_on_load = False
    fail_on_indexes: set = frozenset()

    def __init__(self, model_size, device, language):
        if self.fail_on_load:
            raise RuntimeError("CUDA indisponivel (simulado)")
        self.model_size = model_size

    def transcribe_file(self, path: Path, offset_seconds: float = 0.0):
        index = int(path.stem.split("_")[1])
        if index in self.fail_on_indexes:
            raise RuntimeError(f"falha simulada no bloco {index}")
        return [Segment(start=offset_seconds, end=offset_seconds + 1.0, text=f"texto do bloco {index}")]


@pytest.fixture(autouse=True)
def _reset_fake_transcriber():
    _FakeTranscriber.fail_on_load = False
    _FakeTranscriber.fail_on_indexes = frozenset()
    yield


def test_full_run_with_meeting_dir_marks_completed_and_writes_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "recording_worker", _fake_recording_worker_factory(3))
    monkeypatch.setattr(cli, "Transcriber", _FakeTranscriber)
    monkeypatch.setattr(cli.signal, "signal", lambda *a, **k: None)  # sem sinal de verdade num teste

    meeting_dir = tmp_path / "data" / "meetings" / "reuniao-1"
    args = _make_args(tmp_path, meeting_dir=meeting_dir)

    exit_code = cli.run(args)

    assert exit_code == 0
    content = args.output.read_text(encoding="utf-8")
    assert "texto do bloco 0" in content
    assert "texto do bloco 1" in content
    assert "texto do bloco 2" in content
    assert "Duracao total gravada" in content

    session = MeetingSession.load(meeting_dir)
    assert session.state["status"] == STATUS_COMPLETED
    assert session.state["chunks_transcribed"] == 3
    assert session.state["chunks_recorded"] == 3


def test_run_marks_session_failed_when_model_fails_to_load(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "recording_worker", _fake_recording_worker_factory(1))
    _FakeTranscriber.fail_on_load = True
    monkeypatch.setattr(cli, "Transcriber", _FakeTranscriber)
    monkeypatch.setattr(cli.signal, "signal", lambda *a, **k: None)

    meeting_dir = tmp_path / "data" / "meetings" / "reuniao-2"
    args = _make_args(tmp_path, meeting_dir=meeting_dir)

    exit_code = cli.run(args)

    assert exit_code == 1
    session = MeetingSession.load(meeting_dir)
    assert session.state["status"] == STATUS_FAILED
    assert "CUDA" in session.state["error"]
    # o markdown precisa ter sido finalizado mesmo com a falha (cabecalho +
    # rodape), nao deixado pela metade -- P1-3 da auditoria.
    content = args.output.read_text(encoding="utf-8")
    assert "Duracao total gravada" in content


def test_run_continues_session_after_one_chunk_fails_to_transcribe(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "recording_worker", _fake_recording_worker_factory(3))
    _FakeTranscriber.fail_on_indexes = {1}
    monkeypatch.setattr(cli, "Transcriber", _FakeTranscriber)
    monkeypatch.setattr(cli.signal, "signal", lambda *a, **k: None)

    meeting_dir = tmp_path / "data" / "meetings" / "reuniao-3"
    args = _make_args(tmp_path, meeting_dir=meeting_dir)

    exit_code = cli.run(args)

    assert exit_code == 0  # um bloco com falha nao derruba a sessao inteira
    content = args.output.read_text(encoding="utf-8")
    assert "texto do bloco 0" in content
    assert "texto do bloco 2" in content
    assert "Falha ao transcrever" in content

    session = MeetingSession.load(meeting_dir)
    assert session.state["chunks_transcribed"] == 2
    assert session.state["status"] == "interrupted"  # rebaixado por causa do bloco 1 com falha


def test_resume_reprocesses_only_pending_chunks_and_appends(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "Transcriber", _FakeTranscriber)

    output_path = tmp_path / "saida.md"
    meeting_dir = tmp_path / "data" / "meetings" / "reuniao-4"
    session = MeetingSession.create(
        base_dir=meeting_dir.parent,
        title="Reuniao interrompida",
        model="small",
        language="pt",
        device="cpu",
        transcript_path=output_path,
        meeting_id=meeting_dir.name,
    )

    # bloco 0 ja foi transcrito antes (simula sessao que rodou parcialmente);
    # bloco 1 foi gravado mas nunca chegou a ser transcrito (processo morreu).
    chunk0 = session.chunks_dir / "chunk_00000.wav"
    chunk0.write_bytes(b"fake")
    session.mark_chunk_recorded(0, chunk0, 0.0, 30.0)
    session.mark_chunk_transcribed(0, 30.0)

    chunk1 = session.chunks_dir / "chunk_00001.wav"
    chunk1.write_bytes(b"fake")
    session.mark_chunk_recorded(1, chunk1, 30.0, 30.0)

    output_path.write_text(
        "# Reuniao interrompida\n\n## Transcricao\n\n**[00:00:00]** texto do bloco 0\n\n", encoding="utf-8"
    )

    exit_code = cli.run_resume(meeting_dir)

    assert exit_code == 0
    content = output_path.read_text(encoding="utf-8")
    assert content.count("texto do bloco 0") == 1  # nao duplicou o que ja existia
    assert "texto do bloco 1" in content  # o pendente foi reprocessado e anexado

    reloaded = MeetingSession.load(meeting_dir)
    assert reloaded.state["status"] == STATUS_COMPLETED
    assert reloaded.pending_chunks() == []


def test_resume_stops_between_chunks_when_signaled(tmp_path, monkeypatch):
    """Um sinal de parada gracioso durante --resume nao deve derrubar o
    processo no meio de uma transcricao (KeyboardInterrupt cru) nem marcar a
    sessao como "completed" com blocos que nunca foram tentados."""
    stop_event_holder: dict = {}
    real_make_handler = cli._make_shutdown_handler

    def _spy_make_handler(stop_event, force_exit=os._exit):
        stop_event_holder["event"] = stop_event
        return real_make_handler(stop_event, force_exit)

    monkeypatch.setattr(cli, "_make_shutdown_handler", _spy_make_handler)
    monkeypatch.setattr(cli.signal, "signal", lambda *a, **k: None)

    class _StoppingTranscriber(_FakeTranscriber):
        def transcribe_file(self, path, offset_seconds=0.0):
            result = super().transcribe_file(path, offset_seconds)
            stop_event_holder["event"].set()  # simula Ctrl+C chegando logo apos o 1o bloco
            return result

    monkeypatch.setattr(cli, "Transcriber", _StoppingTranscriber)

    output_path = tmp_path / "saida.md"
    meeting_dir = tmp_path / "data" / "meetings" / "reuniao-6"
    session = MeetingSession.create(
        base_dir=meeting_dir.parent,
        title="Reuniao longa",
        model="small",
        language="pt",
        device="cpu",
        transcript_path=output_path,
        meeting_id=meeting_dir.name,
    )
    for i in range(3):
        chunk = session.chunks_dir / f"chunk_{i:05d}.wav"
        chunk.write_bytes(b"fake")
        session.mark_chunk_recorded(i, chunk, float(i * 30), 30.0)
    output_path.write_text("# Reuniao longa\n\n## Transcricao\n\n", encoding="utf-8")

    exit_code = cli.run_resume(meeting_dir)

    assert exit_code == 0
    reloaded = MeetingSession.load(meeting_dir)
    assert reloaded.state["status"] == STATUS_INTERRUPTED  # blocos 1 e 2 nunca foram tentados
    transcribed = {c["index"] for c in reloaded.state["chunks"] if c["status"] == "transcribed"}
    assert transcribed == {0}


def test_graceful_stop_event_flushes_partial_buffer_through_full_pipeline(tmp_path, monkeypatch):
    """Sobe o loop de gravacao DE VERDADE (recording_worker real, so com
    microfone falso) para confirmar que sinalizar stop_event no meio de um
    bloco ainda resulta num .md com o texto do bloco parcial -- o cenario
    central da auditoria (P0-1): o botao Parar nao pode descartar audio."""
    import numpy as np

    from meeting_transcriber.recorder import recording_worker as real_recording_worker

    monkeypatch.setattr(cli, "Transcriber", _FakeTranscriber)
    monkeypatch.setattr(cli.signal, "signal", lambda *a, **k: None)

    sample_rate = 16_000
    block = np.full(int(0.5 * sample_rate), 0.05, dtype=np.float32)

    class _FakeStream:
        def __init__(self, blocks, stop_event):
            self._blocks = blocks
            self._stop_event = stop_event
            self._i = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def record(self, numframes):
            if self._i >= len(self._blocks):
                self._stop_event.set()
                return np.zeros(numframes, dtype=np.float32)
            b = self._blocks[self._i]
            self._i += 1
            if self._i >= len(self._blocks):
                self._stop_event.set()  # simula o "Ctrl+C"/parada graciosa chegando aqui
            return b

    class _FakeMic:
        def recorder(self, samplerate, channels):
            return _FakeStream([block, block, block], stop_event_holder["event"])

    stop_event_holder = {}

    def _patched_worker(session_dir, chunk_seconds, stop_event, out_queue, on_chunk_recorded=None, **kwargs):
        stop_event_holder["event"] = stop_event
        return real_recording_worker(
            session_dir,
            chunk_seconds,
            stop_event,
            out_queue,
            samplerate=sample_rate,
            mic_factory=_FakeMic,
            on_chunk_recorded=on_chunk_recorded,
        )

    monkeypatch.setattr(cli, "recording_worker", _patched_worker)

    # chunk_seconds bem maior que os 1.5s que vamos "gravar": nunca fecha um
    # bloco completo sozinho, so o parcial ao parar.
    meeting_dir = tmp_path / "data" / "meetings" / "reuniao-5"
    args = _make_args(tmp_path, meeting_dir=meeting_dir, chunk_seconds=60)

    exit_code = cli.run(args)

    assert exit_code == 0
    content = args.output.read_text(encoding="utf-8")
    assert "texto do bloco 0" in content  # o UNICO bloco (parcial, 1.5s) foi transcrito e salvo

    session = MeetingSession.load(meeting_dir)
    assert session.state["status"] == STATUS_COMPLETED
    assert session.state["chunks_recorded"] == 1

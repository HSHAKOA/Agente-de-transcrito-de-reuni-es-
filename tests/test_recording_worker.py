"""Testes do loop de gravacao (recording_worker) usando um microfone falso —
nenhum destes testes precisa de placa de som/dispositivo de audio real.

Cobrem especificamente o comportamento de shutdown gracioso: quando
stop_event e sinalizado no meio de um bloco, o buffer parcial acumulado ate
ali PRECISA ser gravado e enfileirado (senao os ultimos segundos da reuniao
seriam descartados silenciosamente) e o sentinela `None` sempre precisa
chegar no final, mesmo se algo der errado no meio.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import List

import numpy as np
import pytest
import soundfile as sf

from meeting_transcriber.recorder import RecordedChunk, recording_worker

SAMPLE_RATE = 16_000
BLOCK_FRAMES = int(0.5 * SAMPLE_RATE)  # recording_worker le em blocos de 0.5s (BLOCK_SECONDS)


class _FakeRecorderStream:
    """Contexto usado como `mic.recorder(...)`: cada chamada de `.record()`
    devolve o proximo bloco de 0.5s de uma lista pre-definida, e para
    (sinalizando fim de audio disponivel) sinalizando `stop_event` quando a
    lista se esgota — assim o teste controla exatamente quantos blocos de
    0.5s "chegam" antes do Ctrl+C/parada graciosa.
    """

    def __init__(self, blocks: List[np.ndarray], stop_event: threading.Event, stop_after: int | None = None):
        self._blocks = blocks
        self._stop_event = stop_event
        self._stop_after = stop_after if stop_after is not None else len(blocks)
        self._calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def record(self, numframes: int) -> np.ndarray:
        if self._calls >= self._stop_after:
            self._stop_event.set()
            # ainda precisa devolver algo (o loop so checa stop_event no topo
            # do while); um bloco de silencio e inofensivo aqui.
            return np.zeros(numframes, dtype=np.float32)
        block = self._blocks[self._calls]
        self._calls += 1
        if self._calls >= len(self._blocks):
            self._stop_event.set()
        return block


class _FakeMic:
    def __init__(self, blocks: List[np.ndarray], stop_event: threading.Event, stop_after: int | None = None):
        self._blocks = blocks
        self._stop_event = stop_event
        self._stop_after = stop_after

    def recorder(self, samplerate: int, channels: int):
        return _FakeRecorderStream(self._blocks, self._stop_event, self._stop_after)


def _make_block(seconds: float = 0.5) -> np.ndarray:
    return np.full(int(seconds * SAMPLE_RATE), 0.1, dtype=np.float32)


def _drain(q: "queue.Queue") -> List:
    items = []
    while True:
        item = q.get_nowait()
        items.append(item)
        if item is None:
            break
    return items


def test_partial_buffer_is_flushed_when_stopped_mid_chunk(tmp_path: Path):
    """3 blocos de 0.5s = 1.5s gravados, mas chunk_seconds=10 (nunca fecha
    um bloco completo sozinho) -- ao parar, o bloco PARCIAL de 1.5s precisa
    ainda assim virar um chunk WAV e ser enfileirado, nao descartado."""
    stop_event = threading.Event()
    blocks = [_make_block() for _ in range(3)]
    mic = _FakeMic(blocks, stop_event)
    out_queue: "queue.Queue" = queue.Queue()

    recording_worker(
        tmp_path,
        chunk_seconds=10,
        stop_event=stop_event,
        out_queue=out_queue,
        samplerate=SAMPLE_RATE,
        mic_factory=lambda: mic,
    )

    items = _drain(out_queue)
    assert items[-1] is None  # sentinela de fim sempre por ultimo
    chunks = [i for i in items if i is not None]
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert abs(chunks[0].duration_seconds - 1.5) < 1e-6
    assert chunks[0].path.exists()


def test_full_chunks_and_final_partial_chunk_both_emitted(tmp_path: Path):
    """chunk_seconds=1 fecha um chunk completo a cada 2 blocos de 0.5s;
    com 5 blocos totais, esperamos 2 chunks completos (index 0 e 1) + 1
    chunk parcial final (index 2, 0.5s) -- nada pode ficar pra tras."""
    stop_event = threading.Event()
    blocks = [_make_block() for _ in range(5)]
    mic = _FakeMic(blocks, stop_event)
    out_queue: "queue.Queue" = queue.Queue()

    recording_worker(
        tmp_path,
        chunk_seconds=1,
        stop_event=stop_event,
        out_queue=out_queue,
        samplerate=SAMPLE_RATE,
        mic_factory=lambda: mic,
    )

    chunks = [i for i in _drain(out_queue) if i is not None]
    assert [c.index for c in chunks] == [0, 1, 2]
    assert abs(chunks[0].duration_seconds - 1.0) < 1e-6
    assert abs(chunks[1].duration_seconds - 1.0) < 1e-6
    assert abs(chunks[2].duration_seconds - 0.5) < 1e-6
    # offsets cumulativos corretos (usados pros timestamps no markdown)
    assert chunks[0].start_offset_seconds == 0.0
    assert chunks[1].start_offset_seconds == 1.0
    assert chunks[2].start_offset_seconds == 2.0


def test_sentinel_none_is_always_last_even_with_no_audio(tmp_path: Path):
    stop_event = threading.Event()
    stop_event.set()  # ja para antes de ler qualquer bloco
    mic = _FakeMic([], stop_event)
    out_queue: "queue.Queue" = queue.Queue()

    recording_worker(
        tmp_path,
        chunk_seconds=10,
        stop_event=stop_event,
        out_queue=out_queue,
        samplerate=SAMPLE_RATE,
        mic_factory=lambda: mic,
    )

    items = _drain(out_queue)
    assert items == [None]


def test_on_chunk_recorded_callback_invoked_per_chunk(tmp_path: Path):
    stop_event = threading.Event()
    blocks = [_make_block() for _ in range(4)]  # 2s -> 2 chunks completos com chunk_seconds=1
    mic = _FakeMic(blocks, stop_event)
    out_queue: "queue.Queue" = queue.Queue()
    seen: List[RecordedChunk] = []

    recording_worker(
        tmp_path,
        chunk_seconds=1,
        stop_event=stop_event,
        out_queue=out_queue,
        samplerate=SAMPLE_RATE,
        mic_factory=lambda: mic,
        on_chunk_recorded=seen.append,
    )

    assert [c.index for c in seen] == [0, 1]
    queued = [i for i in _drain(out_queue) if i is not None]
    assert seen == queued


def test_on_chunk_recorded_exception_does_not_break_recording(tmp_path: Path):
    """Uma falha ao notificar progresso (ex.: escrever state.json) nao pode
    derrubar a gravacao em andamento -- o audio ja foi gravado em disco e
    colocado na fila, o que importa e nao perde-lo."""
    stop_event = threading.Event()
    blocks = [_make_block(), _make_block()]
    mic = _FakeMic(blocks, stop_event)
    out_queue: "queue.Queue" = queue.Queue()

    def _boom(chunk):
        raise RuntimeError("disco cheio, por exemplo")

    recording_worker(
        tmp_path,
        chunk_seconds=1,
        stop_event=stop_event,
        out_queue=out_queue,
        samplerate=SAMPLE_RATE,
        mic_factory=lambda: mic,
        on_chunk_recorded=_boom,
    )

    chunks = [i for i in _drain(out_queue) if i is not None]
    assert len(chunks) == 1  # o chunk de audio foi gravado e enfileirado normalmente
    assert chunks[0].path.exists()


def test_device_open_failure_still_emits_sentinel_instead_of_hanging(tmp_path: Path):
    """Se o dispositivo de audio nao abrir (ex.: nenhum loopback disponivel),
    o sentinel `None` ainda precisa chegar na fila -- senao o consumidor
    (cli.py) fica bloqueado pra sempre em `chunk_queue.get()`, e nem o
    shutdown gracioso consegue desbloquear isso."""
    stop_event = threading.Event()
    out_queue: "queue.Queue" = queue.Queue()

    def _broken_mic_factory():
        raise RuntimeError("dispositivo de audio indisponivel (simulado)")

    # a excecao ainda propaga (quem chama -- normalmente uma thread daemon
    # -- fica sabendo que algo deu errado via log/traceback padrao); o que
    # importa aqui e que o `finally` roda ANTES dela subir, entao o
    # sentinel chega na fila mesmo assim.
    with pytest.raises(RuntimeError):
        recording_worker(
            tmp_path,
            chunk_seconds=10,
            stop_event=stop_event,
            out_queue=out_queue,
            samplerate=SAMPLE_RATE,
            mic_factory=_broken_mic_factory,
        )

    assert out_queue.get_nowait() is None


def test_written_wav_matches_expected_audio_duration(tmp_path: Path):
    stop_event = threading.Event()
    blocks = [_make_block(1.0)]  # BLOCK_SECONDS logico e 0.5s, mas o mock pode devolver o tamanho que quiser
    mic = _FakeMic(blocks, stop_event)
    out_queue: "queue.Queue" = queue.Queue()

    recording_worker(
        tmp_path,
        chunk_seconds=10,
        stop_event=stop_event,
        out_queue=out_queue,
        samplerate=SAMPLE_RATE,
        mic_factory=lambda: mic,
    )

    chunks = [i for i in _drain(out_queue) if i is not None]
    data, samplerate = sf.read(str(chunks[0].path))
    assert samplerate == SAMPLE_RATE
    assert abs(len(data) / samplerate - 1.0) < 1e-6

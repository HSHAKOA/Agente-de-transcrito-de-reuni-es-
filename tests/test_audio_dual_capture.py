"""Testes de captura simultanea (sistema + microfone) usando microfones
falsos -- nenhum destes precisa de hardware de audio real. Cobrem
especificamente: as duas fontes gravando ao mesmo tempo (nao uma depois da
outra), o pareamento/mixagem de chunks, o flush do buffer parcial de AMBAS
as fontes no stop gracioso, e uma fonte terminando antes da outra sem
travar o encerramento.
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import List

import numpy as np
import soundfile as sf

from meeting_transcriber.audio.dual_capture import _mix_loop, dual_recording_worker
from meeting_transcriber.recorder import RecordedChunk

SAMPLE_RATE = 16_000
BLOCK_FRAMES = int(0.5 * SAMPLE_RATE)


class _FakeRecorderStream:
    """Devolve os blocos designados em ordem e so entao sinaliza que
    terminou -- via um `threading.Barrier` compartilhado entre as duas
    fontes, nao setando `stop_event` sozinha.

    Isso importa: se cada fonte falsa decidisse setar o `stop_event`
    (compartilhado pelas duas threads de captura) assim que SUA PROPRIA
    lista de blocos acabasse, a fonte mais rapida forcaria a outra a parar
    antes de ler os blocos que ainda tinha pra ler -- uma corrida real
    entre threads, nao um bug em dual_capture.py. O barrier garante que as
    duas so "terminam" juntas, depois que AMBAS ja leram tudo que tinham
    pra ler; so entao o `stop_event` e sinalizado (via `action=` do
    barrier), preservando a concorrencia de verdade entre as leituras
    (nada aqui serializa a ORDEM das leituras, so o momento final de
    parar).
    """

    def __init__(self, blocks, barrier: threading.Barrier, on_read=None):
        self._blocks = blocks
        self._barrier = barrier
        self._i = 0
        self._on_read = on_read
        self._reached_barrier = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def record(self, numframes: int) -> np.ndarray:
        if self._on_read is not None:
            self._on_read()
        if self._i >= len(self._blocks):
            return np.zeros(numframes, dtype=np.float32)
        block = self._blocks[self._i]
        self._i += 1
        if self._i >= len(self._blocks) and not self._reached_barrier:
            self._reached_barrier = True
            self._barrier.wait()  # so libera (as duas ao mesmo tempo) quando a outra fonte tambem chegar aqui
        return block


class _FakeMic:
    def __init__(self, blocks, barrier: threading.Barrier, on_read=None):
        self._blocks = blocks
        self._barrier = barrier
        self._on_read = on_read

    def recorder(self, samplerate: int, channels: int):
        return _FakeRecorderStream(self._blocks, self._barrier, on_read=self._on_read)


def _make_block(value: float, seconds: float = 0.5) -> np.ndarray:
    return np.full(int(seconds * SAMPLE_RATE), value, dtype=np.float32)


def _drain(q: "queue.Queue"):
    items = []
    while True:
        item = q.get_nowait()
        items.append(item)
        if item is None:
            break
    return items


def _make_barrier(stop_event: threading.Event) -> threading.Barrier:
    """As duas fontes falsas so terminam de verdade quando AMBAS chegam
    aqui -- so entao `stop_event` e sinalizado (via `action=`)."""
    return threading.Barrier(2, action=stop_event.set)


# -- dual_recording_worker: caminho feliz --------------------------------

def test_dual_capture_produces_mixed_chunks_from_both_sources(tmp_path: Path):
    stop_event = threading.Event()
    barrier = _make_barrier(stop_event)
    system_mic = _FakeMic([_make_block(0.2) for _ in range(4)], barrier)  # 2s
    mic_mic = _FakeMic([_make_block(0.1) for _ in range(4)], barrier)
    out_queue: "queue.Queue" = queue.Queue()

    dual_recording_worker(
        tmp_path,
        chunk_seconds=1,  # fecha um chunk a cada 2 blocos de 0.5s
        stop_event=stop_event,
        out_queue=out_queue,
        system_mic_factory=lambda: system_mic,
        microphone_mic_factory=lambda: mic_mic,
        samplerate=SAMPLE_RATE,
    )

    chunks = [c for c in _drain(out_queue) if c is not None]
    assert len(chunks) == 2  # 2s de audio / 1s por chunk
    for chunk in chunks:
        assert chunk.path.exists()
        data, sr = sf.read(str(chunk.path))
        assert sr == SAMPLE_RATE
        assert np.allclose(data, 0.3, atol=0.02)  # 0.2 (sistema) + 0.1 (mic)

    # os dois brutos tambem ficam gravados, em subpastas separadas
    assert (tmp_path / "system" / "chunk_00000.wav").exists()
    assert (tmp_path / "microphone" / "chunk_00000.wav").exists()
    assert (tmp_path / "mixed" / "chunk_00000.wav").exists()


def test_dual_capture_sources_run_concurrently_not_sequentially(tmp_path: Path):
    """As duas fontes precisam ler blocos entrelacadas no tempo, nao uma
    fonte inteira terminar pra so entao a outra comecar."""
    stop_event = threading.Event()
    read_order: List[str] = []
    read_lock = threading.Lock()

    def _mark(name):
        def _on_read():
            with read_lock:
                read_order.append(name)
            time.sleep(0.01)  # da chance da outra thread intercalar

        return _on_read

    barrier = _make_barrier(stop_event)
    system_mic = _FakeMic([_make_block(0.1) for _ in range(6)], barrier, on_read=_mark("system"))
    mic_mic = _FakeMic([_make_block(0.1) for _ in range(6)], barrier, on_read=_mark("microphone"))
    out_queue: "queue.Queue" = queue.Queue()

    dual_recording_worker(
        tmp_path, chunk_seconds=10, stop_event=stop_event, out_queue=out_queue,
        system_mic_factory=lambda: system_mic, microphone_mic_factory=lambda: mic_mic,
        samplerate=SAMPLE_RATE,
    )

    # se fosse sequencial, todas as leituras de "system" viriam antes de
    # qualquer leitura de "microphone" (ou vice-versa). Concorrente =
    # aparecem intercaladas em algum ponto da sequencia.
    first_half = read_order[: len(read_order) // 2]
    assert "system" in first_half and "microphone" in first_half


def test_dual_capture_flushes_partial_buffer_of_both_sources_on_stop(tmp_path: Path):
    stop_event = threading.Event()
    # 3 blocos de 0.5s = 1.5s, chunk_seconds=10 -> nunca fecha um chunk
    # completo sozinho, so o parcial ao parar.
    barrier = _make_barrier(stop_event)
    system_mic = _FakeMic([_make_block(0.3) for _ in range(3)], barrier)
    mic_mic = _FakeMic([_make_block(0.1) for _ in range(3)], barrier)
    out_queue: "queue.Queue" = queue.Queue()

    dual_recording_worker(
        tmp_path, chunk_seconds=10, stop_event=stop_event, out_queue=out_queue,
        system_mic_factory=lambda: system_mic, microphone_mic_factory=lambda: mic_mic,
        samplerate=SAMPLE_RATE,
    )

    chunks = [c for c in _drain(out_queue) if c is not None]
    assert len(chunks) == 1
    assert abs(chunks[0].duration_seconds - 1.5) < 1e-2


def test_dual_capture_calls_on_chunk_recorded_for_each_source(tmp_path: Path):
    stop_event = threading.Event()
    barrier = _make_barrier(stop_event)
    system_mic = _FakeMic([_make_block(0.1) for _ in range(2)], barrier)
    mic_mic = _FakeMic([_make_block(0.1) for _ in range(2)], barrier)
    out_queue: "queue.Queue" = queue.Queue()
    seen = []

    dual_recording_worker(
        tmp_path, chunk_seconds=1, stop_event=stop_event, out_queue=out_queue,
        system_mic_factory=lambda: system_mic, microphone_mic_factory=lambda: mic_mic,
        samplerate=SAMPLE_RATE,
        on_chunk_recorded=lambda source, chunk: seen.append((source, chunk.index)),
    )

    sources_seen = {s for s, _ in seen}
    assert sources_seen == {"system", "microphone"}


def test_dual_capture_calls_on_level_for_each_source(tmp_path: Path):
    stop_event = threading.Event()
    barrier = _make_barrier(stop_event)
    system_mic = _FakeMic([_make_block(0.1) for _ in range(2)], barrier)
    mic_mic = _FakeMic([_make_block(0.1) for _ in range(2)], barrier)
    out_queue: "queue.Queue" = queue.Queue()
    levels = []
    lock = threading.Lock()

    def _on_level(source, level):
        with lock:
            levels.append((source, level))

    dual_recording_worker(
        tmp_path, chunk_seconds=10, stop_event=stop_event, out_queue=out_queue,
        system_mic_factory=lambda: system_mic, microphone_mic_factory=lambda: mic_mic,
        samplerate=SAMPLE_RATE, on_level=_on_level,
    )

    sources_seen = {s for s, _ in levels}
    assert sources_seen == {"system", "microphone"}
    assert all(level > 0 for _, level in levels)  # blocos nao sao silencio


def test_dual_capture_no_threads_left_running_after_return(tmp_path: Path):
    stop_event = threading.Event()
    barrier = _make_barrier(stop_event)
    system_mic = _FakeMic([_make_block(0.1) for _ in range(2)], barrier)
    mic_mic = _FakeMic([_make_block(0.1) for _ in range(2)], barrier)
    out_queue: "queue.Queue" = queue.Queue()

    before = {t.name for t in threading.enumerate()}

    dual_recording_worker(
        tmp_path, chunk_seconds=1, stop_event=stop_event, out_queue=out_queue,
        system_mic_factory=lambda: system_mic, microphone_mic_factory=lambda: mic_mic,
        samplerate=SAMPLE_RATE,
    )

    after = {t.name for t in threading.enumerate()}
    assert "audio-capture-system" not in after
    assert "audio-capture-microphone" not in after
    assert after - before == set()  # nada novo sobrou rodando


# -- _mix_loop: pareamento direto (sem threads) ---------------------------

def test_mix_loop_pairs_matching_indexes(tmp_path: Path):
    from meeting_transcriber.recorder import write_chunk

    system_dir = tmp_path / "system"
    mic_dir = tmp_path / "microphone"
    mixed_dir = tmp_path / "mixed"
    system_dir.mkdir()
    mic_dir.mkdir()

    system_chunk = write_chunk([_make_block(0.2, 1.0)], system_dir, 0, 0.0, SAMPLE_RATE)
    mic_chunk = write_chunk([_make_block(0.1, 1.0)], mic_dir, 0, 0.0, SAMPLE_RATE)

    system_queue: "queue.Queue" = queue.Queue()
    mic_queue: "queue.Queue" = queue.Queue()
    system_queue.put(system_chunk)
    system_queue.put(None)
    mic_queue.put(mic_chunk)
    mic_queue.put(None)

    out_queue: "queue.Queue" = queue.Queue()
    _mix_loop(system_queue, mic_queue, mixed_dir, SAMPLE_RATE, out_queue)

    items = _drain(out_queue)
    assert len(items) == 2  # 1 mixado + sentinel None
    assert items[1] is None
    data, _sr = sf.read(str(items[0].path))
    assert np.allclose(data, 0.3, atol=0.01)


def test_mix_loop_handles_one_source_finishing_before_the_other(tmp_path: Path):
    """Sistema tem so 1 chunk, microfone tem 3 -- o mixer nao pode travar
    esperando um 2o/3o chunk do sistema que nunca vai chegar."""
    from meeting_transcriber.recorder import write_chunk

    system_dir = tmp_path / "system"
    mic_dir = tmp_path / "microphone"
    mixed_dir = tmp_path / "mixed"
    system_dir.mkdir()
    mic_dir.mkdir()

    system_queue: "queue.Queue" = queue.Queue()
    mic_queue: "queue.Queue" = queue.Queue()

    system_queue.put(write_chunk([_make_block(0.2, 1.0)], system_dir, 0, 0.0, SAMPLE_RATE))
    system_queue.put(None)  # sistema termina cedo

    for i in range(3):
        mic_queue.put(write_chunk([_make_block(0.1, 1.0)], mic_dir, i, float(i), SAMPLE_RATE))
    mic_queue.put(None)

    out_queue: "queue.Queue" = queue.Queue()
    _mix_loop(system_queue, mic_queue, mixed_dir, SAMPLE_RATE, out_queue)

    items = [i for i in _drain(out_queue) if i is not None]
    assert len(items) == 3  # todos os 3 chunks do microfone foram processados

    # os chunks 1 e 2 (depois do sistema acabar) sao so o microfone (sistema = silencio)
    data_last, _ = sf.read(str(items[2].path))
    assert np.allclose(data_last, 0.1, atol=0.01)


def test_mix_loop_empty_queues_just_emits_sentinel(tmp_path: Path):
    system_queue: "queue.Queue" = queue.Queue()
    mic_queue: "queue.Queue" = queue.Queue()
    system_queue.put(None)
    mic_queue.put(None)

    out_queue: "queue.Queue" = queue.Queue()
    _mix_loop(system_queue, mic_queue, tmp_path / "mixed", SAMPLE_RATE, out_queue)

    assert _drain(out_queue) == [None]

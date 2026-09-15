"""Testes do pipeline de transcricao ao vivo com um `transcribe_window`
FALSO (nunca precisa de um modelo Whisper de verdade carregado)."""

from __future__ import annotations

import threading
import time

import numpy as np
import pytest

from meeting_transcriber.live.pipeline import LiveTranscriptionPipeline
from meeting_transcriber.live.segments import STATE_PROVISIONAL
from meeting_transcriber.live.transcript import LiveTranscript

SAMPLERATE = 1000


def _block(seconds: float) -> np.ndarray:
    return np.zeros(int(seconds * SAMPLERATE), dtype=np.float32)


class _ScriptedTranscriber:
    """Devolve um texto fixo por chamada (na ordem), ou lanca excecao se o
    proximo item do script for uma Exception."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def __call__(self, samples: np.ndarray, samplerate: int) -> str:
        self.calls.append((len(samples), samplerate))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _wait_until(predicate, timeout=3.0, interval=0.01):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_full_window_produces_provisional_segment():
    transcript = LiveTranscript()
    fake = _ScriptedTranscriber(["ola mundo"])
    pipeline = LiveTranscriptionPipeline(transcript, fake, SAMPLERATE, window_seconds=2, overlap_seconds=0)
    pipeline.start()
    try:
        pipeline.on_block("mixed", _block(2))
        assert _wait_until(lambda: len(transcript.snapshot()["segments"]) == 1)
        seg = transcript.snapshot()["segments"][0]
        assert seg["text"] == "ola mundo"
        assert seg["state"] == STATE_PROVISIONAL
        assert seg["source"] == "mixed"
    finally:
        pipeline.stop()


def test_overlap_deduplicated_between_adjacent_windows():
    transcript = LiveTranscript()
    fake = _ScriptedTranscriber(["precisamos finalizar esse modulo", "esse modulo ate sexta-feira"])
    pipeline = LiveTranscriptionPipeline(transcript, fake, SAMPLERATE, window_seconds=2, overlap_seconds=1)
    pipeline.start()
    try:
        pipeline.on_block("mixed", _block(2))  # janela 1: [0,2)
        assert _wait_until(lambda: len(transcript.snapshot()["segments"]) == 1)
        pipeline.on_block("mixed", _block(1))  # completa janela 2 (hop=1s): [1,3)
        assert _wait_until(lambda: len(transcript.snapshot()["segments"]) == 2)

        texts = [s["text"] for s in transcript.snapshot()["segments"]]
        assert texts == ["precisamos finalizar esse modulo", "ate sexta-feira"]
    finally:
        pipeline.stop()


def test_empty_transcription_result_produces_no_segment():
    transcript = LiveTranscript()
    fake = _ScriptedTranscriber([""])
    pipeline = LiveTranscriptionPipeline(transcript, fake, SAMPLERATE, window_seconds=1, overlap_seconds=0)
    pipeline.start()
    try:
        pipeline.on_block("mixed", _block(1))
        time.sleep(0.2)
        assert transcript.snapshot()["segments"] == []
    finally:
        pipeline.stop()


def test_failure_is_retried_and_eventually_succeeds():
    transcript = LiveTranscript()
    fake = _ScriptedTranscriber([RuntimeError("falha simulada"), "recuperou"])
    pipeline = LiveTranscriptionPipeline(
        transcript, fake, SAMPLERATE, window_seconds=1, overlap_seconds=0, max_retries=2
    )
    pipeline.start()
    try:
        pipeline.on_block("mixed", _block(1))
        assert _wait_until(lambda: len(transcript.snapshot()["segments"]) == 1)
        assert transcript.snapshot()["segments"][0]["text"] == "recuperou"
    finally:
        pipeline.stop()


def test_failure_exhausting_retries_never_crashes_and_never_blocks_recording():
    transcript = LiveTranscript()
    fake = _ScriptedTranscriber([RuntimeError("1"), RuntimeError("2"), RuntimeError("3")])
    pipeline = LiveTranscriptionPipeline(
        transcript, fake, SAMPLERATE, window_seconds=1, overlap_seconds=0, max_retries=2
    )
    pipeline.start()
    try:
        pipeline.on_block("mixed", _block(1))
        assert _wait_until(lambda: len(fake.calls) == 3)  # 1 tentativa + 2 retries, depois desiste
        time.sleep(0.1)
        assert transcript.snapshot()["segments"] == []  # nunca produziu segmento, mas tambem nunca travou
        # a proxima janela continua sendo processada normalmente depois da desistencia
        pipeline.on_block("mixed", _block(1))
    finally:
        pipeline.stop()


def test_recording_thread_never_blocks_on_slow_transcription():
    """on_block precisa retornar quase instantaneamente mesmo se o
    transcribe_window estiver lento -- a captura de audio nao pode
    esperar o Whisper (missao, secao D.5: 'recorder nunca depende da
    velocidade do Whisper')."""
    transcript = LiveTranscript()
    started = threading.Event()

    def _slow_transcribe(samples, samplerate):
        started.set()
        time.sleep(1.0)
        return "demorou"

    pipeline = LiveTranscriptionPipeline(transcript, _slow_transcribe, SAMPLERATE, window_seconds=1, overlap_seconds=0)
    pipeline.start()
    try:
        t0 = time.time()
        pipeline.on_block("mixed", _block(1))
        elapsed = time.time() - t0
        assert elapsed < 0.5  # on_block nao esperou o transcribe_window de 1s
    finally:
        pipeline.stop()


def test_flush_emits_final_partial_window():
    transcript = LiveTranscript()
    fake = _ScriptedTranscriber(["parcial final"])
    pipeline = LiveTranscriptionPipeline(transcript, fake, SAMPLERATE, window_seconds=8, overlap_seconds=0)
    pipeline.start()
    try:
        pipeline.on_block("mixed", _block(3))  # nunca fecha uma janela cheia de 8s sozinho
        pipeline.flush("mixed")
        assert _wait_until(lambda: len(transcript.snapshot()["segments"]) == 1)
        assert transcript.snapshot()["segments"][0]["text"] == "parcial final"
    finally:
        pipeline.stop()


def test_stop_drains_and_joins_cleanly():
    transcript = LiveTranscript()
    fake = _ScriptedTranscriber(["um", "dois"])
    pipeline = LiveTranscriptionPipeline(transcript, fake, SAMPLERATE, window_seconds=1, overlap_seconds=0)
    pipeline.start()
    pipeline.on_block("mixed", _block(1))
    pipeline.on_block("mixed", _block(1))
    pipeline.stop(timeout=5.0)
    assert not pipeline._thread.is_alive()


def test_backpressure_drops_oldest_when_queue_full_instead_of_growing_unbounded():
    transcript = LiveTranscript()
    release = threading.Event()

    def _blocking_transcribe(samples, samplerate):
        release.wait(timeout=5.0)
        return "processado"

    pipeline = LiveTranscriptionPipeline(
        transcript, _blocking_transcribe, SAMPLERATE, window_seconds=1, overlap_seconds=0, max_queue_size=2
    )
    pipeline.start()
    try:
        # a 1a janela e puxada pro worker (fica "em processo", bloqueada em
        # release.wait). As proximas se acumulam na fila (capacidade 2) --
        # window 5 deveria expulsar a mais antiga (window 2) da fila.
        for _ in range(5):
            pipeline.on_block("mixed", _block(1))
        assert pipeline._queue.qsize() <= 2
    finally:
        release.set()
        pipeline.stop()

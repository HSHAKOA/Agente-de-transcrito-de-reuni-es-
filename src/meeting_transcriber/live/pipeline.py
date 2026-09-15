"""Fila de transcricao ao vivo (Fase D, secao D.5/D.11): uma thread
dedicada consome janelas curtas de audio e produz segmentos PROVISORIOS,
totalmente independente da captura (que so enfileira, nunca espera) e da
transcricao DURAVEL por chunk (que continua rodando exatamente como
antes, em cli.py). Uma janela que falha nunca para a gravacao nem e
descartada silenciosamente -- tenta de novo (`max_retries`) e so entao
desiste com o erro registrado no log.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass, replace
from typing import Callable, Dict, Optional

import numpy as np

from .dedup import merge_overlapping_text
from .segments import STATE_PROVISIONAL, LiveSegment
from .transcript import LiveTranscript
from .window import DEFAULT_OVERLAP_SECONDS, DEFAULT_WINDOW_SECONDS, WindowAccumulator

logger = logging.getLogger("meeting_transcriber.live")

DEFAULT_MAX_RETRIES = 2


@dataclass
class _WindowJob:
    source: str
    start_seconds: float
    end_seconds: float
    samples: np.ndarray
    captured_at: float
    attempt: int = 0


class LiveTranscriptionPipeline:
    """`transcribe_window(samples, samplerate) -> str` e injetado -- em
    producao e um `WhisperModel` real (ver `whisper_adapter.py`); em teste,
    uma funcao fake que devolve texto canned, sem precisar de modelo
    nenhum carregado."""

    def __init__(
        self,
        transcript: LiveTranscript,
        transcribe_window: Callable[[np.ndarray, int], str],
        samplerate: int,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        max_queue_size: int = 200,
    ):
        self._transcript = transcript
        self._transcribe_window = transcribe_window
        self._samplerate = samplerate
        self._window_seconds = window_seconds
        self._overlap_seconds = overlap_seconds
        self._max_retries = max_retries
        self._accumulators: Dict[str, WindowAccumulator] = {}
        # backpressure: se a fila encher (Whisper muito mais lento que o
        # audio chegando), descarta a janela mais ANTIGA -- perder alguns
        # segundos de preview e melhor que crescer memoria sem limite ou
        # travar a captura (o audio real continua intacto nos chunks
        # duraveis; isto aqui e so uma previa, nao a fonte de verdade).
        self._queue: "queue.Queue[Optional[_WindowJob]]" = queue.Queue(maxsize=max_queue_size)
        self._last_raw_text: Dict[str, str] = {}
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="live-transcription")
        self._thread.start()

    def on_block(self, source: str, block: np.ndarray) -> None:
        """Chamado da THREAD DE CAPTURA (mesmo callback `on_block` que ja
        alimenta o medidor de nivel) -- so acumula e enfileira, nunca
        transcreve aqui: gravar nunca pode esperar o Whisper."""
        accumulator = self._accumulators.setdefault(source, WindowAccumulator(self._samplerate, self._window_seconds, self._overlap_seconds))
        for start_seconds, end_seconds, samples in accumulator.push(block):
            self._enqueue(_WindowJob(source, start_seconds, end_seconds, samples, captured_at=time.time()))

    def flush(self, source: str) -> None:
        """Emite a ultima janela parcial (mais curta) de `source`, se
        houver -- chamado ao parar a gravacao, pra nao perder os ultimos
        segundos que nunca fecharam uma janela completa."""
        accumulator = self._accumulators.get(source)
        if accumulator is None:
            return
        final = accumulator.flush_final()
        if final is not None:
            start_seconds, end_seconds, samples = final
            self._enqueue(_WindowJob(source, start_seconds, end_seconds, samples, captured_at=time.time()))

    def _enqueue(self, job: _WindowJob) -> None:
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            try:
                self._queue.get_nowait()  # descarta a mais antiga -- ver docstring da classe
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                pass

    def stop(self, timeout: float = 10.0) -> None:
        self._stop_event.set()
        self._queue.put(None)  # sentinela -- desbloqueia o get() mesmo com a fila cheia de trabalho pendente
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                break
            self._process(job)

    def _process(self, job: _WindowJob) -> None:
        try:
            text = self._transcribe_window(job.samples, self._samplerate)
        except Exception:
            logger.exception(
                "Falha ao transcrever janela ao vivo [%.1f-%.1fs] de '%s' (tentativa %d)",
                job.start_seconds, job.end_seconds, job.source, job.attempt + 1,
            )
            if job.attempt < self._max_retries:
                self._enqueue(replace(job, attempt=job.attempt + 1))
            else:
                logger.error(
                    "Desistindo da janela ao vivo [%.1f-%.1fs] de '%s' apos %d tentativas -- "
                    "o audio continua intacto no chunk duravel, so a PREVIA ao vivo desse trecho fica ausente.",
                    job.start_seconds, job.end_seconds, job.source, job.attempt + 1,
                )
            return

        text = (text or "").strip()
        previous_raw = self._last_raw_text.get(job.source, "")
        self._last_raw_text[job.source] = text
        if not text:
            return

        deduped = merge_overlapping_text(previous_raw, text)
        if not deduped:
            return

        segment = LiveSegment(job.start_seconds, job.end_seconds, deduped, STATE_PROVISIONAL, job.source)
        self._transcript.add_provisional(segment)
        self._transcript.record_latency(time.time() - job.captured_at)

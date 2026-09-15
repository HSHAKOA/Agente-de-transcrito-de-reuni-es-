"""Acumula blocos brutos de audio (o mesmo callback `on_block` que ja
alimenta o medidor de nivel -- ver `recorder.recording_worker`) em
janelas curtas de baixa latencia (Fase D, secao D.1: 5-15s, default 8s),
com uma pequena sobreposicao entre janelas adjacentes pra nao cortar uma
palavra bem na fronteira (dedup dessa sobreposicao fica em `dedup.py`).

Conta AMOSTRAS, nunca relogio de parede, pro mesmo motivo ja documentado
em `audio/dual_capture.py`: os timestamps precisam ser exatos e estaveis,
independente de jitter de agendamento entre chamadas do callback.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

DEFAULT_WINDOW_SECONDS = 8.0
DEFAULT_OVERLAP_SECONDS = 1.5


class WindowAccumulator:
    def __init__(
        self,
        samplerate: int,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        overlap_seconds: float = DEFAULT_OVERLAP_SECONDS,
    ):
        if overlap_seconds >= window_seconds:
            raise ValueError("overlap_seconds precisa ser menor que window_seconds")
        if window_seconds <= 0 or overlap_seconds < 0:
            raise ValueError("window_seconds/overlap_seconds precisam ser positivos")
        self._samplerate = samplerate
        self._window_samples = int(window_seconds * samplerate)
        self._hop_samples = max(1, int((window_seconds - overlap_seconds) * samplerate))
        self._buffer = np.zeros(0, dtype=np.float32)
        self._buffer_start_sample = 0  # indice absoluto (desde o 1o bloco) do buffer[0]
        self._next_window_start_sample = 0
        self._total_samples_seen = 0

    def push(self, block: np.ndarray) -> List[Tuple[float, float, np.ndarray]]:
        """Adiciona um bloco novo de audio; devolve 0+ janelas completas
        que ficaram prontas com esse bloco (normalmente 0 ou 1, mas um
        bloco maior que o hop pode completar mais de uma de uma vez)."""
        block = np.asarray(block, dtype=np.float32).reshape(-1)
        if block.size:
            self._buffer = np.concatenate([self._buffer, block])
            self._total_samples_seen += len(block)

        windows: List[Tuple[float, float, np.ndarray]] = []
        while True:
            local_start = self._next_window_start_sample - self._buffer_start_sample
            local_end = local_start + self._window_samples
            if local_end > len(self._buffer):
                break
            samples = self._buffer[local_start:local_end].copy()
            start_seconds = self._next_window_start_sample / self._samplerate
            end_seconds = (self._next_window_start_sample + self._window_samples) / self._samplerate
            windows.append((start_seconds, end_seconds, samples))
            self._next_window_start_sample += self._hop_samples

        # descarta da frente do buffer o que nenhuma janela futura precisa mais
        trim_local = self._next_window_start_sample - self._buffer_start_sample
        if trim_local > 0:
            self._buffer = self._buffer[trim_local:]
            self._buffer_start_sample = self._next_window_start_sample
        return windows

    def flush_final(self) -> Optional[Tuple[float, float, np.ndarray]]:
        """Ao parar a gravacao, o ultimo pedaco de audio pode ser curto
        demais pra fechar uma janela cheia -- devolve ele mesmo assim
        (mais curto que o normal), ou None se nao sobrou audio novo."""
        local_start = self._next_window_start_sample - self._buffer_start_sample
        if local_start >= len(self._buffer):
            return None
        samples = self._buffer[local_start:].copy()
        if samples.size == 0:
            return None
        start_seconds = self._next_window_start_sample / self._samplerate
        end_seconds = self._total_samples_seen / self._samplerate
        self._next_window_start_sample = self._total_samples_seen
        return start_seconds, end_seconds, samples

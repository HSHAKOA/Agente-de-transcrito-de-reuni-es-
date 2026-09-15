"""Estado agregado da transcricao ao vivo de UMA reuniao: a lista de
segmentos (provisorios + definitivos) que a UI deveria mostrar agora, e o
calculo de backlog (Fase D, secao D.6). Thread-safe -- e escrito pela
thread de transcricao ao vivo E pela thread principal de cli.py (quando
um chunk duravel termina de transcrever "de verdade"), e lido por quem
serializa o snapshot pra `live_transcript.json`/SSE.
"""

from __future__ import annotations

import threading
from typing import List, Optional

from .segments import STATE_COMMITTED, STATE_PROVISIONAL, LiveSegment

# classificacao do backlog (Fase D, secao D.6) -- limites em segundos de
# audio pendente de transcrever. Nao e "ciencia exata", so um sinal
# grosseiro pra UI decidir a cor do indicador.
BEHIND_THRESHOLD_SECONDS = 30.0


class LiveTranscript:
    def __init__(self):
        self._lock = threading.Lock()
        self._segments: List[LiveSegment] = []
        self._recorded_seconds = 0.0
        self._transcribed_seconds = 0.0  # so o que ja virou COMMITTED (fonte de verdade do .md final)
        self._latencies_seconds: List[float] = []
        self._model_load_seconds: Optional[float] = None

    def add_provisional(self, segment: LiveSegment) -> None:
        assert segment.state == STATE_PROVISIONAL
        with self._lock:
            # substitui qualquer provisorio ANTERIOR que cobria essa mesma
            # janela (uma janela pode ser reprocessada em retry) -- nunca
            # acumula duplicata da mesma janela.
            self._segments = [
                s for s in self._segments
                if not (s.state == STATE_PROVISIONAL and s.start_seconds == segment.start_seconds)
            ]
            self._segments.append(segment)
            self._segments.sort(key=lambda s: s.start_seconds)

    def commit_range(self, start_seconds: float, end_seconds: float, committed: List[LiveSegment]) -> None:
        """Chamado quando o chunk DURAVEL [start_seconds, end_seconds)
        termina de transcrever de verdade (a mesma transcricao que ja
        alimenta o .md, inalterada) -- substitui qualquer segmento
        PROVISORIO dentro dessa janela pelos segmentos definitivos.
        Segmentos ja `committed` de uma faixa diferente nunca sao
        tocados."""
        for s in committed:
            assert s.state == STATE_COMMITTED
        with self._lock:
            self._segments = [
                s for s in self._segments
                if s.state == STATE_COMMITTED or not (start_seconds <= s.start_seconds < end_seconds)
            ]
            self._segments.extend(committed)
            self._segments.sort(key=lambda s: s.start_seconds)
            self._transcribed_seconds = max(self._transcribed_seconds, end_seconds)

    def set_recorded_seconds(self, seconds: float) -> None:
        with self._lock:
            self._recorded_seconds = max(self._recorded_seconds, seconds)

    def set_model_load_seconds(self, seconds: float) -> None:
        with self._lock:
            self._model_load_seconds = seconds

    def record_latency(self, seconds: float) -> None:
        with self._lock:
            self._latencies_seconds.append(seconds)
            self._latencies_seconds = self._latencies_seconds[-50:]  # so as mais recentes, nunca cresce sem limite

    def backlog(self) -> dict:
        with self._lock:
            recorded = self._recorded_seconds
            transcribed = self._transcribed_seconds
        pending = max(0.0, recorded - transcribed)
        if pending <= 1.0:
            status = "LIVE"
        elif pending <= BEHIND_THRESHOLD_SECONDS:
            status = "PROCESSING"
        else:
            status = "BEHIND"
        return {
            "recorded_seconds": round(recorded, 1),
            "transcribed_seconds": round(transcribed, 1),
            "pending_seconds": round(pending, 1),
            "status": status,
        }

    def snapshot(self) -> dict:
        with self._lock:
            segments = list(self._segments)
            avg_latency = (
                sum(self._latencies_seconds) / len(self._latencies_seconds) if self._latencies_seconds else None
            )
            model_load_seconds = self._model_load_seconds
        return {
            "segments": [s.to_dict() for s in segments],
            "backlog": self.backlog(),
            "avg_latency_seconds": round(avg_latency, 2) if avg_latency is not None else None,
            "model_load_seconds": round(model_load_seconds, 2) if model_load_seconds is not None else None,
        }

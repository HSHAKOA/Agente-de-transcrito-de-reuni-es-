"""Medicao de nivel de audio: calculo puro (sem I/O, sem threading) mais um
holder thread-safe do "ultimo nivel conhecido" de cada fonte -- e o que
`GET /api/audio/levels`/o stream SSE consultam, sem nunca precisar enviar
buffers de audio pro frontend so pra desenhar uma barra.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Optional

import numpy as np

# RMS de referencia considerado "nivel cheio" (1.0) na barra de UI. Fala
# proxima e clara sem estourar fica em torno disso; nao e um valor
# cientifico, so um ponto de partida razoavel pra a barra nao parecer
# sempre vazia nem sempre no talo.
DEFAULT_REFERENCE_RMS = 0.2

# Abaixo disso, a fonte e considerada "sem sinal" (silencio/desligado) pra
# fins de UI (o ponto verde de "ativo") -- nao afeta o valor numerico do
# nivel, so o campo booleano `active`.
ACTIVE_THRESHOLD = 0.02


def compute_rms(samples: "np.ndarray") -> float:
    """RMS (root mean square) de um bloco de amostras float32 em [-1, 1].
    Bloco vazio -> 0.0 (nunca NaN/excecao)."""
    if samples.size == 0:
        return 0.0
    # float64 no calculo intermediario: evita overflow/perda de precisao
    # somando muitos quadrados de amostras float32.
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


def normalize_level(rms: float, reference: float = DEFAULT_REFERENCE_RMS) -> float:
    """RMS bruto -> nivel normalizado em [0, 1] pra UI. Satura em 1.0 acima
    da referencia (nao interessa "quanto" estourou, so que estourou)."""
    if rms <= 0 or reference <= 0:
        return 0.0
    return float(min(1.0, rms / reference))


class LevelMeter:
    """Guarda o nivel mais recente de cada fonte nomeada (ex.: "system",
    "microphone"), thread-safe. Varias threads de captura podem chamar
    `update` concorrentemente; qualquer numero de leitores pode chamar
    `snapshot` sem se inscrever em nada.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._levels: Dict[str, dict] = {}

    def update(self, source: str, level: float) -> None:
        with self._lock:
            self._levels[source] = {
                "level": level,
                "active": level >= ACTIVE_THRESHOLD,
                "updated_at": time.time(),
            }

    def snapshot(self) -> dict:
        with self._lock:
            return {name: dict(data) for name, data in self._levels.items()}

    def get(self, source: str) -> Optional[dict]:
        with self._lock:
            data = self._levels.get(source)
            return dict(data) if data is not None else None

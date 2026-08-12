"""Transcricao de blocos de audio usando faster-whisper.

faster-whisper (CTranslate2) roda 100% local/offline, sem custo por minuto,
o que e essencial para transcrever horas de gravacao. `vad_filter=True`
usa deteccao de atividade de voz (Silero VAD) para pular trechos de
silencio, o que acelera bastante o processamento de audio de reuniao (que
costuma ter pausas).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)


@dataclass
class Segment:
    start: float
    end: float
    text: str


class Transcriber:
    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        language: Optional[str] = "pt",
    ):
        compute_type = "int8" if device == "cpu" else "float16"
        logger.info("Carregando modelo Whisper '%s' (device=%s, compute_type=%s)...", model_size, device, compute_type)
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self.language = language

    def transcribe_file(self, path: Path, offset_seconds: float = 0.0) -> List[Segment]:
        """Transcreve um arquivo WAV e retorna os segmentos com os
        timestamps ja deslocados por `offset_seconds` (posicao do bloco
        dentro da gravacao completa), para que o markdown final mostre o
        tempo correto dentro da reuniao inteira, nao apenas dentro do bloco.
        """
        segments, _info = self.model.transcribe(
            str(path),
            language=self.language,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            # Cada bloco e transcrito isoladamente (sem contexto do bloco
            # anterior), entao nao faz sentido condicionar ao texto previo:
            # evita o modelo "alucinar" repeticoes na fronteira dos blocos.
            condition_on_previous_text=False,
        )
        return [
            Segment(start=s.start + offset_seconds, end=s.end + offset_seconds, text=s.text.strip())
            for s in segments
            if s.text.strip()
        ]

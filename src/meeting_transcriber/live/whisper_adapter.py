"""Liga `LiveTranscriptionPipeline` a um `WhisperModel` de verdade.
Separado do pipeline de proposito -- o pipeline em si nunca importa
`faster_whisper`, entao os testes do pipeline nunca precisam de um
modelo carregado (ver `tests/test_live_pipeline.py`)."""

from __future__ import annotations

import logging
import time
from typing import Callable, Optional, Tuple

import numpy as np

from ..transcriber import Transcriber
from ..whisper_config import DEFAULT_LIVE_PRESET, resolve_device, resolve_model_size

logger = logging.getLogger("meeting_transcriber.live")


def load_live_model(
    preset: str = DEFAULT_LIVE_PRESET, device: str = "cpu", language: Optional[str] = "pt"
) -> Tuple[object, Optional[str], float]:
    """Carrega o modelo Whisper usado SO pela previa ao vivo -- normalmente
    um preset mais rapido (`FAST`/tiny) que o da transcricao duravel, ja
    que precisa terminar bem antes da proxima janela chegar. Devolve
    (model, language, segundos_de_carregamento) -- o tempo de carregamento
    e medido aqui (Fase D, secao D.10) e repassado pra `LiveTranscript`."""
    model_size = resolve_model_size(preset)
    device = resolve_device(device)
    compute_type = "int8" if device == "cpu" else "float16"
    logger.info("Carregando modelo Whisper (ao vivo) '%s' (device=%s)...", model_size, device)
    started = time.time()
    model = Transcriber._load_model(model_size, device, compute_type)
    load_seconds = time.time() - started
    logger.info("Modelo ao vivo '%s' carregado em %.2fs.", model_size, load_seconds)
    return model, language, load_seconds


def make_transcribe_window_fn(model, language: Optional[str]) -> Callable[[np.ndarray, int], str]:
    """`samplerate` e recebido pra bater com a interface generica de
    `LiveTranscriptionPipeline`, mas na pratica o pipeline so roda com
    audio ja capturado em 16kHz (`audio_capture.SAMPLE_RATE`) -- a mesma
    taxa nativa do Whisper, entao nao ha reamostragem nenhuma aqui."""

    def _transcribe_window(samples: np.ndarray, samplerate: int) -> str:
        segments, _info = model.transcribe(
            samples,
            language=language,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments if s.text.strip())

    return _transcribe_window

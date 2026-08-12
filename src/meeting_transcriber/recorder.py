"""Gravacao continua do audio do sistema em blocos (chunks) de WAV.

A gravacao roda em uma thread dedicada e nunca para para esperar a
transcricao: cada bloco completo e colocado em uma fila (queue.Queue) assim
que e gravado em disco, para que uma thread consumidora transcreva no seu
proprio ritmo sem introduzir buracos na gravacao. Isso e o que permite lidar
com reunioes de horas de duracao sem estourar memoria (so ficam em RAM os
~`chunk_seconds` mais recentes) e sem perder audio caso a transcricao de um
bloco demore mais que o normal.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np
import soundfile as sf

from .audio_capture import SAMPLE_RATE, get_loopback_microphone

logger = logging.getLogger(__name__)

BLOCK_SECONDS = 0.5  # granularidade de leitura, para reagir rapido ao Ctrl+C


@dataclass
class RecordedChunk:
    path: Path
    index: int
    start_offset_seconds: float
    duration_seconds: float


def write_chunk(
    buffer: List[np.ndarray],
    session_dir: Path,
    index: int,
    start_offset_seconds: float,
    samplerate: int,
) -> RecordedChunk:
    """Concatena os blocos de audio acumulados e grava um arquivo WAV.

    Fica separada do loop de gravacao ao vivo para poder ser testada com
    audio sintetico, sem precisar de microfone/placa de som real.
    """
    audio = np.concatenate(buffer) if buffer else np.zeros(0, dtype=np.float32)
    path = session_dir / f"chunk_{index:05d}.wav"
    sf.write(str(path), audio, samplerate, subtype="PCM_16")
    duration = len(audio) / samplerate
    return RecordedChunk(
        path=path,
        index=index,
        start_offset_seconds=start_offset_seconds,
        duration_seconds=duration,
    )


def recording_worker(
    session_dir: Path,
    chunk_seconds: int,
    stop_event: threading.Event,
    out_queue: "queue.Queue[Optional[RecordedChunk]]",
    samplerate: int = SAMPLE_RATE,
) -> None:
    """Grava continuamente ate `stop_event` ser sinalizado, colocando cada
    `RecordedChunk` concluido em `out_queue`. Ao final (inclusive o ultimo
    bloco parcial), coloca `None` na fila para avisar o consumidor que a
    gravacao acabou.

    Deve rodar em sua propria thread: o loop de leitura do microfone nao
    pode ficar bloqueado esperando a transcricao terminar.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    block_frames = max(1, int(BLOCK_SECONDS * samplerate))
    chunk_frames = int(chunk_seconds * samplerate)

    mic = get_loopback_microphone()
    buffer: List[np.ndarray] = []
    buffered_frames = 0
    chunk_index = 0
    cumulative_seconds = 0.0

    try:
        with mic.recorder(samplerate=samplerate, channels=1) as rec:
            while not stop_event.is_set():
                block = np.asarray(rec.record(numframes=block_frames), dtype=np.float32).reshape(-1)
                buffer.append(block)
                buffered_frames += len(block)

                if buffered_frames >= chunk_frames:
                    chunk = write_chunk(buffer, session_dir, chunk_index, cumulative_seconds, samplerate)
                    logger.info(
                        "Bloco %d gravado (%.1fs) -> %s", chunk_index, chunk.duration_seconds, chunk.path
                    )
                    cumulative_seconds += chunk.duration_seconds
                    chunk_index += 1
                    buffer, buffered_frames = [], 0
                    out_queue.put(chunk)

        if buffer:
            chunk = write_chunk(buffer, session_dir, chunk_index, cumulative_seconds, samplerate)
            logger.info(
                "Bloco final %d gravado (%.1fs) -> %s", chunk_index, chunk.duration_seconds, chunk.path
            )
            out_queue.put(chunk)
    finally:
        out_queue.put(None)

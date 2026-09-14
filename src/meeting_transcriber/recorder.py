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
from typing import Callable, List, Optional

import numpy as np
import soundfile as sf

from .audio_capture import SAMPLE_RATE, get_loopback_microphone

logger = logging.getLogger(__name__)

BLOCK_SECONDS = 0.5  # granularidade de leitura, para reagir rapido ao Ctrl+C


@dataclass
class RecordedChunk:
    """Metadados de um bloco de audio ja gravado em disco (pronto pra transcrever)."""

    path: Path  # onde o .wav desse bloco foi salvo
    index: int  # numero sequencial do bloco (0, 1, 2, ...) dentro da sessao
    start_offset_seconds: float  # em que segundo da GRAVACAO INTEIRA esse bloco comeca
    duration_seconds: float  # duracao real do bloco (pode ser menor que chunk_seconds no ultimo)


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
    mic_factory: Callable[[], "sc.Microphone"] = get_loopback_microphone,  # noqa: F821
    on_chunk_recorded: Optional[Callable[[RecordedChunk], None]] = None,
) -> None:
    """Grava continuamente ate `stop_event` ser sinalizado, colocando cada
    `RecordedChunk` concluido em `out_queue`. Ao final (inclusive o ultimo
    bloco parcial), coloca `None` na fila para avisar o consumidor que a
    gravacao acabou.

    `mic_factory` e `on_chunk_recorded` existem para permitir testar toda a
    logica de particionamento em blocos (buffer parcial, sequencia, sinal de
    fim) com um microfone falso, sem precisar de placa de som real. Quem
    chama pode usar `on_chunk_recorded` pra espelhar cada bloco gravado em
    algum lugar durável (ex.: `session.MeetingSession.mark_chunk_recorded`)
    sem que este modulo precise saber nada sobre sessao/persistencia.

    Deve rodar em sua propria thread: o loop de leitura do microfone nao
    pode ficar bloqueado esperando a transcricao terminar.
    """
    session_dir.mkdir(parents=True, exist_ok=True)
    block_frames = max(1, int(BLOCK_SECONDS * samplerate))  # frames por leitura (0.5s)
    chunk_frames = int(chunk_seconds * samplerate)  # frames necessarios pra fechar 1 bloco completo

    buffer: List[np.ndarray] = []  # pedacinhos de 0.5s acumulados ate formar um bloco inteiro
    buffered_frames = 0
    chunk_index = 0
    cumulative_seconds = 0.0  # posicao (em segundos) do inicio do proximo bloco na gravacao inteira

    def _emit(chunk: RecordedChunk) -> None:
        out_queue.put(chunk)
        if on_chunk_recorded is not None:
            try:
                on_chunk_recorded(chunk)
            except Exception:  # notificacao de progresso nao pode derrubar a gravacao
                logger.exception("Falha ao notificar chunk %d gravado", chunk.index)

    try:
        # mic_factory() (abrir o dispositivo de audio) tem que estar DENTRO
        # deste try: se o dispositivo nao existir/nao abrir (ex.: nenhum
        # loopback disponivel), a excecao precisa passar pelo `finally` que
        # poe o sentinela `None` na fila. Sem isso, cli.py fica bloqueado
        # para sempre em `chunk_queue.get()` -- nem o shutdown gracioso
        # consegue desbloquear um `queue.Queue.get()` sem sentinela.
        mic = mic_factory()
        # abre o stream de gravacao uma unica vez e le em pedacos pequenos
        # (BLOCK_SECONDS) pra continuar respondendo rapido ao Ctrl+C mesmo
        # com chunk_seconds grande (ex.: 300s = 5min).
        with mic.recorder(samplerate=samplerate, channels=1) as rec:
            while not stop_event.is_set():
                block = np.asarray(rec.record(numframes=block_frames), dtype=np.float32).reshape(-1)
                buffer.append(block)
                buffered_frames += len(block)

                # buffer encheu o suficiente pra fechar mais um bloco: grava
                # em disco e manda pra fila de transcricao (que roda em
                # outra thread, sem travar a gravacao que continua aqui).
                if buffered_frames >= chunk_frames:
                    chunk = write_chunk(buffer, session_dir, chunk_index, cumulative_seconds, samplerate)
                    logger.info(
                        "Bloco %d gravado (%.1fs) -> %s", chunk_index, chunk.duration_seconds, chunk.path
                    )
                    cumulative_seconds += chunk.duration_seconds
                    chunk_index += 1
                    buffer, buffered_frames = [], 0
                    _emit(chunk)

        # Ctrl+C/parada graciosa interrompeu o loop: ainda sobra um bloco
        # parcial (menor que chunk_seconds) no buffer — grava e transcreve
        # ele tambem, senao os ultimos segundos da reuniao seriam perdidos.
        if buffer:
            chunk = write_chunk(buffer, session_dir, chunk_index, cumulative_seconds, samplerate)
            logger.info(
                "Bloco final %d gravado (%.1fs) -> %s", chunk_index, chunk.duration_seconds, chunk.path
            )
            _emit(chunk)
    finally:
        # sinal de "acabou" pra thread consumidora parar de esperar por mais blocos
        out_queue.put(None)

"""Mixagem de duas fontes de audio (sistema + microfone) num unico sinal
pra transcrever. Deliberadamente simples: soma + normalizacao so quando o
pico realmente estoura (nunca reduz volume sem necessidade), sem DSP
sofisticado (sem cancelamento de eco, sem compressor/EQ) -- ver
docs/RECOVERY.md e docs/ARCHITECTURE.md para o raciocinio de escopo desta
fase.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from ..recorder import RecordedChunk


def pad_to_length(samples: np.ndarray, length: int) -> np.ndarray:
    """Completa `samples` com silencio (zeros) ate `length` amostras, ou
    corta se for mais longo. As duas fontes raramente tem exatamente o
    mesmo numero de amostras no mesmo chunk (jitter de agendamento entre
    as duas threads de captura) -- isso absorve essa pequena diferenca sem
    distorcer nenhuma das duas."""
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    if len(samples) == length:
        return samples
    if len(samples) > length:
        return samples[:length]
    return np.concatenate([samples, np.zeros(length - len(samples), dtype=np.float32)])


def mix_samples(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Soma dois sinais (mesmo tamanho) com protecao contra clipping:
    normaliza o pico combinado de volta pra +-1.0 SO SE ele realmente
    estourar essa faixa -- preserva o volume original quando a soma
    simples ja cabe, em vez de sempre reduzir por precaucao."""
    a = np.asarray(a, dtype=np.float32).reshape(-1)
    b = np.asarray(b, dtype=np.float32).reshape(-1)
    if len(a) != len(b):
        length = max(len(a), len(b))
        a = pad_to_length(a, length)
        b = pad_to_length(b, length)

    combined = a.astype(np.float32) + b.astype(np.float32)
    peak = float(np.max(np.abs(combined))) if combined.size else 0.0
    if peak > 1.0:
        combined = combined / peak
    return combined.astype(np.float32)


def _read_chunk_audio(chunk: Optional[RecordedChunk]) -> np.ndarray:
    """Le o WAV de um chunk gravado, ou devolve um array vazio se o chunk
    for None (fonte ja tinha terminado -- ver dual_capture._mix_loop).
    `mix_samples` trata um array vazio como silencio e completa (`pad_to_
    length`) pro tamanho da outra fonte automaticamente."""
    if chunk is None:
        return np.zeros(0, dtype=np.float32)
    data, _samplerate = sf.read(str(chunk.path), dtype="float32")
    return np.asarray(data).reshape(-1)


def mix_chunks(
    system_chunk: Optional[RecordedChunk],
    microphone_chunk: Optional[RecordedChunk],
    mixed_dir: Path,
    index: int,
    samplerate: int,
) -> RecordedChunk:
    """Le os chunks de sistema e microfone (um dos dois pode ser None se
    aquela fonte ja tiver terminado), mixa, grava o resultado em
    `mixed_dir` e devolve o `RecordedChunk` correspondente -- pronto pra
    entrar na fila de transcricao exatamente como um chunk de fonte unica.
    """
    system_audio = _read_chunk_audio(system_chunk)
    microphone_audio = _read_chunk_audio(microphone_chunk)
    mixed_audio = mix_samples(system_audio, microphone_audio)

    mixed_dir.mkdir(parents=True, exist_ok=True)
    path = mixed_dir / f"chunk_{index:05d}.wav"
    sf.write(str(path), mixed_audio, samplerate, subtype="PCM_16")

    if system_chunk is not None:
        start_offset = system_chunk.start_offset_seconds
    elif microphone_chunk is not None:
        start_offset = microphone_chunk.start_offset_seconds
    else:
        start_offset = 0.0

    duration = len(mixed_audio) / samplerate
    return RecordedChunk(path=path, index=index, start_offset_seconds=start_offset, duration_seconds=duration)

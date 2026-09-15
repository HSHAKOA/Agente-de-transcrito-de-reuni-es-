"""Mixagem de duas fontes de audio (sistema + microfone) num unico sinal
pra transcrever. Deliberadamente simples: soma + normalizacao so quando o
pico realmente estoura (nunca reduz volume sem necessidade), sem DSP
sofisticado (sem cancelamento de eco, sem compressor/EQ) -- ver
docs/RECOVERY.md e docs/ARCHITECTURE.md para o raciocinio de escopo desta
fase.
"""

from __future__ import annotations

import numpy as np


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

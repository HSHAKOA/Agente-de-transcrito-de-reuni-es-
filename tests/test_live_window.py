from __future__ import annotations

import numpy as np
import pytest

from meeting_transcriber.live.window import WindowAccumulator

SAMPLERATE = 1000  # numero redondo, facil de raciocinar em amostras


def _block(seconds: float, value: float = 0.1) -> np.ndarray:
    return np.full(int(seconds * SAMPLERATE), value, dtype=np.float32)


def test_rejects_overlap_not_smaller_than_window():
    with pytest.raises(ValueError):
        WindowAccumulator(SAMPLERATE, window_seconds=5, overlap_seconds=5)


def test_no_window_emitted_before_enough_audio():
    acc = WindowAccumulator(SAMPLERATE, window_seconds=8, overlap_seconds=0)
    windows = acc.push(_block(3))
    assert windows == []


def test_emits_first_window_exactly_at_window_seconds():
    acc = WindowAccumulator(SAMPLERATE, window_seconds=8, overlap_seconds=0)
    acc.push(_block(7))
    windows = acc.push(_block(1))
    assert len(windows) == 1
    start, end, samples = windows[0]
    assert start == 0.0
    assert end == 8.0
    assert len(samples) == 8 * SAMPLERATE


def test_back_to_back_windows_without_overlap():
    acc = WindowAccumulator(SAMPLERATE, window_seconds=4, overlap_seconds=0)
    windows = acc.push(_block(12))
    assert [(w[0], w[1]) for w in windows] == [(0.0, 4.0), (4.0, 8.0), (8.0, 12.0)]


def test_overlapping_windows_hop_correctly():
    acc = WindowAccumulator(SAMPLERATE, window_seconds=8, overlap_seconds=2)
    # hop = 6s
    windows = acc.push(_block(20))
    starts_ends = [(round(w[0], 2), round(w[1], 2)) for w in windows]
    assert starts_ends == [(0.0, 8.0), (6.0, 14.0), (12.0, 20.0)]


def test_windows_span_across_multiple_push_calls():
    acc = WindowAccumulator(SAMPLERATE, window_seconds=8, overlap_seconds=0)
    all_windows = []
    for _ in range(16):
        all_windows.extend(acc.push(_block(0.5)))  # 16 * 0.5s = 8s total
    assert len(all_windows) == 1
    assert all_windows[0][0] == 0.0
    assert all_windows[0][1] == 8.0


def test_buffer_does_not_grow_unbounded_across_many_windows():
    acc = WindowAccumulator(SAMPLERATE, window_seconds=4, overlap_seconds=1)
    for _ in range(50):
        acc.push(_block(1))
    # buffer interno nunca deveria acumular mais que ~1 janela de audio
    assert len(acc._buffer) <= 4 * SAMPLERATE + SAMPLERATE  # folga de 1s


def test_flush_final_returns_none_when_nothing_pending():
    acc = WindowAccumulator(SAMPLERATE, window_seconds=8, overlap_seconds=0)
    acc.push(_block(8))  # fecha exatamente uma janela, nada sobra
    assert acc.flush_final() is None


def test_flush_final_returns_partial_tail():
    acc = WindowAccumulator(SAMPLERATE, window_seconds=8, overlap_seconds=0)
    acc.push(_block(10))  # 1 janela completa (0-8s) + 2s sobrando
    final = acc.flush_final()
    assert final is not None
    start, end, samples = final
    assert start == 8.0
    assert end == 10.0
    assert len(samples) == 2 * SAMPLERATE


def test_flush_final_is_idempotent_after_being_called_once():
    acc = WindowAccumulator(SAMPLERATE, window_seconds=8, overlap_seconds=0)
    acc.push(_block(10))
    acc.flush_final()
    assert acc.flush_final() is None


def test_timestamps_based_on_sample_count_not_wall_clock():
    """Muitos pushes pequenos (simulando jitter de agendamento entre
    chamadas do callback) ainda produzem timestamps exatos, baseados em
    quantas amostras realmente chegaram -- nunca em quanto tempo passou
    de verdade entre as chamadas."""
    acc = WindowAccumulator(SAMPLERATE, window_seconds=2, overlap_seconds=0)
    windows = []
    # blocos "estranhos" de tamanhos variados, somando exatamente 6s -- 3
    # janelas completas de 2s cada, nao importa como o audio chegou picado
    total = 0.0
    for s in [0.3, 0.25, 0.45, 1.0, 0.9, 0.4, 0.5, 1.0, 1.2]:  # soma = 6.0s
        windows.extend(acc.push(_block(s)))
        total += s
    assert round(total, 2) == 6.0
    assert [(round(w[0], 2), round(w[1], 2)) for w in windows] == [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]

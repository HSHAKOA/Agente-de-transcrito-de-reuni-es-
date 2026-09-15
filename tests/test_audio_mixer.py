import numpy as np

from meeting_transcriber.audio.mixer import mix_samples, pad_to_length


def test_pad_to_length_extends_with_silence():
    result = pad_to_length(np.array([1.0, 2.0], dtype=np.float32), 5)
    assert list(result) == [1.0, 2.0, 0.0, 0.0, 0.0]


def test_pad_to_length_truncates_when_longer():
    result = pad_to_length(np.array([1.0, 2.0, 3.0], dtype=np.float32), 2)
    assert list(result) == [1.0, 2.0]


def test_pad_to_length_noop_when_already_correct_length():
    original = np.array([1.0, 2.0], dtype=np.float32)
    result = pad_to_length(original, 2)
    assert list(result) == [1.0, 2.0]


def test_mix_samples_sums_without_clipping_when_within_range():
    a = np.full(100, 0.2, dtype=np.float32)
    b = np.full(100, 0.1, dtype=np.float32)
    mixed = mix_samples(a, b)
    assert np.allclose(mixed, 0.3, atol=1e-6)  # soma direta, sem normalizar (nao estourou)


def test_mix_samples_normalizes_when_peak_would_clip():
    a = np.full(100, 0.8, dtype=np.float32)
    b = np.full(100, 0.8, dtype=np.float32)
    mixed = mix_samples(a, b)
    assert np.max(np.abs(mixed)) <= 1.0 + 1e-6
    # a proporcao entre as duas fontes se mantem (ambas iguais aqui)
    assert np.allclose(mixed, mixed[0], atol=1e-6)


def test_mix_samples_preserves_relative_proportion_after_normalizing():
    a = np.full(100, 0.9, dtype=np.float32)
    b = np.full(100, 0.3, dtype=np.float32)
    mixed = mix_samples(a, b)
    # a estourou mais que b -- depois de normalizar, a proporcao 0.9:0.3 (3:1) se mantem
    assert np.max(np.abs(mixed)) <= 1.0 + 1e-6


def test_mix_samples_pads_mismatched_lengths_instead_of_raising():
    a = np.full(100, 0.1, dtype=np.float32)
    b = np.full(80, 0.1, dtype=np.float32)
    mixed = mix_samples(a, b)
    assert len(mixed) == 100


def test_mix_samples_silence_plus_silence_is_silence():
    a = np.zeros(50, dtype=np.float32)
    b = np.zeros(50, dtype=np.float32)
    mixed = mix_samples(a, b)
    assert np.all(mixed == 0.0)


def test_mix_samples_one_source_silent_returns_other_unchanged():
    a = np.full(50, 0.3, dtype=np.float32)
    b = np.zeros(50, dtype=np.float32)
    mixed = mix_samples(a, b)
    assert np.allclose(mixed, 0.3, atol=1e-6)

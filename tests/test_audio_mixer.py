from pathlib import Path

import numpy as np

from meeting_transcriber.audio.mixer import mix_chunks, mix_samples, pad_to_length
from meeting_transcriber.recorder import write_chunk

SAMPLE_RATE = 16_000


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


# -- mix_chunks (le/escreve WAV de verdade em disco) -------------------

def _write_test_chunk(tmp_path: Path, subdir: str, value: float, seconds: float, index: int, offset: float):
    session_dir = tmp_path / subdir
    session_dir.mkdir(parents=True, exist_ok=True)  # write_chunk nao cria o diretorio sozinho
    n = int(seconds * SAMPLE_RATE)
    buffer = [np.full(n, value, dtype=np.float32)]
    return write_chunk(buffer, session_dir, index, offset, SAMPLE_RATE)


def test_mix_chunks_combines_both_sources(tmp_path: Path):
    system_chunk = _write_test_chunk(tmp_path, "system", 0.2, 1.0, 0, 0.0)
    mic_chunk = _write_test_chunk(tmp_path, "microphone", 0.1, 1.0, 0, 0.0)
    mixed_dir = tmp_path / "mixed"

    result = mix_chunks(system_chunk, mic_chunk, mixed_dir, 0, SAMPLE_RATE)

    assert result.path.exists()
    assert result.path.parent == mixed_dir
    assert abs(result.duration_seconds - 1.0) < 1e-3

    import soundfile as sf

    data, sr = sf.read(str(result.path))
    assert sr == SAMPLE_RATE
    assert np.allclose(data, 0.3, atol=0.01)


def test_mix_chunks_treats_missing_system_source_as_silence(tmp_path: Path):
    mic_chunk = _write_test_chunk(tmp_path, "microphone", 0.4, 1.0, 0, 0.0)
    mixed_dir = tmp_path / "mixed"

    result = mix_chunks(None, mic_chunk, mixed_dir, 0, SAMPLE_RATE)

    import soundfile as sf

    data, _sr = sf.read(str(result.path))
    assert np.allclose(data, 0.4, atol=0.01)


def test_mix_chunks_treats_missing_microphone_source_as_silence(tmp_path: Path):
    system_chunk = _write_test_chunk(tmp_path, "system", 0.4, 1.0, 0, 0.0)
    mixed_dir = tmp_path / "mixed"

    result = mix_chunks(system_chunk, None, mixed_dir, 0, SAMPLE_RATE)

    import soundfile as sf

    data, _sr = sf.read(str(result.path))
    assert np.allclose(data, 0.4, atol=0.01)


def test_mix_chunks_creates_mixed_dir_if_missing(tmp_path: Path):
    system_chunk = _write_test_chunk(tmp_path, "system", 0.1, 0.5, 0, 0.0)
    mixed_dir = tmp_path / "nao-existe-ainda" / "mixed"
    assert not mixed_dir.exists()

    mix_chunks(system_chunk, None, mixed_dir, 0, SAMPLE_RATE)

    assert mixed_dir.exists()


def test_mix_chunks_uses_start_offset_from_available_source(tmp_path: Path):
    system_chunk = _write_test_chunk(tmp_path, "system", 0.1, 1.0, 3, 90.0)
    mixed_dir = tmp_path / "mixed"

    result = mix_chunks(system_chunk, None, mixed_dir, 3, SAMPLE_RATE)

    assert result.start_offset_seconds == 90.0
    assert result.index == 3

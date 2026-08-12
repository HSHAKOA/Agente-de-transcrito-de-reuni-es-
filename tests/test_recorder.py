from pathlib import Path

import numpy as np
import soundfile as sf

from meeting_transcriber.recorder import write_chunk

SAMPLE_RATE = 16_000


def _sine(seconds: float, freq: float = 440.0, samplerate: int = SAMPLE_RATE) -> np.ndarray:
    t = np.linspace(0, seconds, int(samplerate * seconds), endpoint=False)
    return (0.1 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_write_chunk_creates_wav_with_expected_duration(tmp_path: Path):
    blocks = [_sine(0.5), _sine(0.5), _sine(0.25)]
    chunk = write_chunk(blocks, tmp_path, index=0, start_offset_seconds=0.0, samplerate=SAMPLE_RATE)

    assert chunk.path.exists()
    assert chunk.index == 0
    assert chunk.start_offset_seconds == 0.0
    assert abs(chunk.duration_seconds - 1.25) < 1e-6

    data, samplerate = sf.read(str(chunk.path))
    assert samplerate == SAMPLE_RATE
    assert abs(len(data) / samplerate - 1.25) < 1e-6


def test_write_chunk_naming_and_offsets(tmp_path: Path):
    chunk0 = write_chunk([_sine(1.0)], tmp_path, index=0, start_offset_seconds=0.0, samplerate=SAMPLE_RATE)
    chunk1 = write_chunk([_sine(1.0)], tmp_path, index=1, start_offset_seconds=chunk0.duration_seconds, samplerate=SAMPLE_RATE)

    assert chunk0.path.name == "chunk_00000.wav"
    assert chunk1.path.name == "chunk_00001.wav"
    assert chunk1.start_offset_seconds == chunk0.duration_seconds


def test_write_chunk_empty_buffer(tmp_path: Path):
    chunk = write_chunk([], tmp_path, index=0, start_offset_seconds=0.0, samplerate=SAMPLE_RATE)
    assert chunk.duration_seconds == 0.0
    assert chunk.path.exists()

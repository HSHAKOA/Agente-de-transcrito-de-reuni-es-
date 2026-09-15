import numpy as np
import pytest

from meeting_transcriber.audio.levels import (
    ACTIVE_THRESHOLD,
    LevelMeter,
    compute_rms,
    normalize_level,
)


def _sine(amplitude: float, n: int = 1600) -> np.ndarray:
    t = np.linspace(0, 1, n, endpoint=False)
    return (amplitude * np.sin(2 * np.pi * 10 * t)).astype(np.float32)


def test_compute_rms_of_empty_array_is_zero():
    assert compute_rms(np.array([], dtype=np.float32)) == 0.0


def test_compute_rms_of_silence_is_zero():
    assert compute_rms(np.zeros(1000, dtype=np.float32)) == 0.0


def test_compute_rms_of_full_scale_sine_is_close_to_expected():
    # RMS de uma senoide de amplitude A e A/sqrt(2)
    signal = _sine(1.0)
    rms = compute_rms(signal)
    assert abs(rms - (1.0 / (2**0.5))) < 0.01


def test_compute_rms_scales_with_amplitude():
    quiet = compute_rms(_sine(0.1))
    loud = compute_rms(_sine(0.5))
    assert loud > quiet


def test_normalize_level_zero_for_silence():
    assert normalize_level(0.0) == 0.0


def test_normalize_level_saturates_at_one():
    assert normalize_level(10.0, reference=0.2) == 1.0


def test_normalize_level_proportional_below_reference():
    assert normalize_level(0.1, reference=0.2) == pytest.approx(0.5)


def test_normalize_level_negative_rms_treated_as_zero():
    assert normalize_level(-1.0) == 0.0


def test_normalize_level_zero_reference_never_divides_by_zero():
    assert normalize_level(0.5, reference=0.0) == 0.0


# -- LevelMeter -----------------------------------------------------------

def test_level_meter_starts_empty():
    meter = LevelMeter()
    assert meter.snapshot() == {}
    assert meter.get("system") is None


def test_level_meter_update_and_snapshot():
    meter = LevelMeter()
    meter.update("system", 0.5)
    meter.update("microphone", 0.1)

    snap = meter.snapshot()
    assert set(snap.keys()) == {"system", "microphone"}
    assert snap["system"]["level"] == 0.5
    assert "updated_at" in snap["system"]


def test_level_meter_active_flag_reflects_threshold():
    meter = LevelMeter()
    meter.update("system", ACTIVE_THRESHOLD - 0.001)
    meter.update("microphone", ACTIVE_THRESHOLD + 0.001)

    assert meter.get("system")["active"] is False
    assert meter.get("microphone")["active"] is True


def test_level_meter_snapshot_is_a_copy_not_live_view():
    meter = LevelMeter()
    meter.update("system", 0.5)
    snap = meter.snapshot()
    meter.update("system", 0.9)
    assert snap["system"]["level"] == 0.5  # a copia anterior nao muda

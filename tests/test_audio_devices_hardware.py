"""Testes que tocam o backend de audio DE VERDADE (sem `backend=` falso) --
diferente do resto da suite de audio, que roda so com dublês. Servem como
evidencia real de hardware nesta maquina, nao como parte da cobertura que
CI/ambientes sem placa de som podem rodar.

Pulados automaticamente (nao falham a suite) se nao houver nenhum
dispositivo de audio disponivel no ambiente onde rodam.
"""

from __future__ import annotations

import pytest

from meeting_transcriber.audio.devices import check_device_health, list_devices
from meeting_transcriber.audio.models import AudioError


def _has_real_audio_hardware() -> bool:
    try:
        devices = list_devices()
    except AudioError:
        return False
    return bool(devices["inputs"]) or bool(devices["outputs"])


pytestmark = pytest.mark.skipif(
    not _has_real_audio_hardware(), reason="nenhum dispositivo de audio real disponivel neste ambiente"
)


def test_real_output_devices_are_listed_with_exactly_one_default():
    devices = list_devices()
    assert len(devices["outputs"]) >= 1
    defaults = [d for d in devices["outputs"] if d["is_default"]]
    assert len(defaults) == 1


def test_real_input_devices_are_listed():
    devices = list_devices()
    # nem toda maquina tem microfone conectado -- so confere que, se
    # houver algum, exatamente um esta marcado como padrao.
    defaults = [d for d in devices["inputs"] if d["is_default"]]
    assert len(defaults) <= 1


def test_real_default_output_loopback_health_check_succeeds():
    devices = list_devices()
    default_output = next((d for d in devices["outputs"] if d["is_default"]), None)
    if default_output is None:
        pytest.skip("nenhuma saida padrao disponivel")
    result = check_device_health("output", default_output["id"], samplerate=16000, probe_seconds=0.2)
    assert result.ok, result.message
    assert result.level is not None


def test_real_default_input_health_check_when_microphone_present():
    devices = list_devices()
    default_input = next((d for d in devices["inputs"] if d["is_default"]), None)
    if default_input is None:
        pytest.skip("nenhum microfone disponivel neste ambiente")
    result = check_device_health("input", default_input["id"], samplerate=16000, probe_seconds=0.2)
    assert result.ok, result.message
    assert result.level is not None

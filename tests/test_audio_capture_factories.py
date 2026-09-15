"""Testes das fabricas finas loopback.py/microphone.py -- confirmam so a
delegacao correta e a preguica (resolve so quando chamada), a logica real
de resolucao ja e coberta em test_audio_devices.py."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from meeting_transcriber.audio.loopback import make_loopback_mic_factory
from meeting_transcriber.audio.microphone import make_microphone_factory
from meeting_transcriber.audio.models import AudioError, AudioErrorCode


@dataclass
class _FakeDevice:
    id: str
    name: str = "Dispositivo Falso"


class _FakeBackend:
    def __init__(self):
        self.calls = []

    def default_speaker(self):
        self.calls.append("default_speaker")
        return _FakeDevice("spk-default")

    def get_speaker(self, device_id):
        self.calls.append(("get_speaker", device_id))
        return _FakeDevice(device_id)

    def get_microphone(self, id, include_loopback=False):  # noqa: A002
        self.calls.append(("get_microphone", id, include_loopback))
        return _FakeDevice(id)

    def default_microphone(self):
        self.calls.append("default_microphone")
        return _FakeDevice("mic-default")


def test_loopback_factory_is_lazy_until_called():
    backend = _FakeBackend()
    factory = make_loopback_mic_factory("spk-1", backend=backend)
    assert backend.calls == []  # nada resolvido so por criar a factory
    factory()
    assert backend.calls  # so resolveu quando chamada


def test_loopback_factory_resolves_default_when_no_id():
    backend = _FakeBackend()
    factory = make_loopback_mic_factory(None, backend=backend)
    mic = factory()
    assert mic.id == "spk-default"


def test_loopback_factory_resolves_specific_device():
    backend = _FakeBackend()
    factory = make_loopback_mic_factory("spk-1", backend=backend)
    mic = factory()
    assert mic.id == "spk-1"


def test_microphone_factory_is_lazy_until_called():
    backend = _FakeBackend()
    factory = make_microphone_factory("mic-1", backend=backend)
    assert backend.calls == []
    factory()
    assert backend.calls


def test_microphone_factory_resolves_default_when_no_id():
    backend = _FakeBackend()
    factory = make_microphone_factory(None, backend=backend)
    mic = factory()
    assert mic.id == "mic-default"


def test_microphone_factory_raises_audio_error_for_unknown_device():
    class _BrokenBackend(_FakeBackend):
        def get_microphone(self, id, include_loopback=False):  # noqa: A002
            raise LookupError("nao existe")

    factory = make_microphone_factory("nao-existe", backend=_BrokenBackend())
    with pytest.raises(AudioError) as exc_info:
        factory()
    assert exc_info.value.code == AudioErrorCode.DEVICE_NOT_FOUND

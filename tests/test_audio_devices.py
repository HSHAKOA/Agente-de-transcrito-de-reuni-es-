"""Testes de devices.py com um backend falso (mesma superficie do modulo
`soundcard`) -- nenhum destes precisa de placa de som/microfone real.
Testes que exigem hardware de verdade ficam em test_audio_devices_hardware.py.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from typing import List

import numpy as np
import pytest

from meeting_transcriber.audio import devices as devices_module
from meeting_transcriber.audio.devices import (
    check_device_health,
    list_devices,
    list_input_devices,
    list_output_devices,
    resolve_input_device,
    resolve_loopback_source,
    resolve_output_device,
)
from meeting_transcriber.audio.models import AudioError, AudioErrorCode


@dataclass
class _FakeEndpoint:
    id: str
    name: str


class _FakeRecorderStream:
    def __init__(self, samples: np.ndarray, raise_on_open: Exception | None = None):
        self._samples = samples
        self._raise_on_open = raise_on_open

    def __enter__(self):
        if self._raise_on_open:
            raise self._raise_on_open
        return self

    def __exit__(self, *exc):
        return False

    def record(self, numframes: int) -> np.ndarray:
        return self._samples[:numframes]


class _FakeMic(_FakeEndpoint):
    def __init__(self, id: str, name: str, samples: np.ndarray | None = None, fail_open: Exception | None = None):
        super().__init__(id, name)
        self._samples = samples if samples is not None else np.zeros(4800, dtype=np.float32)
        self._fail_open = fail_open

    def recorder(self, samplerate: int, channels: int):
        return _FakeRecorderStream(self._samples, raise_on_open=self._fail_open)


class FakeBackend:
    """Dublê do modulo `soundcard`: guarda listas de speakers/mics falsos
    e resolve por id do mesmo jeito que a API real."""

    def __init__(self, speakers: List[_FakeEndpoint], mics: List[_FakeMic], default_speaker_id: str, default_mic_id: str):
        self._speakers = speakers
        self._mics = mics
        self._default_speaker_id = default_speaker_id
        self._default_mic_id = default_mic_id

    def all_speakers(self):
        return list(self._speakers)

    def all_microphones(self, include_loopback: bool = False):
        if include_loopback:
            # loopback "mics" sao os proprios speakers, como no soundcard real
            return [_FakeMic(s.id, s.name) for s in self._speakers] + list(self._mics)
        return list(self._mics)

    def default_speaker(self):
        return next(s for s in self._speakers if s.id == self._default_speaker_id)

    def default_microphone(self):
        return next(m for m in self._mics if m.id == self._default_mic_id)

    def get_speaker(self, device_id):
        for s in self._speakers:
            if s.id == device_id:
                return s
        raise LookupError(f"no such speaker: {device_id}")

    def get_microphone(self, id, include_loopback: bool = False):  # noqa: A002 - nome espelha a lib real
        for s in self._speakers:
            if s.id == id:
                return _FakeMic(s.id, s.name)
        for m in self._mics:
            if m.id == id:
                return m
        raise LookupError(f"no such microphone: {id}")


@pytest.fixture
def backend() -> FakeBackend:
    return FakeBackend(
        speakers=[_FakeEndpoint("spk-1", "Alto-falantes"), _FakeEndpoint("spk-2", "Fones de ouvido")],
        mics=[_FakeMic("mic-1", "Microfone USB")],
        default_speaker_id="spk-2",
        default_mic_id="mic-1",
    )


# -- listagem -------------------------------------------------------------

def test_list_output_devices_marks_default(backend: FakeBackend):
    outputs = list_output_devices(backend=backend)
    assert {d.id for d in outputs} == {"spk-1", "spk-2"}
    assert next(d for d in outputs if d.id == "spk-2").is_default is True
    assert next(d for d in outputs if d.id == "spk-1").is_default is False


def test_list_output_devices_all_support_loopback(backend: FakeBackend):
    outputs = list_output_devices(backend=backend)
    assert all(d.loopback_supported for d in outputs)


def test_list_input_devices_marks_default_and_excludes_loopback(backend: FakeBackend):
    inputs = list_input_devices(backend=backend)
    assert [d.id for d in inputs] == ["mic-1"]
    assert inputs[0].is_default is True


def test_list_devices_returns_dto_dicts_not_raw_objects(backend: FakeBackend):
    result = list_devices(backend=backend)
    assert "inputs" in result and "outputs" in result
    assert all(isinstance(d, dict) for d in result["inputs"] + result["outputs"])
    # id usado como chave, nao o nome de exibicao
    assert all("id" in d and "name" in d for d in result["inputs"])


def test_list_output_devices_wraps_backend_failure_as_audio_error():
    class _BrokenBackend:
        def all_speakers(self):
            raise RuntimeError("PortAudioError: 0x80004005 cryptic native failure")

        def default_speaker(self):
            raise RuntimeError("PortAudioError: 0x80004005 cryptic native failure")

    with pytest.raises(AudioError) as exc_info:
        list_output_devices(backend=_BrokenBackend())
    assert exc_info.value.code == AudioErrorCode.BACKEND_UNAVAILABLE
    # a mensagem pro cliente nunca deve conter o texto cru da excecao do
    # backend (missao, secao "Erros") -- o detalhe tecnico vai so pro log.
    assert "PortAudioError" not in exc_info.value.message
    assert "0x80004005" not in exc_info.value.message


# -- resolucao --------------------------------------------------------------

def test_resolve_output_device_by_id(backend: FakeBackend):
    device = resolve_output_device("spk-1", backend=backend)
    assert device.id == "spk-1"


def test_resolve_output_device_default_when_id_none(backend: FakeBackend):
    device = resolve_output_device(None, backend=backend)
    assert device.id == "spk-2"


def test_resolve_output_device_raises_device_not_found(backend: FakeBackend):
    with pytest.raises(AudioError) as exc_info:
        resolve_output_device("nao-existe", backend=backend)
    assert exc_info.value.code == AudioErrorCode.DEVICE_NOT_FOUND
    assert exc_info.value.device_id == "nao-existe"


def test_resolve_input_device_raises_device_not_found(backend: FakeBackend):
    with pytest.raises(AudioError) as exc_info:
        resolve_input_device("nao-existe", backend=backend)
    assert exc_info.value.code == AudioErrorCode.DEVICE_NOT_FOUND


def test_resolve_loopback_source_resolves_via_output_device(backend: FakeBackend):
    mic = resolve_loopback_source("spk-1", backend=backend)
    assert mic.id == "spk-1"


def test_resolve_loopback_source_device_not_found_for_bad_output_id(backend: FakeBackend):
    with pytest.raises(AudioError) as exc_info:
        resolve_loopback_source("nao-existe", backend=backend)
    assert exc_info.value.code == AudioErrorCode.DEVICE_NOT_FOUND


# -- check_device_health -----------------------------------------------

def test_check_device_health_ok_for_working_input(backend: FakeBackend):
    result = check_device_health("input", "mic-1", samplerate=16000, backend=backend)
    assert result.ok is True
    assert result.device_id == "mic-1"
    assert result.device_name == "Microfone USB"
    assert result.level is not None


def test_check_device_health_ok_for_working_output_loopback(backend: FakeBackend):
    result = check_device_health("output", "spk-1", samplerate=16000, backend=backend)
    assert result.ok is True
    assert result.device_id == "spk-1"


def test_check_device_health_device_not_found(backend: FakeBackend):
    result = check_device_health("input", "nao-existe", samplerate=16000, backend=backend)
    assert result.ok is False
    assert result.code == AudioErrorCode.DEVICE_NOT_FOUND


def test_check_device_health_stream_failure(backend: FakeBackend):
    broken_mic = _FakeMic(
        "mic-broken", "Microfone Quebrado", fail_open=OSError("0xdeadbeef native PortAudio failure")
    )
    backend._mics.append(broken_mic)
    result = check_device_health("input", "mic-broken", samplerate=16000, backend=backend)
    assert result.ok is False
    assert result.code == AudioErrorCode.STREAM_FAILED
    assert "0xdeadbeef" not in result.message  # nunca vaza o erro cru da lib nativa


def test_check_device_health_invalid_kind_raises_value_error(backend: FakeBackend):
    with pytest.raises(ValueError):
        check_device_health("nonsense", "mic-1", samplerate=16000, backend=backend)


def test_check_device_health_level_reflects_real_signal(backend: FakeBackend):
    loud_mic = _FakeMic("mic-loud", "Microfone Alto", samples=np.full(4800, 0.5, dtype=np.float32))
    backend._mics.append(loud_mic)
    result = check_device_health("input", "mic-loud", samplerate=16000, backend=backend)
    assert result.ok is True
    assert result.level > 0.5  # RMS de 0.5 constante normalizado (referencia 0.2) satura em 1.0


# -- inicializacao de COM por thread (regressao: CO_E_NOTINITIALIZED) ------
#
# Cada thread que chama uma interface COM diretamente precisa ter chamado
# CoInitializeEx pelo menos uma vez -- `soundcard` so faz isso na thread
# que primeiro importa o modulo. `_ensure_com_initialized_for_this_thread`
# fecha essa lacuna para qualquer outra thread (ex.: cada request de
# `ThreadingHTTPServer` em webui.py) que chame `_backend()`.
#
# Importante: estes testes chamam `_backend()` (nao a funcao privada de
# COM isolada) de proposito. Chamar `_ensure_com_initialized_for_this_thread`
# diretamente, ANTES de qualquer `import soundcard` ter acontecido nesta
# thread, reproduziria um bug real encontrado durante o desenvolvimento
# deste fix: se COM ja estiver inicializado quando `soundcard` importa
# pela primeira vez (em qualquer thread do processo), o `_COMLibrary()`
# interno da propria lib recebe `S_FALSE` do seu proprio `CoInitializeEx`
# e o tratamento de erro dela so perdoa `RPC_E_CHANGED_MODE`, nao
# `S_FALSE` -- resultado: `import soundcard` passa a lancar `RuntimeError`
# e QUALQUER teste (inclusive os de hardware) que dependa dele quebra.
# `_backend()` evita isso host importando primeiro; os testes abaixo
# passam por ele para exercitar o caminho real, nao um atalho perigoso.

pytestmark_com = pytest.mark.skipif(sys.platform != "win32", reason="COM e especifico do Windows")


@pytestmark_com
def test_ensure_com_initialized_is_idempotent_for_current_thread():
    try:
        devices_module._backend()
        devices_module._backend()  # nao deve lancar nem reinicializar
    except AudioError:
        pytest.skip("motor de audio indisponivel neste ambiente")
    assert threading.get_ident() in devices_module._com_initialized_thread_ids


@pytestmark_com
def test_ensure_com_initialized_works_from_a_freshly_spawned_thread():
    outcome: dict = {}

    def _worker():
        try:
            devices_module._backend()
            outcome["thread_id"] = threading.get_ident()
        except AudioError as exc:
            outcome["skip"] = str(exc)
        except Exception as exc:  # nao deveria acontecer
            outcome["exception"] = exc

    thread = threading.Thread(target=_worker)
    thread.start()
    thread.join(timeout=5)

    assert not thread.is_alive()
    if "skip" in outcome:
        pytest.skip("motor de audio indisponivel neste ambiente")
    assert "exception" not in outcome, f"levantou excecao inesperada: {outcome.get('exception')!r}"
    assert outcome["thread_id"] != threading.get_ident()
    assert outcome["thread_id"] in devices_module._com_initialized_thread_ids

"""Descoberta e resolucao de dispositivos de audio.

Isolado do `recorder.py`/`audio_capture.py` existentes (que continuam
cuidando so da captura de loopback padrao, inalterados) para nao espalhar
logica de descoberta pelo projeto, e para poder ser testado com um
"backend" falso — todo mundo aqui aceita `backend=None` (usa o
`soundcard` de verdade, importado sob demanda) ou um objeto injetado com
a mesma superficie (`all_speakers`, `all_microphones`, `default_speaker`,
`default_microphone`, `get_speaker`, `get_microphone`), sem precisar de
hardware real pra testar a logica de resolucao/serializacao.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import numpy as np

from .models import AudioDevice, AudioError, AudioErrorCode, AudioHealthResult

logger = logging.getLogger(__name__)

# Mensagens sempre amigaveis pro cliente (nunca o texto cru da excecao do
# backend, tipo "PortAudioError: ..." -- ver missao, secao "Erros"). O
# detalhe tecnico de verdade vai so pro log do servidor.
_BACKEND_UNAVAILABLE_MESSAGE = "O motor de audio nao esta disponivel neste momento."
_STREAM_FAILED_MESSAGE = "Nao foi possivel abrir o dispositivo de audio."


def _backend():
    """Import tardio de `soundcard`: em ambientes sem servidor de audio
    (containers de CI, por exemplo) a lib falha ao carregar assim que
    importada -- adiar o import mantem o resto do modulo importavel/
    testavel nesses ambientes, so quebra aqui, na hora de falar com audio
    de verdade (mesmo raciocinio ja usado em audio_capture.py)."""
    try:
        import soundcard as sc
    except Exception as exc:  # depende do SO/driver, dificil restringir o tipo
        logger.error("Falha ao carregar o backend de audio: %s", exc)
        raise AudioError(AudioErrorCode.BACKEND_UNAVAILABLE, _BACKEND_UNAVAILABLE_MESSAGE) from exc
    return sc


def list_output_devices(backend=None) -> List[AudioDevice]:
    """Dispositivos de SAIDA (alto-falantes/fones) -- todos suportam
    loopback no Windows via WASAPI (o unico backend hoje suportado de
    verdade; ver README para Linux/macOS)."""
    sc = backend if backend is not None else _backend()
    try:
        speakers = sc.all_speakers()
        default = sc.default_speaker()
    except AudioError:
        raise
    except Exception as exc:
        logger.error("Falha ao listar dispositivos de saida: %s", exc)
        raise AudioError(AudioErrorCode.BACKEND_UNAVAILABLE, _BACKEND_UNAVAILABLE_MESSAGE) from exc
    default_id = getattr(default, "id", None)
    return [
        AudioDevice(id=s.id, name=s.name, kind="output", is_default=(s.id == default_id), loopback_supported=True)
        for s in speakers
    ]


def list_input_devices(backend=None) -> List[AudioDevice]:
    """Dispositivos de ENTRADA reais (microfones) -- exclui as entradas de
    loopback (que sao dispositivos de saida "disfarcados" de microfone,
    nao aparecem aqui pra nao confundir a lista de microfones de verdade)."""
    sc = backend if backend is not None else _backend()
    try:
        mics = sc.all_microphones(include_loopback=False)
        default = sc.default_microphone()
    except AudioError:
        raise
    except Exception as exc:
        logger.error("Falha ao listar microfones: %s", exc)
        raise AudioError(AudioErrorCode.BACKEND_UNAVAILABLE, _BACKEND_UNAVAILABLE_MESSAGE) from exc
    default_id = getattr(default, "id", None)
    return [AudioDevice(id=m.id, name=m.name, kind="input", is_default=(m.id == default_id)) for m in mics]


def list_devices(backend=None) -> dict:
    """Formato pronto para `GET /api/audio/devices` (ver docs/API.md)."""
    return {
        "inputs": [d.to_dict() for d in list_input_devices(backend=backend)],
        "outputs": [d.to_dict() for d in list_output_devices(backend=backend)],
    }


def resolve_output_device(device_id: Optional[str], backend=None):
    """Devolve o objeto `Speaker` do backend correspondente a `device_id`,
    ou o padrao do sistema se `device_id` for None."""
    sc = backend if backend is not None else _backend()
    try:
        return sc.default_speaker() if device_id is None else sc.get_speaker(device_id)
    except AudioError:
        raise
    except Exception as exc:
        logger.warning("Dispositivo de saida '%s' nao encontrado: %s", device_id, exc)
        raise AudioError(
            AudioErrorCode.DEVICE_NOT_FOUND,
            "O dispositivo de saida selecionado nao esta mais disponivel.",
            device_id=device_id,
        ) from exc


def resolve_input_device(device_id: Optional[str], backend=None):
    """Devolve o objeto `Microphone` (entrada real, nao loopback)
    correspondente a `device_id`, ou o padrao se `device_id` for None."""
    sc = backend if backend is not None else _backend()
    try:
        return sc.default_microphone() if device_id is None else sc.get_microphone(device_id, include_loopback=False)
    except AudioError:
        raise
    except Exception as exc:
        logger.warning("Microfone '%s' nao encontrado: %s", device_id, exc)
        raise AudioError(
            AudioErrorCode.DEVICE_NOT_FOUND,
            "O microfone selecionado nao esta mais disponivel.",
            device_id=device_id,
        ) from exc


def resolve_loopback_source(device_id: Optional[str], backend=None):
    """Resolve o dispositivo de SAIDA (por id, ou o padrao) e devolve o
    'microfone' de loopback correspondente -- e assim que se grava "o que
    esta tocando" nesse dispositivo (ver audio_capture.py para a captura
    do dispositivo padrao, ja em producao; isto aqui generaliza pra
    qualquer dispositivo escolhido pelo usuario)."""
    sc = backend if backend is not None else _backend()
    speaker = resolve_output_device(device_id, backend=sc)
    try:
        return sc.get_microphone(id=speaker.id, include_loopback=True)
    except Exception as exc:
        logger.error("Falha ao abrir loopback para '%s' (%s): %s", speaker.name, speaker.id, exc)
        raise AudioError(
            AudioErrorCode.STREAM_FAILED,
            f"Nao foi possivel capturar o audio do dispositivo '{speaker.name}'.",
            device_id=getattr(speaker, "id", device_id),
        ) from exc


def check_device_health(
    kind: str,
    device_id: Optional[str],
    samplerate: int,
    probe_seconds: float = 0.3,
    backend=None,
) -> AudioHealthResult:
    """Testa um dispositivo de verdade: resolve, abre um stream curto, le
    alguns frames, fecha. Usado tanto pelo health check pre-gravacao
    quanto por "Testar audio" -- nunca cria reuniao, nunca persiste nada
    alem do resultado que o chamador decidir guardar.
    """
    sc = backend if backend is not None else _backend()
    try:
        if kind == "output":
            mic = resolve_loopback_source(device_id, backend=sc)
        elif kind == "input":
            mic = resolve_input_device(device_id, backend=sc)
        else:
            raise ValueError(f"kind invalido: {kind!r} (use 'input' ou 'output')")
    except AudioError as exc:
        return AudioHealthResult(ok=False, code=exc.code, message=exc.message, device_id=device_id)

    resolved_id = getattr(mic, "id", device_id)
    frames = max(1, int(samplerate * probe_seconds))
    try:
        with mic.recorder(samplerate=samplerate, channels=1) as rec:
            block = np.asarray(rec.record(numframes=frames), dtype=np.float32).reshape(-1)
    except Exception as exc:
        logger.error("Falha ao testar stream do dispositivo '%s': %s", resolved_id, exc)
        return AudioHealthResult(
            ok=False,
            code=AudioErrorCode.STREAM_FAILED,
            message=_STREAM_FAILED_MESSAGE,
            device_id=resolved_id,
        )

    from .levels import compute_rms, normalize_level

    level = normalize_level(compute_rms(block))
    return AudioHealthResult(ok=True, code=None, message="OK", device_id=resolved_id, level=level)

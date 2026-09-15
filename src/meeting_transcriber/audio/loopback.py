"""Fabrica de captura de loopback (audio do sistema) para um dispositivo de
saida especifico. O caminho de fonte unica original
(`audio_capture.get_loopback_microphone`, sempre o dispositivo de saida
PADRAO) continua existindo e em uso -- isto aqui generaliza pra qualquer
dispositivo escolhido pelo usuario, reaproveitando o mesmo
`recorder.recording_worker` via `mic_factory`.
"""

from __future__ import annotations

from typing import Callable, Optional

from . import devices


def make_loopback_mic_factory(device_id: Optional[str] = None, backend=None) -> Callable[[], object]:
    """Devolve uma factory (callable sem argumentos, compativel com o
    `mic_factory` que `recorder.recording_worker` ja aceita) que resolve o
    dispositivo de saida indicado (ou o padrao, se `device_id` for None) e
    abre o loopback dele. A resolucao so acontece quando a factory e
    chamada (dentro da thread de gravacao), nao na hora de criar a
    factory -- assim o dispositivo escolhido e sempre o mais atual no
    momento de comecar a gravar."""

    def factory():
        return devices.resolve_loopback_source(device_id, backend=backend)

    return factory

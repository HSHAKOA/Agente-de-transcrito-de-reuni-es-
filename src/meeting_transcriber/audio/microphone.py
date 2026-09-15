"""Fabrica de captura de microfone (entrada real, nao loopback) para um
dispositivo especifico -- por padrao, o microfone padrao do sistema.
"""

from __future__ import annotations

from typing import Callable, Optional

from . import devices


def make_microphone_factory(device_id: Optional[str] = None, backend=None) -> Callable[[], object]:
    """Mesma ideia de `loopback.make_loopback_mic_factory`, mas para um
    microfone de entrada real."""

    def factory():
        return devices.resolve_input_device(device_id, backend=backend)

    return factory

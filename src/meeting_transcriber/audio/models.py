"""Modelos de dados da camada de audio: DTOs serializaveis (nunca objetos
internos da biblioteca `soundcard` expostos direto pra API/JSON) e os
codigos de erro que o frontend (HTML hoje, React futuramente) recebe no
lugar de uma exececao Python crua.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AudioDevice:
    """Representacao interna estavel de um dispositivo de audio.

    `id` e o identificador estavel do backend (no `soundcard`/Windows, o
    ID de dispositivo do MMDevice — uma string opaca tipo
    "{0.0.0.00000000}.{...guid...}"), nunca o nome de exibicao: nomes se
    repetem entre dispositivos e podem mudar (driver atualiza, Windows
    renomeia), o ID nao.
    """

    id: str
    name: str
    kind: str  # "input" | "output"
    is_default: bool
    backend: str = "soundcard"
    loopback_supported: bool = False  # so relevante para kind="output"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "is_default": self.is_default,
            **({"loopback_supported": self.loopback_supported} if self.kind == "output" else {}),
        }


@dataclass(frozen=True)
class AudioHealthResult:
    """Resultado de testar um dispositivo de verdade (abrir stream, ler
    alguns frames, fechar) -- usado tanto pelo health check pre-gravacao
    quanto por "Testar audio"."""

    ok: bool
    code: Optional[str]  # um AudioErrorCode.value, ou None se ok
    message: str
    device_id: Optional[str] = None
    level: Optional[float] = None  # RMS normalizado (0..1) do trecho lido, se conseguiu

    def to_dict(self) -> dict:
        data = {"ok": self.ok, "message": self.message}
        if self.code:
            data["code"] = self.code
        if self.device_id is not None:
            data["device_id"] = self.device_id
        if self.level is not None:
            data["level"] = self.level
        return data


class AudioErrorCode:
    """Codigos de erro estaveis, documentados em docs/API.md -- o
    frontend decide a mensagem/UI a partir do codigo, nunca faz parsing de
    texto de excecao Python."""

    DEVICE_NOT_FOUND = "AUDIO_DEVICE_NOT_FOUND"
    DEVICE_BUSY = "AUDIO_DEVICE_BUSY"
    STREAM_FAILED = "AUDIO_STREAM_FAILED"
    BACKEND_UNAVAILABLE = "AUDIO_BACKEND_UNAVAILABLE"
    NO_SOURCE_ENABLED = "AUDIO_NO_SOURCE_ENABLED"


class AudioError(Exception):
    """Erro de dominio da camada de audio. Sempre carrega um `code` de
    `AudioErrorCode` -- quem serializa pra HTTP (webui.py) usa isso pra
    montar `{"error": {"code": ..., "message": ...}}`, nunca vaza
    traceback/mensagem crua de `soundcard`/PortAudio pro cliente."""

    def __init__(self, code: str, message: str, device_id: Optional[str] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.device_id = device_id

    def to_dict(self) -> dict:
        data = {"code": self.code, "message": self.message}
        if self.device_id is not None:
            data["device_id"] = self.device_id
        return {"error": data}

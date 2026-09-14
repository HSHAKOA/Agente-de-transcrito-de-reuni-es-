"""Validacao de entrada da API HTTP local (webui.py).

O servidor local nunca deve confiar diretamente no que vem do navegador —
mesmo rodando so em 127.0.0.1, qualquer pagina/script capaz de fazer uma
requisicao para esse endereco (ex.: JS de uma aba qualquer aberta ao mesmo
tempo, um cenario classico de ataque contra servicos "so localhost") pode
tentar falar com essa API. Cada campo tem aqui uma funcao de validacao pura
(sem depender de HTTP/subprocess), facil de testar isoladamente.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

MODEL_ALLOWLIST = {"tiny", "base", "small", "medium", "large-v3"}
DEVICE_ALLOWLIST = {"cpu", "cuda"}
MIN_CHUNK_SECONDS = 5
MAX_CHUNK_SECONDS = 1800
MIN_FREE_BYTES = 200 * 1024 * 1024  # 200 MB — abaixo disso, recusar iniciar a reuniao
MAX_TITLE_LENGTH = 200
MAX_OUTPUT_LENGTH = 200
DEFAULT_OUTPUT_NAME = "transcricao.md"

_MEETING_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,80}$")
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class ValidationError(ValueError):
    """Entrada recebida da API nao passou na validacao."""


def validate_model(value) -> str:
    if not isinstance(value, str) or value not in MODEL_ALLOWLIST:
        raise ValidationError(f"Modelo invalido. Use um de: {', '.join(sorted(MODEL_ALLOWLIST))}.")
    return value


def validate_device(value) -> str:
    if not isinstance(value, str) or value not in DEVICE_ALLOWLIST:
        raise ValidationError(f"Dispositivo invalido. Use um de: {', '.join(sorted(DEVICE_ALLOWLIST))}.")
    return value


def validate_language(value) -> str:
    if not isinstance(value, str):
        raise ValidationError("Idioma invalido.")
    value = value.strip().lower()
    if value == "auto":
        return "auto"
    if not (2 <= len(value) <= 5) or not value.replace("-", "").isalpha():
        raise ValidationError("Codigo de idioma invalido (ex.: pt, en, auto).")
    return value


def validate_chunk_seconds(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValidationError("chunk_seconds invalido.")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValidationError("chunk_seconds precisa ser um numero inteiro.") from None
    if isinstance(value, float) and value != parsed:
        raise ValidationError("chunk_seconds precisa ser um numero inteiro.")
    if not (MIN_CHUNK_SECONDS <= parsed <= MAX_CHUNK_SECONDS):
        raise ValidationError(
            f"chunk_seconds precisa estar entre {MIN_CHUNK_SECONDS} e {MAX_CHUNK_SECONDS}."
        )
    return parsed


def validate_title(value) -> str:
    if value is None:
        return "Transcricao de reuniao"
    if not isinstance(value, str):
        raise ValidationError("Titulo invalido.")
    value = value.strip()
    if not value:
        return "Transcricao de reuniao"
    if len(value) > MAX_TITLE_LENGTH:
        raise ValidationError(f"Titulo muito longo (maximo {MAX_TITLE_LENGTH} caracteres).")
    return value


def validate_output_filename(value, base_dir: Path, default: str = DEFAULT_OUTPUT_NAME) -> Path:
    """Aceita so um NOME de arquivo (sem separadores de diretorio) e devolve
    o caminho absoluto dentro de `base_dir`, ja confirmado com `resolve()`.
    Rejeita qualquer tentativa de path traversal (`../`, `..\\`), path
    absoluto, nomes vazios/reservados pelo Windows, ou tipos inesperados.
    """
    if value is None:
        name = default
    else:
        if not isinstance(value, str):
            raise ValidationError("output invalido.")
        name = value.strip()
        if not name:
            name = default

    if len(name) > MAX_OUTPUT_LENGTH:
        raise ValidationError(f"Nome de arquivo muito longo (maximo {MAX_OUTPUT_LENGTH} caracteres).")

    # Qualquer separador (POSIX ou Windows) ou componente "."/".." derruba a
    # validacao aqui, ainda na string ORIGINAL — Path(name).name normalizaria
    # algo como "a/../b" silenciosamente para "b", entao nao da pra confiar
    # nisso sozinho como defesa.
    if "/" in name or "\\" in name or name in (".", "..") or name.startswith("."):
        raise ValidationError("Nome de arquivo invalido: use apenas um nome simples, sem caminhos.")

    stem = Path(name).stem.upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        raise ValidationError("Nome de arquivo reservado pelo sistema operacional.")

    if not name.lower().endswith(".md"):
        name = f"{name}.md"

    base_resolved = base_dir.resolve()
    candidate = (base_resolved / name).resolve()
    # defesa em profundidade: mesmo com a checagem de string acima, confirma
    # que o resultado final continua sendo um filho direto de base_dir.
    if candidate.parent != base_resolved:
        raise ValidationError("Nome de arquivo invalido.")
    return candidate


def validate_meeting_id(value) -> str:
    if not isinstance(value, str) or not _MEETING_ID_RE.match(value):
        raise ValidationError("Identificador de reuniao invalido.")
    return value


def validate_meetings_root_path(value) -> Path:
    """Validacao pura (sem tocar disco) do texto de um caminho de pasta
    escolhido pelo usuario -- confirma que e uma string nao vazia e resolve
    para um Path absoluto. Diferente de `validate_output_filename`, aqui o
    usuario ESCOLHE a raiz: nao ha "diretorio autorizado" pra confinar
    contra, porque essa raiz e o proprio diretorio autorizado dali em
    diante. A checagem de saude (existe/grava/tem espaco) e separada, em
    `check_folder_health`, porque essa sim precisa tocar o disco.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Escolha uma pasta valida.")
    try:
        path = Path(value).expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise ValidationError(f"Caminho invalido: {exc}") from None
    return path


@dataclass
class FolderHealth:
    ok: bool
    message: str
    free_bytes: Optional[int] = None


def check_folder_health(
    path: Path,
    min_free_bytes: int = MIN_FREE_BYTES,
    write_probe: Optional[Callable[[Path], None]] = None,
) -> FolderHealth:
    """Checklist antes de habilitar gravar numa pasta (secao 8 da missao):
    existe, e realmente uma pasta, tem espaco livre suficiente, e da pra
    criar um arquivo nela de verdade (nao so checar permissao "no papel" --
    ACLs do Windows sao traicoeiras o suficiente pra so confiar num teste
    real de escrita).

    `write_probe` existe so pra teste: por padrao escreve e apaga um
    arquivo temporario de verdade dentro de `path`.
    """
    if not isinstance(path, Path):
        return FolderHealth(False, "Caminho invalido.")
    if not path.exists():
        return FolderHealth(False, f"A pasta “{path}” nao existe.")
    if not path.is_dir():
        return FolderHealth(False, f"“{path}” nao e uma pasta.")

    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        return FolderHealth(False, f"Nao foi possivel verificar o espaco em disco: {exc}")

    if usage.free < min_free_bytes:
        free_mb = usage.free / (1024 * 1024)
        return FolderHealth(
            False,
            f"Pouco espaco disponivel no disco (livre: {free_mb:.0f} MB). "
            "Escolha outro local antes de iniciar a reuniao.",
            usage.free,
        )

    probe = write_probe or _default_write_probe
    try:
        probe(path)
    except OSError:
        return FolderHealth(
            False, f"Nao foi possivel escrever em “{path}”. Verifique as permissoes.", usage.free
        )

    return FolderHealth(True, "OK", usage.free)


def _default_write_probe(path: Path) -> None:
    probe_path = path / f".meeting_transcriber_write_test_{os.getpid()}.tmp"
    probe_path.write_text("ok", encoding="utf-8")
    probe_path.unlink()

"""Configuracoes locais do aplicativo (nao confundir com metadata.json de uma
reuniao especifica — isto aqui e config do app inteiro, hoje so qual pasta
usar como raiz de todas as reunioes). Sempre local: nunca em servico externo.

Fica de proposito FORA da pasta de reunioes escolhida pelo usuario (ela pode
mudar, estar num disco removivel, etc.) — quem chama decide onde o arquivo de
settings mora (ver `webui.py`, que usa uma pasta fixa dentro do projeto).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SETTINGS_FILE_NAME = "settings.json"


def default_meetings_root() -> Path:
    """Pasta sugerida na primeira execucao, antes do usuario escolher a
    dele: Documents/Reunioes, um lugar obvio de achar no Explorador de
    Arquivos — bem melhor que uma pasta escondida dentro do projeto."""
    return Path.home() / "Documents" / "Reunioes"


def load(settings_path: Path) -> dict:
    if not settings_path.exists():
        return {}
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save(settings_path: Path, data: dict) -> None:
    """Escrita atomica (tmp file + os.replace), mesmo padrao usado em
    session.py — settings.json nunca deve ficar corrompido pela metade."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = settings_path.with_name(settings_path.name + f".tmp-{os.getpid()}")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, settings_path)


def get_meetings_root(settings_path: Path) -> Path:
    data = load(settings_path)
    raw = data.get("meetings_root")
    if raw:
        return Path(raw)
    return default_meetings_root()


def set_meetings_root(settings_path: Path, new_root: Path) -> None:
    data = load(settings_path)
    data["meetings_root"] = str(new_root)
    save(settings_path, data)

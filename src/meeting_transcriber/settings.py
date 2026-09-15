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
import time
from pathlib import Path
from typing import List, Optional

SETTINGS_FILE_NAME = "settings.json"


def _normalize_root(raw) -> str:
    """Normaliza um caminho de raiz pra comparacao/dedupe. Nunca precisa do
    caminho existir (`resolve()` sem strict) -- uma raiz num disco removivel
    desconectado ainda precisa normalizar sem lancar excecao."""
    return str(Path(raw).expanduser().resolve())


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


def _replace_with_retry(src: Path, dst: Path, attempts: int = 5, delay: float = 0.05) -> None:
    """`os.replace()` no Windows pode falhar transitoriamente logo apos o
    destino ser criado/escrito (ex.: antivirus/indexador segurando um
    handle nele por uma fracao de segundo) -- observado na pratica durante
    esta fase, num teste com varias reunioes/escritas concorrentes.
    Algumas tentativas com um atraso minimo resolvem isso sem mascarar uma
    falha real (permissao de verdade, disco cheio): se todas as tentativas
    falharem, a excecao original ainda propaga."""
    last_exc: Optional[OSError] = None
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def save(settings_path: Path, data: dict) -> None:
    """Escrita atomica (tmp file + os.replace), mesmo padrao usado em
    session.py — settings.json nunca deve ficar corrompido pela metade."""
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = settings_path.with_name(settings_path.name + f".tmp-{os.getpid()}")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    _replace_with_retry(tmp_path, settings_path)


def get_meetings_root(settings_path: Path) -> Path:
    data = load(settings_path)
    raw = data.get("meetings_root")
    if raw:
        return Path(raw)
    return default_meetings_root()


def set_meetings_root(settings_path: Path, new_root: Path) -> None:
    """Troca a raiz ativa E registra ela na lista de raizes conhecidas
    (deduplicada, normalizada) -- e assim que `get_known_meeting_roots`
    consegue, mais tarde, procurar reunioes interrompidas deixadas numa
    raiz anterior sem precisar varrer o computador inteiro: so raizes que
    o usuario escolheu explicitamente algum dia entram nessa lista."""
    data = load(settings_path)
    normalized_new = _normalize_root(new_root)

    known_normalized: List[str] = []
    seen = set()
    for raw in data.get("known_meeting_roots") or []:
        try:
            norm = _normalize_root(raw)
        except (OSError, RuntimeError, ValueError):
            continue
        if norm not in seen:
            seen.add(norm)
            known_normalized.append(norm)
    if normalized_new not in seen:
        known_normalized.append(normalized_new)

    data["meetings_root"] = normalized_new
    data["known_meeting_roots"] = known_normalized
    save(settings_path, data)


def get_known_meeting_roots(settings_path: Path) -> List[Path]:
    """Todas as raizes que o usuario ja usou (mais a raiz ativa atual e/ou
    o padrao, garantidos presentes), deduplicadas e normalizadas. Nao
    verifica se a pasta existe/esta acessivel -- isso e responsabilidade
    de quem consome a lista (uma raiz desconectada nao pode quebrar quem
    chama)."""
    data = load(settings_path)
    candidates = list(data.get("known_meeting_roots") or [])
    current = data.get("meetings_root")
    candidates.append(current if current else str(default_meetings_root()))

    result: List[Path] = []
    seen = set()
    for raw in candidates:
        try:
            norm = _normalize_root(raw)
        except (OSError, RuntimeError, ValueError):
            continue
        if norm not in seen:
            seen.add(norm)
            result.append(Path(norm))
    return result


def forget_meeting_root(settings_path: Path, root) -> bool:
    """Remove uma raiz da lista de raizes conhecidas -- nunca apaga nenhum
    arquivo, so o registro. Recusa remover a raiz ATUALMENTE ativa (o
    usuario precisa trocar de raiz antes). Devolve True se algo foi
    removido."""
    data = load(settings_path)
    try:
        target = _normalize_root(root)
    except (OSError, RuntimeError, ValueError):
        return False

    current = data.get("meetings_root")
    if current:
        try:
            if _normalize_root(current) == target:
                return False
        except (OSError, RuntimeError, ValueError):
            pass

    known = data.get("known_meeting_roots") or []
    new_known = []
    removed = False
    for raw in known:
        try:
            norm = _normalize_root(raw)
        except (OSError, RuntimeError, ValueError):
            continue
        if norm == target:
            removed = True
            continue
        new_known.append(norm)

    if not removed:
        return False
    data["known_meeting_roots"] = new_known
    save(settings_path, data)
    return True


# Preferencias de audio (Fase C, secao "Configuracoes"): ultimo microfone,
# ultimo dispositivo de saida, e se cada fonte deve vir habilitada por
# padrao na proxima reuniao.
DEFAULT_AUDIO_PREFERENCES = {
    "capture_system": True,
    "capture_microphone": False,
    "system_device_id": None,
    "microphone_device_id": None,
}


def get_audio_preferences(settings_path: Path) -> dict:
    """Preferencias salvas, com os padroes preenchidos pra qualquer chave
    ausente/nunca salva. Nao valida se o dispositivo salvo ainda existe --
    isso e responsabilidade de quem VAI USAR a preferencia (webui.py, na
    hora de iniciar uma gravacao ou popular a UI), nunca de quem le/grava
    a configuracao."""
    data = load(settings_path)
    prefs = dict(DEFAULT_AUDIO_PREFERENCES)
    stored = data.get("audio_preferences")
    if isinstance(stored, dict):
        for key in DEFAULT_AUDIO_PREFERENCES:
            if key in stored:
                prefs[key] = stored[key]
    return prefs


def set_audio_preferences(settings_path: Path, **updates) -> dict:
    """Atualiza so as chaves passadas (demais preferencias existentes sao
    preservadas). Chaves desconhecidas sao ignoradas silenciosamente --
    isto e um merge parcial controlado, nao uma substituicao total."""
    data = load(settings_path)
    prefs = dict(DEFAULT_AUDIO_PREFERENCES)
    stored = data.get("audio_preferences")
    if isinstance(stored, dict):
        for key in DEFAULT_AUDIO_PREFERENCES:
            if key in stored:
                prefs[key] = stored[key]
    for key, value in updates.items():
        if key in DEFAULT_AUDIO_PREFERENCES:
            prefs[key] = value
    data["audio_preferences"] = prefs
    save(settings_path, data)
    return prefs

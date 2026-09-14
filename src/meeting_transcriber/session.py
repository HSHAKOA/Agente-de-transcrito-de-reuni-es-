"""Modelo de sessao (reuniao) persistente em disco.

Cada reuniao guarda seu estado em `data/meetings/<meeting_id>/`:

    metadata.json   dados que nao mudam depois de criados (titulo, modelo, ...)
    state.json      estado mutavel (status, contadores, lista de chunks),
                     escrito de forma atomica a cada mudanca
    chunks/         os .wav de cada bloco gravado

Guardar isso em disco (em vez de so na memoria do processo) e o que permite
detectar, na proxima inicializacao do app, uma reuniao que ficou "presa" em
`recording`/`processing` porque o processo anterior morreu sem finalizar —
e recuperar (reprocessar) o que ainda nao foi transcrito, sem apagar nada.

Este modulo nao sabe nada de audio/Whisper: so persiste e le estado. Quem
chama (cli.py) decide quando invocar cada `mark_*`.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

STATUS_CREATED = "created"
STATUS_RECORDING = "recording"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_INTERRUPTED = "interrupted"
STATUS_FAILED = "failed"

# Estados em que uma sessao so deveria existir enquanto ha um processo vivo
# cuidando dela. Se encontrados num scan de inicializacao, o processo anterior
# morreu sem chegar a marcar completed/failed/interrupted.
LIVE_STATUSES = {STATUS_RECORDING, STATUS_PROCESSING}

CHUNK_RECORDED = "recorded"
CHUNK_TRANSCRIBED = "transcribed"
CHUNK_FAILED = "failed"

_MEETING_ID_RE = re.compile(r"^[0-9A-Za-z_-]{1,80}$")

# caracteres proibidos em nomes de arquivo/pasta no Windows (o SO mais
# restritivo dos tres suportados) — filtrar por esses cobre POSIX de graca.
_INVALID_FOLDER_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_title_for_folder(title: str, max_length: int = 50) -> str:
    """Transforma um titulo de reuniao (texto livre, digitado pelo usuario)
    num pedaco de nome de pasta seguro: remove caracteres invalidos no
    Windows, troca espacos por hifen, tira pontos/espacos/hifens das pontas
    (o Windows rejeita nomes terminados em ponto ou espaco), e evita nomes
    reservados do SO. Nunca devolve vazio."""
    if not isinstance(title, str):
        title = ""
    cleaned = _INVALID_FOLDER_CHARS_RE.sub("", title).strip()
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = cleaned.strip(". -")
    cleaned = cleaned[:max_length].strip(". -")
    if not cleaned or cleaned.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = "Reuniao"
    return cleaned


def new_meeting_id(title: Optional[str] = None) -> str:
    """Id unico o suficiente (timestamp + sufixo aleatorio) e seguro pra
    usar como nome de pasta em qualquer SO.

    Sem `title`: mantem o formato compacto/opaco original
    (`AAAAMMDD-HHMMSS-xxxxxx`), usado por --resume e por quem so precisa de
    um identificador (sem se importar com legibilidade no Explorador de
    Arquivos). Com `title`: produz um nome de pasta legivel
    (`AAAA-MM-DD_HHMM_Titulo-Sanitizado_xxxxxx`) -- e o que o painel usa,
    ja que o usuario agora escolhe a pasta-raiz e navega essas pastas
    diretamente no SO. Em ambos os casos, o sufixo aleatorio de 6 hex
    garante unicidade mesmo com o mesmo titulo no mesmo minuto; e o
    resultado so contem [0-9A-Za-z_-], entao sempre bate com
    `is_valid_meeting_id`.
    """
    suffix = secrets.token_hex(3)
    if title:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        safe_title = sanitize_title_for_folder(title)
        return f"{stamp}_{safe_title}_{suffix}"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{suffix}"


def is_valid_meeting_id(value: str) -> bool:
    return isinstance(value, str) and bool(_MEETING_ID_RE.match(value))


def _now_iso() -> str:
    # microsegundos, nao segundos: duas reunioes criadas dentro do mesmo
    # segundo (comum em testes, e possivel no uso real) precisam continuar
    # ordenaveis por created_at em list_sessions().
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="microseconds")


def _atomic_write_json(path: Path, data: dict) -> None:
    """Escreve JSON de forma atomica: grava num arquivo temporario no mesmo
    diretorio e substitui o arquivo final com `os.replace` (atomico em POSIX
    e Windows). Assim o state.json nunca fica corrompido/pela metade se o
    processo morrer no meio de uma escrita.
    """
    tmp_path = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)


@dataclass
class ChunkRecord:
    index: int
    path: str  # relativo ao meeting_dir
    start_offset_seconds: float
    duration_seconds: float
    status: str = CHUNK_RECORDED
    retry_count: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "ChunkRecord":
        return ChunkRecord(
            index=data["index"],
            path=data["path"],
            start_offset_seconds=data.get("start_offset_seconds", 0.0),
            duration_seconds=data.get("duration_seconds", 0.0),
            status=data.get("status", CHUNK_RECORDED),
            retry_count=data.get("retry_count", 0),
            error=data.get("error"),
        )


class MeetingSession:
    """Gerencia metadata.json + state.json de uma reuniao em
    `<base_dir>/<meeting_id>/`. Toda mudanca de estado e persistida na hora
    (escrita atomica) — nao ha estado "so em memoria" que se perderia num
    crash do processo.
    """

    def __init__(self, meeting_dir: Path):
        self.meeting_dir = meeting_dir
        self.chunks_dir = meeting_dir / "chunks"
        self.metadata_path = meeting_dir / "metadata.json"
        self.state_path = meeting_dir / "state.json"
        self._lock = threading.Lock()
        self._state: dict = {}
        self._metadata: dict = {}

    @classmethod
    def create(
        cls,
        base_dir: Path,
        title: str,
        model: str,
        language: Optional[str],
        device: str,
        transcript_path: Optional[Path] = None,
        meeting_id: Optional[str] = None,
        system_audio_device: Optional[str] = None,
        microphone_device: Optional[str] = None,
    ) -> "MeetingSession":
        meeting_id = meeting_id or new_meeting_id()
        meeting_dir = base_dir / meeting_id
        meeting_dir.mkdir(parents=True, exist_ok=True)
        (meeting_dir / "chunks").mkdir(parents=True, exist_ok=True)

        session = cls(meeting_dir)
        created_at = _now_iso()
        session._metadata = {
            "meeting_id": meeting_id,
            "title": title,
            "model": model,
            "language": language,
            "device": device,
            "created_at": created_at,
            "transcript_path": str(transcript_path) if transcript_path else None,
            # raiz escolhida pelo usuario e pasta desta reuniao especifica --
            # gravados aqui pra "Abrir pasta" e pra tela de Arquivos nao
            # dependerem de reconstruir o caminho a partir de outra fonte.
            "root_directory": str(base_dir.resolve()),
            "meeting_directory": str(meeting_dir.resolve()),
            # ainda nao usados (captura hoje e so loopback do sistema) --
            # reservados pra Fase C (microfone + selecao de dispositivo),
            # ja no formato final pra nao exigir migracao de schema depois.
            "system_audio_device": system_audio_device,
            "microphone_device": microphone_device,
        }
        _atomic_write_json(session.metadata_path, session._metadata)

        session._state = {
            "meeting_id": meeting_id,
            "title": title,
            "status": STATUS_CREATED,
            "created_at": created_at,
            "started_at": None,
            "finished_at": None,
            "chunk_count": 0,
            "chunks_recorded": 0,
            "chunks_transcribed": 0,
            "duration": 0.0,
            "model": model,
            "language": language,
            "device": device,
            "error": None,
            "chunks": [],
        }
        session._save_state()
        return session

    @classmethod
    def load(cls, meeting_dir: Path) -> "MeetingSession":
        session = cls(meeting_dir)
        session._metadata = json.loads(session.metadata_path.read_text(encoding="utf-8"))
        state = json.loads(session.state_path.read_text(encoding="utf-8"))
        state.setdefault("chunks", [])
        session._state = state
        return session

    def _save_state(self) -> None:
        _atomic_write_json(self.state_path, self._state)

    @property
    def state(self) -> dict:
        with self._lock:
            return dict(self._state)

    @property
    def metadata(self) -> dict:
        return dict(self._metadata)

    def mark_recording(self) -> None:
        with self._lock:
            self._state["status"] = STATUS_RECORDING
            self._state["started_at"] = _now_iso()
            self._save_state()

    def mark_chunk_recorded(
        self, index: int, path: Path, start_offset_seconds: float, duration_seconds: float
    ) -> None:
        with self._lock:
            try:
                # sempre com "/" (as_posix), independente do SO: state.json
                # e um arquivo de dados, nao deveria carregar barras
                # invertidas so porque foi gravado no Windows.
                rel_path = path.relative_to(self.meeting_dir).as_posix()
            except ValueError:
                rel_path = path.as_posix()
            record = ChunkRecord(
                index=index,
                path=rel_path,
                start_offset_seconds=start_offset_seconds,
                duration_seconds=duration_seconds,
            )
            self._state["chunks"].append(record.to_dict())
            self._state["chunk_count"] += 1
            self._state["chunks_recorded"] += 1
            self._save_state()

    def mark_chunk_transcribed(self, index: int, end_offset_seconds: float) -> None:
        with self._lock:
            for c in self._state["chunks"]:
                if c["index"] == index:
                    c["status"] = CHUNK_TRANSCRIBED
                    c["error"] = None
                    break
            self._state["chunks_transcribed"] += 1
            self._state["duration"] = max(self._state.get("duration", 0.0), end_offset_seconds)
            self._state["status"] = STATUS_PROCESSING
            self._save_state()

    def mark_chunk_failed(self, index: int, error: str) -> None:
        with self._lock:
            for c in self._state["chunks"]:
                if c["index"] == index:
                    c["status"] = CHUNK_FAILED
                    c["error"] = error
                    c["retry_count"] += 1
                    break
            self._save_state()

    def mark_completed(self) -> None:
        with self._lock:
            # qualquer chunk que nao seja "transcribed" ainda esta pendente
            # -- seja porque falhou, seja porque nunca chegou a ser tentado
            # (ex.: --resume interrompido no meio, antes de tentar todos).
            # So checar CHUNK_FAILED deixaria esse segundo caso passar como
            # "completed" incorretamente.
            still_pending = [c for c in self._state["chunks"] if c["status"] != CHUNK_TRANSCRIBED]
            self._state["status"] = STATUS_INTERRUPTED if still_pending else STATUS_COMPLETED
            self._state["finished_at"] = _now_iso()
            self._save_state()

    def mark_failed(self, error: str) -> None:
        with self._lock:
            self._state["status"] = STATUS_FAILED
            self._state["error"] = error
            self._state["finished_at"] = _now_iso()
            self._save_state()

    def pending_chunks(self) -> List[ChunkRecord]:
        """Chunks gravados mas ainda sem transcricao bem-sucedida (novos ou
        que falharam antes) — usados pelo modo `--resume`."""
        with self._lock:
            return [
                ChunkRecord.from_dict(c) for c in self._state["chunks"] if c["status"] != CHUNK_TRANSCRIBED
            ]


def mark_interrupted_sessions(base_dir: Path) -> List[dict]:
    """Varre `base_dir` procurando sessoes travadas num estado "ao vivo"
    (recording/processing) — sinal de que o processo anterior morreu sem
    marcar completed/failed. Marca essas sessoes como "interrupted" (sem
    apagar nenhum chunk) e devolve os estados encontrados.

    Deve rodar uma unica vez, na inicializacao do painel/app — nunca durante
    uma sessao ativa, senao marcaria a propria sessao em andamento.
    """
    if not base_dir.exists():
        return []

    recovered = []
    for meeting_dir in sorted(p for p in base_dir.iterdir() if p.is_dir()):
        state_path = meeting_dir / "state.json"
        if not state_path.exists():
            continue
        try:
            session = MeetingSession.load(meeting_dir)
        except (json.JSONDecodeError, OSError, KeyError):
            continue
        if session.state.get("status") in LIVE_STATUSES:
            with session._lock:
                session._state["status"] = STATUS_INTERRUPTED
                session._save_state()
            recovered.append(session.state)
    return recovered


def list_sessions(base_dir: Path) -> List[dict]:
    """Lista o estado de todas as reunioes conhecidas (mais recente primeiro)."""
    if not base_dir.exists():
        return []
    sessions = []
    for meeting_dir in base_dir.iterdir():
        if not meeting_dir.is_dir():
            continue
        state_path = meeting_dir / "state.json"
        if not state_path.exists():
            continue
        try:
            sessions.append(MeetingSession.load(meeting_dir).state)
        except (json.JSONDecodeError, OSError, KeyError):
            continue
    sessions.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    return sessions

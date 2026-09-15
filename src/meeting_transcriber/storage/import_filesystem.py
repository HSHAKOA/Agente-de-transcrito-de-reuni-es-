"""Importa reunioes existentes no filesystem (metadata.json/state.json/
transcript.md, ver session.py) pro indice SQLite pesquisavel (Fase E,
secao E.7). Idempotente: reimportar a mesma reuniao so atualiza os
campos (`upsert_meeting`/`replace_segments`), nunca duplica. Nunca
modifica nenhum arquivo original -- e uma leitura, nao uma migracao
destrutiva.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from ..session import MeetingSession
from .repository import MeetingRepository

logger = logging.getLogger("meeting_transcriber.storage.import")

_SEGMENT_RE = re.compile(r"^\*\*\[(\d{2}):(\d{2}):(\d{2})\]\*\*\s?(.*)$")

# Fase H (versao "leve", sem diarizacao de verdade): rotulo de speaker so
# pelo CANAL de origem -- "Você" quando o microfone estava habilitado,
# "Áudio da reunião" quando so o sistema. NUNCA um nome de pessoa: a
# missao e explicita que inventar "João"/"Maria" sem evidencia real e
# proibido (secao H.5).
SPEAKER_LABEL_MICROPHONE = "Você"
SPEAKER_LABEL_SYSTEM = "Áudio da reunião"
SPEAKER_LABEL_MIXED = "Reunião"


@dataclass
class ImportResult:
    meeting_id: str
    ok: bool
    message: str = "OK"
    segments_imported: int = 0


def _timestamp_to_seconds(hours: str, minutes: str, seconds: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds)


def parse_markdown_segments(text: str) -> List[dict]:
    """Extrai `(start_seconds, text)` de cada linha `**[HH:MM:SS]** texto`
    escrita por `MarkdownWriter.append_segments`. `end_seconds` e
    aproximado pelo INICIO do proximo segmento (o .md nunca guardou o fim
    de cada um) -- limitacao documentada em `docs/DATABASE.md`, so afeta
    reunioes importadas do formato legado (novas reunioes, uma vez
    gravadas direto no banco numa fase futura, teriam o fim exato)."""
    starts_and_text = []
    for line in text.splitlines():
        match = _SEGMENT_RE.match(line.strip())
        if match:
            h, m, s, seg_text = match.groups()
            starts_and_text.append((_timestamp_to_seconds(h, m, s), seg_text.strip()))

    segments = []
    for i, (start, seg_text) in enumerate(starts_and_text):
        end = starts_and_text[i + 1][0] if i + 1 < len(starts_and_text) else start
        segments.append({"start_seconds": float(start), "end_seconds": float(end), "text": seg_text})
    return segments


def _speaker_label(metadata: dict) -> Optional[str]:
    mic_on = bool(metadata.get("microphone_enabled"))
    sys_on = bool(metadata.get("system_audio_enabled"))
    if mic_on and sys_on:
        return SPEAKER_LABEL_MIXED
    if mic_on:
        return SPEAKER_LABEL_MICROPHONE
    if sys_on:
        return SPEAKER_LABEL_SYSTEM
    return None


def import_meeting(repo: MeetingRepository, meeting_dir: Path) -> ImportResult:
    meeting_id = meeting_dir.name
    try:
        if not (meeting_dir / "state.json").exists():
            return ImportResult(meeting_id, False, "state.json ausente -- nao e uma pasta de reuniao valida")

        session = MeetingSession.load(meeting_dir)
        metadata = session.metadata
        state = session.state

        segments_data: List[dict] = []
        transcript_path_str = metadata.get("transcript_path")
        transcript_path = Path(transcript_path_str) if transcript_path_str else None
        if transcript_path is None or not transcript_path.exists():
            # metadata.json pode apontar pra um caminho absoluto que nao
            # existe mais (pasta movida, backup restaurado noutra maquina)
            # -- antes de desistir, tenta o local padrao (transcript.md
            # dentro da PROPRIA pasta da reuniao, que e onde start_transcriber
            # sempre grava). Nunca reescreve metadata.json com esse fallback:
            # e so uma tentativa de leitura, nao uma migracao.
            fallback_path = meeting_dir / "transcript.md"
            if fallback_path.exists():
                transcript_path = fallback_path
        if transcript_path is not None and transcript_path.exists():
            raw = transcript_path.read_text(encoding="utf-8", errors="replace")
            segments_data = parse_markdown_segments(raw)

        label = _speaker_label(metadata)
        if label:
            for seg in segments_data:
                seg["speaker_label"] = label

        chunks = state.get("chunks") or []
        duration = state.get("duration")
        if not duration and chunks:
            duration = max(c.get("start_offset_seconds", 0) + c.get("duration_seconds", 0) for c in chunks)

        repo.upsert_meeting(
            {
                "id": meeting_id,
                "title": metadata.get("title") or meeting_id,
                "status": state.get("status", "unknown"),
                "started_at": state.get("started_at") or metadata.get("created_at"),
                "finished_at": state.get("finished_at"),
                "duration_seconds": duration,
                "root_directory": metadata.get("root_directory"),
                "meeting_directory": str(meeting_dir.resolve()),
                "language": metadata.get("language"),
                "model": metadata.get("model"),
                "system_audio_enabled": metadata.get("system_audio_enabled"),
                "system_device_id": metadata.get("system_device_id"),
                "system_device_name": metadata.get("system_device_name"),
                "microphone_enabled": metadata.get("microphone_enabled"),
                "microphone_device_id": metadata.get("microphone_device_id"),
                "microphone_device_name": metadata.get("microphone_device_name"),
            }
        )
        repo.replace_segments(meeting_id, segments_data)
        return ImportResult(meeting_id, True, "OK", segments_imported=len(segments_data))
    except Exception as exc:
        logger.exception("Falha ao importar a reuniao em %s", meeting_dir)
        return ImportResult(meeting_id, False, str(exc))


def import_all(repo: MeetingRepository, roots: List[Path]) -> List[ImportResult]:
    """Varre cada raiz conhecida por subpastas de reuniao (identificadas
    por ter `state.json`) e importa cada uma. Uma reuniao com erro nunca
    impede as demais de serem importadas (missao, secao E.7: "registrar
    erro por reuniao; continuar com as demais")."""
    results = []
    seen_ids = set()
    for root in roots:
        if not root.exists():
            continue
        for entry in sorted(p for p in root.iterdir() if p.is_dir()):
            if entry.name in seen_ids:
                continue  # mesmo meeting_id em duas raizes (improvavel, mas nao reimporta)
            if (entry / "state.json").exists():
                seen_ids.add(entry.name)
                results.append(import_meeting(repo, entry))
    return results

"""Entidade `Schedule` (agendamento de gravacao) e sua sub-entidade `Run`
(uma ocorrencia concreta desse agendamento -- uma reuniao recorrente gera
varios `Run`s ao longo do tempo, cada um com seu proprio `meeting_id`).

Deliberadamente NAO duplica dados que ja existem em `session.py`
(`MeetingSession`): um `Run` so guarda o VINCULO entre um agendamento e a
reuniao que ele disparou (`meeting_id`, horarios previstos vs reais,
status do disparo em si) -- os detalhes da gravacao/transcricao continuam
inteiramente em `metadata.json`/`state.json` da propria reuniao.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

# -- status do AGENDAMENTO (a regra em si) ----------------------------------
# Reflete o ciclo de vida da ocorrencia ATUAL/PROXIMA. Um agendamento
# recorrente volta para SCHEDULED apos completar uma ocorrencia, pronto
# para a proxima -- ver `engine.py`.
STATUS_SCHEDULED = "scheduled"
STATUS_PREPARING = "preparing"
STATUS_RECORDING = "recording"
STATUS_FINISHING = "finishing"
STATUS_COMPLETED = "completed"
STATUS_MISSED = "missed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

ALL_STATUSES = {
    STATUS_SCHEDULED, STATUS_PREPARING, STATUS_RECORDING, STATUS_FINISHING,
    STATUS_COMPLETED, STATUS_MISSED, STATUS_FAILED, STATUS_CANCELLED,
}

# um agendamento nesses estados nao esta "em aberto" -- nao aceita
# transicoes automaticas do motor (ja terminou aquela ocorrencia, ou foi
# cancelado pelo usuario).
TERMINAL_RUN_STATUSES = {STATUS_COMPLETED, STATUS_MISSED, STATUS_FAILED, STATUS_CANCELLED}

# tipos de recorrencia suportados (missao, secao 16) -- estrutura simples de
# proposito, nunca um parser de expressao de calendario.
RECURRENCE_ONCE = "once"
RECURRENCE_DAILY = "daily"
RECURRENCE_WEEKDAYS = "weekdays"  # segunda a sexta
RECURRENCE_WEEKLY = "weekly"  # um unico dia da semana, repetido
RECURRENCE_CUSTOM_DAYS = "custom_days"  # conjunto arbitrario de dias da semana

ALL_RECURRENCE_TYPES = {
    RECURRENCE_ONCE, RECURRENCE_DAILY, RECURRENCE_WEEKDAYS, RECURRENCE_WEEKLY, RECURRENCE_CUSTOM_DAYS,
}


def new_schedule_id() -> str:
    return f"sch_{secrets.token_hex(6)}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.fromisoformat(value)


@dataclass
class Recurrence:
    """Regra de recorrencia estruturada (nunca uma string de cron/calendario
    livre). `days`: lista de inteiros 0=segunda .. 6=domingo (mesma
    convencao de `date.weekday()`), usado so por WEEKLY/CUSTOM_DAYS."""

    type: str = RECURRENCE_ONCE
    days: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"type": self.type, "days": list(self.days)}

    @classmethod
    def from_dict(cls, data: Optional[dict]) -> "Recurrence":
        if not data:
            return cls()
        return cls(type=data.get("type", RECURRENCE_ONCE), days=list(data.get("days") or []))


@dataclass
class ScheduleRun:
    """Uma ocorrencia concreta de um `Schedule` -- o que a missao chama de
    "reuniao gerada pela programacao". `occurrence_date` e a data (no
    timezone do agendamento) a que esta ocorrencia se refere; existe mesmo
    antes de qualquer gravacao comecar, pra permitir detectar "missed" e
    evitar disparo duplicado da MESMA ocorrencia."""

    occurrence_date: str  # "YYYY-MM-DD" no timezone do agendamento
    scheduled_start_at: str  # ISO 8601 UTC
    scheduled_end_at: str  # ISO 8601 UTC
    status: str = STATUS_SCHEDULED
    meeting_id: Optional[str] = None
    meeting_dir: Optional[str] = None
    actual_start_at: Optional[str] = None
    actual_end_at: Optional[str] = None
    ended_early: bool = False
    started_manually_early: bool = False
    error_message: Optional[str] = None
    preflight: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "occurrence_date": self.occurrence_date,
            "scheduled_start_at": self.scheduled_start_at,
            "scheduled_end_at": self.scheduled_end_at,
            "status": self.status,
            "meeting_id": self.meeting_id,
            "meeting_dir": self.meeting_dir,
            "actual_start_at": self.actual_start_at,
            "actual_end_at": self.actual_end_at,
            "ended_early": self.ended_early,
            "started_manually_early": self.started_manually_early,
            "error_message": self.error_message,
            "preflight": self.preflight,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduleRun":
        return cls(
            occurrence_date=data["occurrence_date"],
            scheduled_start_at=data["scheduled_start_at"],
            scheduled_end_at=data["scheduled_end_at"],
            status=data.get("status", STATUS_SCHEDULED),
            meeting_id=data.get("meeting_id"),
            meeting_dir=data.get("meeting_dir"),
            actual_start_at=data.get("actual_start_at"),
            actual_end_at=data.get("actual_end_at"),
            ended_early=bool(data.get("ended_early", False)),
            started_manually_early=bool(data.get("started_manually_early", False)),
            error_message=data.get("error_message"),
            preflight=data.get("preflight"),
        )


# quantas ocorrencias passadas manter em `history` -- so pra diagnostico
# (missao, secao 24), nunca cresce sem limite.
MAX_HISTORY_ENTRIES = 200


@dataclass
class Schedule:
    id: str
    title: str
    scheduled_date: str  # "YYYY-MM-DD": ancora (once: a data exata; recorrente: nao produz ocorrencia antes dela)
    start_time: str  # "HH:MM"
    end_time: str  # "HH:MM"
    timezone: str  # nome IANA, ex. "America/Sao_Paulo"
    meetings_root: str
    system_audio_enabled: bool = True
    system_device_id: Optional[str] = None
    microphone_enabled: bool = False
    microphone_device_id: Optional[str] = None
    transcription_model: str = "small"
    language: str = "pt"
    device: str = "cpu"
    chunk_seconds: int = 300
    recurrence: Recurrence = field(default_factory=Recurrence)
    status: str = STATUS_SCHEDULED
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    current_run: Optional[ScheduleRun] = None
    history: List[ScheduleRun] = field(default_factory=list)

    def is_open(self) -> bool:
        """Ainda aceita transicoes automaticas do motor -- False so quando o
        usuario cancelou o agendamento inteiro (`cancelled` no NIVEL do
        agendamento, nao de uma ocorrencia isolada)."""
        return self.status != STATUS_CANCELLED

    def push_history(self, run: ScheduleRun) -> None:
        self.history.append(run)
        if len(self.history) > MAX_HISTORY_ENTRIES:
            self.history = self.history[-MAX_HISTORY_ENTRIES:]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "scheduled_date": self.scheduled_date,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "timezone": self.timezone,
            "meetings_root": self.meetings_root,
            "system_audio_enabled": self.system_audio_enabled,
            "system_device_id": self.system_device_id,
            "microphone_enabled": self.microphone_enabled,
            "microphone_device_id": self.microphone_device_id,
            "transcription_model": self.transcription_model,
            "language": self.language,
            "device": self.device,
            "chunk_seconds": self.chunk_seconds,
            "recurrence": self.recurrence.to_dict(),
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_run_at": self.last_run_at,
            "next_run_at": self.next_run_at,
            "current_run": self.current_run.to_dict() if self.current_run else None,
            "history": [r.to_dict() for r in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Schedule":
        return cls(
            id=data["id"],
            title=data["title"],
            scheduled_date=data["scheduled_date"],
            start_time=data["start_time"],
            end_time=data["end_time"],
            timezone=data["timezone"],
            meetings_root=data["meetings_root"],
            system_audio_enabled=bool(data.get("system_audio_enabled", True)),
            system_device_id=data.get("system_device_id"),
            microphone_enabled=bool(data.get("microphone_enabled", False)),
            microphone_device_id=data.get("microphone_device_id"),
            transcription_model=data.get("transcription_model", "small"),
            language=data.get("language", "pt"),
            device=data.get("device", "cpu"),
            chunk_seconds=int(data.get("chunk_seconds", 300)),
            recurrence=Recurrence.from_dict(data.get("recurrence")),
            status=data.get("status", STATUS_SCHEDULED),
            created_at=data.get("created_at") or _now_iso(),
            updated_at=data.get("updated_at") or _now_iso(),
            last_run_at=data.get("last_run_at"),
            next_run_at=data.get("next_run_at"),
            current_run=ScheduleRun.from_dict(data["current_run"]) if data.get("current_run") else None,
            history=[ScheduleRun.from_dict(r) for r in (data.get("history") or [])],
        )

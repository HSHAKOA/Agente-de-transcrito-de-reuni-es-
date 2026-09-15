"""Operacoes de CRUD sobre agendamentos: validar, checar conflito, criar,
listar, editar, cancelar. Nada aqui dispara gravacao nenhuma -- isso e
trabalho do `engine.py` (o motor movido a tempo, que tambem cuida de
iniciar manualmente adiantado/apos um "missed", ja que essas acoes
precisam coordenar com o unico slot de gravacao ativa do painel).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from . import validation as sched_validation
from .conflicts import first_conflict_message
from .models import STATUS_CANCELLED, STATUS_FINISHING, STATUS_RECORDING, Schedule, new_schedule_id
from .store import ScheduleStore

ValidationError = sched_validation.ValidationError


def _validate_fields(body: dict) -> dict:
    """Valida todos os campos de um agendamento (criacao OU edicao) e
    devolve um dict ja normalizado, pronto pra montar/atualizar um
    `Schedule`. Nao toca o `ScheduleStore` nem checa conflito -- isso e
    responsabilidade de quem chama, que precisa saber o id (pra excluir a
    si mesmo da checagem de conflito numa edicao)."""
    title = sched_validation.validate_title(body.get("title"))
    scheduled_date = sched_validation.validate_date(body.get("scheduled_date"))
    start_time = sched_validation.validate_time(body.get("start_time"), "Horario de inicio")
    end_time = sched_validation.validate_time(body.get("end_time"), "Horario de fim")
    tz_name = sched_validation.validate_timezone(body.get("timezone") or local_timezone_name())
    sched_validation.validate_duration(scheduled_date, start_time, end_time, tz_name)
    meetings_root = sched_validation.validate_meetings_root(body.get("meetings_root"))
    recurrence = sched_validation.validate_recurrence(body.get("recurrence"))

    system_audio_enabled = bool(body.get("system_audio_enabled", True))
    microphone_enabled = bool(body.get("microphone_enabled", False))
    if not system_audio_enabled and not microphone_enabled:
        raise ValidationError("Selecione pelo menos uma fonte de audio (computador e/ou microfone).")

    return dict(
        title=title,
        scheduled_date=scheduled_date,
        start_time=start_time,
        end_time=end_time,
        timezone=tz_name,
        meetings_root=str(meetings_root),
        system_audio_enabled=system_audio_enabled,
        system_device_id=sched_validation.validate_device_id(body.get("system_device_id"), "Dispositivo de saida"),
        microphone_enabled=microphone_enabled,
        microphone_device_id=sched_validation.validate_device_id(body.get("microphone_device_id"), "Microfone"),
        transcription_model=sched_validation.validate_model(body.get("transcription_model") or "small"),
        language=sched_validation.validate_language(body.get("language") or "pt"),
        device=sched_validation.validate_device(body.get("device") or "cpu"),
        chunk_seconds=sched_validation.validate_chunk_seconds(body.get("chunk_seconds", 300)),
        recurrence=recurrence,
    )


def local_timezone_name() -> str:
    """Timezone local detectado do computador (missao, secao 2) -- usado so
    como PADRAO quando o cliente nao manda um explicito; a arquitetura
    inteira (recurrence.py, models.py) trabalha com qualquer timezone IANA
    valido, nunca fica presa a este."""
    try:
        import tzlocal

        return tzlocal.get_localzone_name()
    except Exception:
        return "UTC"  # nunca falha por causa disso -- pior caso, agendamento fica em UTC ate o usuario trocar


class ScheduleService:
    def __init__(self, store: ScheduleStore, now_fn=lambda: datetime.now(timezone.utc)):
        self._store = store
        self._now_fn = now_fn  # injetavel pra teste, mesmo raciocinio do Clock usado pelo engine

    def list_all(self) -> List[Schedule]:
        return self._store.list_all()

    def get(self, schedule_id: str) -> Optional[Schedule]:
        return self._store.get(schedule_id)

    def create(self, body: dict) -> Schedule:
        fields = _validate_fields(body)
        schedule = Schedule(id=new_schedule_id(), **fields)

        existing = [s for s in self._store.list_all() if s.is_open()]
        conflict_message = first_conflict_message(schedule, existing, self._now_fn())
        if conflict_message:
            raise ValidationError(conflict_message)

        self._store.save(schedule)
        return schedule

    def update(self, schedule_id: str, body: dict) -> Schedule:
        schedule = self._store.get(schedule_id)
        if schedule is None:
            raise ValidationError("Agendamento nao encontrado.")
        if schedule.current_run is not None and schedule.current_run.status in (STATUS_RECORDING, STATUS_FINISHING):
            raise ValidationError("Nao e possivel editar um agendamento com uma gravacao em andamento.")

        fields = _validate_fields(body)
        for key, value in fields.items():
            setattr(schedule, key, value)
        schedule.updated_at = self._now_fn().isoformat(timespec="microseconds")
        # muda os horarios/recorrencia -- a proxima ocorrencia precisa ser
        # recalculada do zero pelo engine, nao continuar apontando pra uma
        # janela que pode nem fazer mais sentido com os novos campos.
        schedule.current_run = None
        schedule.next_run_at = None

        existing = [s for s in self._store.list_all() if s.is_open() and s.id != schedule_id]
        conflict_message = first_conflict_message(schedule, existing, self._now_fn())
        if conflict_message:
            raise ValidationError(conflict_message)

        self._store.save(schedule)
        return schedule

    def cancel(self, schedule_id: str) -> Schedule:
        schedule = self._store.get(schedule_id)
        if schedule is None:
            raise ValidationError("Agendamento nao encontrado.")
        if schedule.current_run is not None and schedule.current_run.status in (STATUS_RECORDING, STATUS_FINISHING):
            raise ValidationError(
                "Ha uma gravacao em andamento para este agendamento. Pare a gravacao antes de cancelar."
            )
        if schedule.current_run is not None:
            schedule.current_run.status = STATUS_CANCELLED
            schedule.push_history(schedule.current_run)
            schedule.current_run = None
        schedule.status = STATUS_CANCELLED
        schedule.next_run_at = None
        schedule.updated_at = self._now_fn().isoformat(timespec="microseconds")
        self._store.save(schedule)
        return schedule

"""Validacao de entrada para agendamentos -- mesmo espirito de
`meeting_transcriber.validation` (funcoes puras, sem tocar disco/HTTP),
reaproveitando o que ja existe la para os campos que sao identicos
(modelo, device, idioma, pasta) em vez de duplicar as regras.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from .. import validation as base_validation
from .models import (
    ALL_RECURRENCE_TYPES,
    RECURRENCE_CUSTOM_DAYS,
    RECURRENCE_DAILY,
    RECURRENCE_ONCE,
    RECURRENCE_WEEKDAYS,
    RECURRENCE_WEEKLY,
    Recurrence,
)
from .recurrence import InvalidTimeZone, occurrence_window_for_date, resolve_zone

ValidationError = base_validation.ValidationError

MAX_TITLE_LENGTH = 200
MAX_DEVICE_ID_LENGTH = 200
MIN_DURATION_MINUTES = 1
MAX_DURATION_HOURS = 12  # duracao maxima razoavel (missao, secao 3) -- tambem rejeita "19:00 -> 18:00" no mesmo
                          # dia por construcao, ja que isso vira 23h ao ser interpretado como virada de meia-noite
MAX_SCHEDULE_DATE_YEARS_AHEAD = 2

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_WEEKDAY_NAMES_PT = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]


def validate_title(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Titulo do agendamento e obrigatorio.")
    value = value.strip()
    if len(value) > MAX_TITLE_LENGTH:
        raise ValidationError(f"Titulo muito longo (maximo {MAX_TITLE_LENGTH} caracteres).")
    return value


def validate_date(value) -> str:
    if not isinstance(value, str):
        raise ValidationError("Data invalida.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValidationError("Data invalida (use AAAA-MM-DD).") from None
    if parsed > date.today() + timedelta(days=365 * MAX_SCHEDULE_DATE_YEARS_AHEAD):
        raise ValidationError("Data muito distante no futuro.")
    return parsed.isoformat()


def validate_time(value, field_name: str = "Horario") -> str:
    if not isinstance(value, str) or not _HHMM_RE.match(value):
        raise ValidationError(f"{field_name} invalido (use HH:MM, 00:00-23:59).")
    return value


def validate_timezone(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Timezone e obrigatorio.")
    try:
        resolve_zone(value)
    except InvalidTimeZone as exc:
        raise ValidationError(str(exc)) from None
    return value


def validate_duration(scheduled_date: str, start_time: str, end_time: str, timezone_name: str) -> None:
    """So pode ser chamado depois de `validate_date`/`validate_time`/
    `validate_timezone` (usa os 3 pra calcular a duracao de verdade,
    incluindo a virada de meia-noite -- ver `recurrence.occurrence_window_for_date`)."""
    tz = resolve_zone(timezone_name)
    day = date.fromisoformat(scheduled_date)
    start_at, end_at = occurrence_window_for_date(day, start_time, end_time, tz)
    duration = end_at - start_at
    if duration <= timedelta(0):
        raise ValidationError("O horario de fim precisa ser depois do horario de inicio.")
    if duration < timedelta(minutes=MIN_DURATION_MINUTES):
        raise ValidationError(f"Duracao minima de {MIN_DURATION_MINUTES} minuto(s).")
    if duration > timedelta(hours=MAX_DURATION_HOURS):
        raise ValidationError(
            f"Duracao maxima de {MAX_DURATION_HOURS}h excedida. Se o horario de fim e antes do "
            "inicio, ele e interpretado como no dia seguinte -- confira se os horarios estao corretos."
        )


def validate_recurrence(value) -> Recurrence:
    if value is None:
        return Recurrence()
    if not isinstance(value, dict):
        raise ValidationError("Recorrencia invalida.")
    rtype = value.get("type", RECURRENCE_ONCE)
    if rtype not in ALL_RECURRENCE_TYPES:
        raise ValidationError(f"Tipo de recorrencia invalido. Use um de: {', '.join(sorted(ALL_RECURRENCE_TYPES))}.")
    days = value.get("days") or []
    if rtype in (RECURRENCE_WEEKLY, RECURRENCE_CUSTOM_DAYS):
        if not isinstance(days, list) or not days:
            raise ValidationError("Selecione ao menos um dia da semana para essa recorrencia.")
        if not all(isinstance(d, int) and 0 <= d <= 6 for d in days):
            raise ValidationError("Dias da semana invalidos (use 0=segunda .. 6=domingo).")
        if rtype == RECURRENCE_WEEKLY and len(set(days)) != 1:
            raise ValidationError("Recorrencia semanal aceita exatamente um dia da semana (use 'custom_days' para varios).")
    return Recurrence(type=rtype, days=sorted(set(days)) if days else [])


def validate_device_id(value, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_DEVICE_ID_LENGTH:
        raise ValidationError(f"{field_name} invalido.")
    return value


def validate_meetings_root(value):
    return base_validation.validate_meetings_root_path(value)


def validate_model(value) -> str:
    return base_validation.validate_model(value)


def validate_device(value) -> str:
    return base_validation.validate_device(value)


def validate_language(value) -> str:
    return base_validation.validate_language(value)


def validate_chunk_seconds(value) -> int:
    return base_validation.validate_chunk_seconds(value)

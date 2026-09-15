"""Calculo de ocorrencias concretas (data + hora de inicio/fim em UTC) a
partir de uma regra de recorrencia -- deliberadamente simples (missao,
secao 16: "nao implementar um parser de calendario excessivamente
complexo"): so sabe somar dias de calendario e filtrar por dia da semana,
nunca expressoes tipo cron/RRULE completas.

Toda conversao de data+hora local para UTC passa por `zoneinfo.ZoneInfo`,
que ja resolve corretamente horario de verao e mudancas de regra de
timezone (a materializacao usa SEMPRE a data de calendario + hora de
parede reconstruidas do zero para cada dia candidato -- nunca soma
`timedelta(days=1)` num datetime ja com tzinfo, o que preservaria o offset
UTC antigo em vez de recalcular o offset correto daquele dia)."""

from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta, timezone as dt_timezone
from typing import List, NamedTuple, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import (
    RECURRENCE_CUSTOM_DAYS,
    RECURRENCE_DAILY,
    RECURRENCE_ONCE,
    RECURRENCE_WEEKDAYS,
    RECURRENCE_WEEKLY,
    Recurrence,
    Schedule,
)

# horizonte maximo de materializacao de ocorrencias futuras -- protege
# contra varrer indefinidamente pra um agendamento diario/semanal (missao:
# "nao implementar parser de calendario excessivamente complexo"). Uma
# checagem de conflito ou "proxima ocorrencia" nunca precisa olhar mais
# longe que isto.
MAX_LOOKAHEAD_DAYS = 366

WEEKDAYS_SET = {0, 1, 2, 3, 4}  # segunda(0) a sexta(4), convencao date.weekday()


class Occurrence(NamedTuple):
    occurrence_date: date
    start_at: datetime  # UTC, aware
    end_at: datetime  # UTC, aware


class InvalidTimeZone(ValueError):
    pass


def resolve_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise InvalidTimeZone(f"Timezone invalido ou desconhecido: {name!r}") from exc


def _parse_hhmm(value: str) -> dt_time:
    hour, _, minute = value.partition(":")
    return dt_time(hour=int(hour), minute=int(minute))


def occurrence_window_for_date(
    day: date, start_time: str, end_time: str, tz: ZoneInfo
) -> "tuple[datetime, datetime]":
    """Constroi o par (inicio, fim) em UTC para UM dia de calendario
    especifico, no timezone dado. Se `end_time <= start_time`, o fim e
    interpretado automaticamente como no dia SEGUINTE (sessao que atravessa
    meia-noite, missao secao 3: "23:00 -> 01:00 do dia seguinte") -- nunca
    produz uma janela de duracao zero ou negativa."""
    start_t = _parse_hhmm(start_time)
    end_t = _parse_hhmm(end_time)

    start_local = datetime.combine(day, start_t, tzinfo=tz)
    end_day = day if end_t > start_t else day + timedelta(days=1)
    end_local = datetime.combine(end_day, end_t, tzinfo=tz)

    return start_local.astimezone(dt_timezone.utc), end_local.astimezone(dt_timezone.utc)


def _applicable_weekdays(recurrence: Recurrence) -> Optional[set]:
    """Devolve o conjunto de dias da semana em que a recorrencia se aplica,
    ou None se for RECURRENCE_ONCE/RECURRENCE_DAILY (todo dia serve)."""
    if recurrence.type == RECURRENCE_WEEKDAYS:
        return WEEKDAYS_SET
    if recurrence.type in (RECURRENCE_WEEKLY, RECURRENCE_CUSTOM_DAYS):
        return set(recurrence.days)
    return None


def iter_occurrences(
    schedule: Schedule,
    range_start: datetime,
    range_end: datetime,
    limit: int = 100,
) -> List[Occurrence]:
    """Materializa as ocorrencias de `schedule` cujo INICIO cai dentro de
    [range_start, range_end) (ambos UTC, aware), na ordem cronologica, ate
    `limit` itens ou `MAX_LOOKAHEAD_DAYS` dias de calendario varridos (o
    que vier primeiro).

    RECURRENCE_ONCE produz no maximo UMA ocorrencia (a propria
    `scheduled_date`). As demais produzem uma por dia de calendario
    aplicavel, comecando em `scheduled_date` (nunca antes dela).
    """
    tz = resolve_zone(schedule.timezone)
    anchor = date.fromisoformat(schedule.scheduled_date)

    results: List[Occurrence] = []

    if schedule.recurrence.type == RECURRENCE_ONCE:
        start_at, end_at = occurrence_window_for_date(anchor, schedule.start_time, schedule.end_time, tz)
        if range_start <= start_at < range_end:
            results.append(Occurrence(anchor, start_at, end_at))
        return results

    applicable = _applicable_weekdays(schedule.recurrence)
    day = anchor
    # nunca materializa antes da ancora, mesmo que range_start seja anterior
    # a ela (ex.: agendamento criado pra comecar so daqui a alguns dias).
    if range_start.astimezone(tz).date() > anchor:
        # avanca o ponto de partida pra perto do inicio do range, sem pular
        # nenhum dia candidato -- comeca um dia antes por seguranca de fuso
        # (um dia em UTC pode corresponder a dois dias de calendario local
        # perto da virada, e vice-versa).
        day = max(anchor, range_start.astimezone(tz).date() - timedelta(days=1))

    for _ in range(MAX_LOOKAHEAD_DAYS):
        if len(results) >= limit:
            break
        if applicable is None or day.weekday() in applicable:
            start_at, end_at = occurrence_window_for_date(day, schedule.start_time, schedule.end_time, tz)
            if start_at >= range_end:
                break
            if start_at >= range_start:
                results.append(Occurrence(day, start_at, end_at))
        day = day + timedelta(days=1)

    return results


def next_occurrence(schedule: Schedule, after: datetime, limit_days: int = MAX_LOOKAHEAD_DAYS) -> Optional[Occurrence]:
    """A proxima ocorrencia com inicio >= `after`, ou None se nao houver
    nenhuma dentro do horizonte (ex.: RECURRENCE_ONCE cuja unica ocorrencia
    ja passou).

    A janela de busca de `limit_days` e medida a partir do maior entre
    `after` e a ancora do agendamento (`scheduled_date`) -- nunca a partir
    de `after` sozinho. Sem isso, um `after` bem anterior a ancora (ex.:
    "nunca processado ainda", representado como uma data bem no passado)
    faria a janela de 366 dias "gastar-se" toda antes mesmo de chegar
    perto da data real do agendamento, e a ocorrencia nunca seria
    encontrada -- um bug real pego pelos testes desta fase.
    """
    tz = resolve_zone(schedule.timezone)
    anchor = date.fromisoformat(schedule.scheduled_date)
    anchor_start, _ = occurrence_window_for_date(anchor, schedule.start_time, schedule.end_time, tz)
    search_start = max(after, anchor_start)
    far_future = search_start + timedelta(days=limit_days)
    found = iter_occurrences(schedule, search_start, far_future, limit=1)
    return found[0] if found else None

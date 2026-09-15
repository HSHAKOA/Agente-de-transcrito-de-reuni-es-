"""Deteccao de conflito entre agendamentos (missao, secao 4): por enquanto
so existe UMA sessao de captura ativa por aplicacao, entao duas ocorrencias
com janelas de tempo (UTC) sobrepostas nunca podem ambas ser aceitas.

Verificado no CADASTRO (bloqueia salvar), materializando ocorrencias
futuras dentro de um horizonte limitado -- nunca uma varredura infinita
(mesmo raciocinio de `recurrence.MAX_LOOKAHEAD_DAYS`). Um conflito entre
dois agendamentos recorrentes cuja primeira sobreposicao cai depois desse
horizonte nao e pego no cadastro; a garantia de "uma captura por vez" em
tempo real continua vindo do proprio `state['proc']` unico do painel (ver
`engine.py`), entao mesmo esse caso extremo nunca resulta em duas
gravacoes simultaneas de verdade -- so um agendamento "perdendo a vez" na
hora, o que o usuario veria como um "missed"/"failed" tardio em vez de um
aviso antecipado no cadastro.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

from .models import Schedule
from .recurrence import Occurrence, iter_occurrences

CONFLICT_CHECK_HORIZON_DAYS = 30
CONFLICT_CHECK_MAX_OCCURRENCES = 60


@dataclass
class Conflict:
    other_schedule: Schedule
    other_occurrence: Occurrence
    this_occurrence: Occurrence

    def message(self) -> str:
        start_local = self.other_occurrence.start_at.astimezone()
        end_local = self.other_occurrence.end_at.astimezone()
        return (
            f"Existe outra gravacao programada neste horario: {self.other_schedule.title} "
            f"({start_local.strftime('%d/%m %H:%M')} - {end_local.strftime('%H:%M')}). "
            "Altere um dos horarios."
        )


def _windows_overlap(a: Occurrence, b: Occurrence) -> bool:
    return a.start_at < b.end_at and b.start_at < a.end_at


def find_conflicts(
    candidate: Schedule,
    existing: List[Schedule],
    now: datetime,
    horizon_days: int = CONFLICT_CHECK_HORIZON_DAYS,
) -> List[Conflict]:
    """Compara as ocorrencias futuras de `candidate` contra as de todo
    agendamento em `existing` que ainda esta aberto (nao cancelado) e tem
    id diferente (permite re-checar um agendamento sendo EDITADO contra os
    outros, excluindo ele mesmo da lista `existing` antes de chamar)."""
    range_end = now + timedelta(days=horizon_days)
    candidate_occurrences = iter_occurrences(candidate, now, range_end, limit=CONFLICT_CHECK_MAX_OCCURRENCES)
    if not candidate_occurrences:
        return []

    conflicts: List[Conflict] = []
    for other in existing:
        if other.id == candidate.id or not other.is_open():
            continue
        other_occurrences = iter_occurrences(other, now, range_end, limit=CONFLICT_CHECK_MAX_OCCURRENCES)
        for mine in candidate_occurrences:
            for theirs in other_occurrences:
                if _windows_overlap(mine, theirs):
                    conflicts.append(Conflict(other_schedule=other, other_occurrence=theirs, this_occurrence=mine))
    return conflicts


def first_conflict_message(
    candidate: Schedule, existing: List[Schedule], now: datetime, horizon_days: int = CONFLICT_CHECK_HORIZON_DAYS
) -> Optional[str]:
    conflicts = find_conflicts(candidate, existing, now, horizon_days)
    return conflicts[0].message() if conflicts else None

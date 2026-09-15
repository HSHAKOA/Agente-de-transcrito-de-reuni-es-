"""Abstracao de relogio: TODO o modulo de agendamento le a hora atual so
atraves de um `Clock`, nunca chamando `datetime.now()`/`time.time()`
diretamente espalhado pelo codigo (missao, secao "Arquitetura testavel").

Isso permite testar o scheduler inteiro (start automatico, fim automatico,
deteccao de "missed", virada de dia, DST) sem esperar nenhum segundo de
verdade: os testes usam `ManualClock`, avancando o relogio manualmente e
observando as transicoes de estado. Producao usa `SystemClock`.

Toda hora que trafega no modulo de agendamento e timezone-aware em UTC
(`datetime.now(timezone.utc)`), nunca ingenua (naive) -- ver `models.py` e
`recurrence.py` para onde a conversao de/para o timezone de exibicao do
usuario acontece.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone


class Clock(ABC):
    """Fonte de tempo injetavel. `now()` sempre devolve um datetime
    timezone-aware em UTC."""

    @abstractmethod
    def now(self) -> datetime:
        raise NotImplementedError


class SystemClock(Clock):
    """Relogio de verdade (producao): `datetime.now(timezone.utc)`."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ManualClock(Clock):
    """Relogio controlado manualmente (testes): comeca num instante fixo
    (ou `datetime.now(timezone.utc)` se nenhum for passado) e so muda
    quando `set`/`advance` sao chamados explicitamente -- nunca avanca
    sozinho, nem mesmo com o tempo real passando durante o teste."""

    def __init__(self, start: "datetime | None" = None):
        self._current = start if start is not None else datetime.now(timezone.utc)
        if self._current.tzinfo is None:
            raise ValueError("ManualClock exige um datetime timezone-aware.")

    def now(self) -> datetime:
        return self._current

    def set(self, when: datetime) -> None:
        if when.tzinfo is None:
            raise ValueError("ManualClock exige um datetime timezone-aware.")
        self._current = when

    def advance(self, seconds: float = 0, **timedelta_kwargs) -> datetime:
        """Avanca o relogio por `seconds` (ou qualquer combinacao de
        argumentos de `timedelta`, ex.: `advance(minutes=5)`) e devolve o
        novo valor de `now()`."""
        delta = timedelta(seconds=seconds, **timedelta_kwargs)
        self._current = self._current + delta
        return self._current

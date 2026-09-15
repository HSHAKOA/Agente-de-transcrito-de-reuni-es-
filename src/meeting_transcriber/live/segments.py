"""Modelo de segmento ao vivo (Fase D, secao D.2/D.4): `provisional`
(resultado rapido, pode ser substituido) vs `committed` (resultado da
transcricao definitiva do chunk duravel -- a MESMA que ja alimenta o
`.md` final, inalterada)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

STATE_PROVISIONAL = "provisional"
STATE_COMMITTED = "committed"


@dataclass
class LiveSegment:
    start_seconds: float
    end_seconds: float
    text: str
    state: str  # STATE_PROVISIONAL ou STATE_COMMITTED
    source: str  # "system" | "microphone" | "mixed" -- de qual fluxo de audio veio
    confidence: Optional[float] = None

    def to_dict(self) -> dict:
        data = {
            "start_seconds": round(self.start_seconds, 2),
            "end_seconds": round(self.end_seconds, 2),
            "text": self.text,
            "state": self.state,
            "source": self.source,
        }
        if self.confidence is not None:
            data["confidence"] = round(self.confidence, 3)
        return data

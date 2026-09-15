"""Formatacao de timestamp compartilhada entre SRT e VTT (so o separador
entre segundos e milissegundos muda: virgula no SRT, ponto no VTT)."""

from __future__ import annotations


def format_timecode(seconds: float, decimal_separator: str) -> str:
    seconds = max(0.0, seconds)
    total_ms = round(seconds * 1000)
    hours, rem_ms = divmod(total_ms, 3_600_000)
    minutes, rem_ms = divmod(rem_ms, 60_000)
    secs, ms = divmod(rem_ms, 1_000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{decimal_separator}{ms:03d}"

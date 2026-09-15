"""Exportacao em texto puro: so a fala, sem marcacao nenhuma -- pra colar
em qualquer lugar (email, editor de texto, etc.)."""

from __future__ import annotations

from typing import List


def render(meeting: dict, segments: List[dict]) -> str:
    lines = [meeting.get("title") or meeting.get("id", "Reuniao"), ""]
    for seg in segments:
        label = seg.get("speaker_label")
        prefix = f"{label}: " if label else ""
        lines.append(f"{prefix}{seg['text']}")
    return "\n".join(lines) + "\n"

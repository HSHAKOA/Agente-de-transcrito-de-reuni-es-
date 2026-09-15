"""Exportacao em SubRip (.srt) -- legenda com timestamps reais de cada
segmento, formato aceito pela maioria dos players/editores de video."""

from __future__ import annotations

from typing import List

from ._timecodes import format_timecode

# duracao minima de exibicao -- um segmento com start==end (timestamp de
# fim desconhecido, ver docs/DATABASE.md sobre reunioes importadas do
# .md legado) ficaria com 0s de duracao, invisivel na pratica.
_MIN_DURATION_SECONDS = 0.5


def render(meeting: dict, segments: List[dict]) -> str:
    blocks = []
    for i, seg in enumerate(segments, start=1):
        start = seg["start_seconds"]
        end = seg["end_seconds"]
        if end <= start:
            end = start + _MIN_DURATION_SECONDS
        label = seg.get("speaker_label")
        text = f"{label}: {seg['text']}" if label else seg["text"]
        blocks.append(
            f"{i}\n{format_timecode(start, ',')} --> {format_timecode(end, ',')}\n{text}\n"
        )
    return "\n".join(blocks)

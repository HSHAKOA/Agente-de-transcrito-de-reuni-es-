"""Exportacao em WebVTT (.vtt) -- mesmo raciocinio de `srt.py`, formato
usado por players web (`<track>` do HTML5)."""

from __future__ import annotations

from typing import List

from ._timecodes import format_timecode
from .srt import _MIN_DURATION_SECONDS


def render(meeting: dict, segments: List[dict]) -> str:
    lines = ["WEBVTT", ""]
    for seg in segments:
        start = seg["start_seconds"]
        end = seg["end_seconds"]
        if end <= start:
            end = start + _MIN_DURATION_SECONDS
        label = seg.get("speaker_label")
        text = f"{label}: {seg['text']}" if label else seg["text"]
        lines.append(f"{format_timecode(start, '.')} --> {format_timecode(end, '.')}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)

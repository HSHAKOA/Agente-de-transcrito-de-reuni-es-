"""Exportadores (Fase I): cada formato recebe os mesmos dados -- um dict
de reuniao (formato de `storage.repository.MeetingRepository.get_meeting`)
e uma lista de segmentos (formato de `list_segments`) -- e devolve uma
string pronta para salvar em arquivo. Nunca dependem do SQLite
diretamente (testaveis com dados soltos, sem banco nenhum).
"""

from __future__ import annotations

from typing import Callable, Dict, List

from . import json_format, markdown, srt, txt, vtt

EXPORTERS: Dict[str, Callable[[dict, List[dict]], str]] = {
    "markdown": markdown.render,
    "txt": txt.render,
    "json": json_format.render,
    "srt": srt.render,
    "vtt": vtt.render,
}

EXTENSIONS = {
    "markdown": "md",
    "txt": "txt",
    "json": "json",
    "srt": "srt",
    "vtt": "vtt",
}

CONTENT_TYPES = {
    "markdown": "text/markdown; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
}


def render(fmt: str, meeting: dict, segments: List[dict]) -> str:
    if fmt not in EXPORTERS:
        raise ValueError(f"Formato de exportacao desconhecido: {fmt!r}. Use um de: {', '.join(sorted(EXPORTERS))}.")
    return EXPORTERS[fmt](meeting, segments)

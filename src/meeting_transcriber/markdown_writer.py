"""Escrita incremental do transcript em Markdown.

O arquivo e escrito progressivamente (cabecalho na abertura, um bloco de
texto por segmento transcrito) em vez de montado tudo em memoria e gravado
so no final. Assim, numa reuniao de horas, se o processo for interrompido
o .md ja contem tudo que foi transcrito ate aquele momento.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import List, Optional

from .transcriber import Segment


def format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class MarkdownWriter:
    def __init__(self, path: Path, title: str, model_size: str, language: Optional[str]):
        self.path = path
        self._write_header(title, model_size, language)

    def _write_header(self, title: str, model_size: str, language: Optional[str]) -> None:
        started = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = (
            f"# {title}\n\n"
            f"- **Data/hora de inicio:** {started}\n"
            f"- **Modelo Whisper:** {model_size}\n"
            f"- **Idioma:** {language or 'deteccao automatica'}\n\n"
            f"## Transcricao\n\n"
        )
        self.path.write_text(header, encoding="utf-8")

    def append_segments(self, segments: List[Segment]) -> None:
        if not segments:
            return
        lines = [f"**[{format_timestamp(s.start)}]** {s.text}\n\n" for s in segments]
        with self.path.open("a", encoding="utf-8") as f:
            f.writelines(lines)

    def append_error_note(self, start_offset_seconds: float, path: Path, error: Exception) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(
                f"> ⚠️ Falha ao transcrever o bloco iniciado em "
                f"**[{format_timestamp(start_offset_seconds)}]** ({error}). "
                f"Audio bruto mantido em `{path}` para nova tentativa manual.\n\n"
            )

    def finalize(self, duration_seconds: float) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(f"\n---\n\n*Duracao total gravada: {format_timestamp(duration_seconds)}*\n")

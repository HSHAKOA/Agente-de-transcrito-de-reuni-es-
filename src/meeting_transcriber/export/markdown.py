"""Exportacao em Markdown estruturado -- Metadados + Transcricao.
Secoes de Resumo/Decisoes/Tarefas (Fase G, nao implementada) so
apareceriam aqui se os dados existissem de verdade -- nunca uma secao
vazia ou inventada."""

from __future__ import annotations

from typing import List


def _format_hms(seconds: float) -> str:
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def render(meeting: dict, segments: List[dict]) -> str:
    title = meeting.get("title") or meeting.get("id", "Reuniao")
    lines = [f"# {title}", "", "## Metadados", ""]
    lines.append(f"- **Status:** {meeting.get('status', 'desconhecido')}")
    if meeting.get("started_at"):
        lines.append(f"- **Inicio:** {meeting['started_at']}")
    if meeting.get("finished_at"):
        lines.append(f"- **Fim:** {meeting['finished_at']}")
    if meeting.get("duration_seconds") is not None:
        lines.append(f"- **Duracao:** {_format_hms(meeting['duration_seconds'])}")
    if meeting.get("model"):
        lines.append(f"- **Modelo Whisper:** {meeting['model']}")
    if meeting.get("language"):
        lines.append(f"- **Idioma:** {meeting['language']}")
    lines.append("")

    lines.append("## Transcricao")
    lines.append("")
    if not segments:
        lines.append("*Nenhum segmento transcrito.*")
    for seg in segments:
        label = seg.get("speaker_label")
        prefix = f"**{label}** — " if label else ""
        lines.append(f"**[{_format_hms(seg['start_seconds'])}]** {prefix}{seg['text']}")
        lines.append("")

    return "\n".join(lines)

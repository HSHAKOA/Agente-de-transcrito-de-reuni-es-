"""Exportacao estruturada em JSON -- pra interoperabilidade com outras
ferramentas (nao e o formato interno do banco, e uma projecao estavel
pensada pra ser consumida por fora)."""

from __future__ import annotations

import json
from typing import List


def render(meeting: dict, segments: List[dict]) -> str:
    payload = {
        "meeting": {
            "id": meeting.get("id"),
            "title": meeting.get("title"),
            "status": meeting.get("status"),
            "started_at": meeting.get("started_at"),
            "finished_at": meeting.get("finished_at"),
            "duration_seconds": meeting.get("duration_seconds"),
            "language": meeting.get("language"),
            "model": meeting.get("model"),
        },
        "segments": [
            {
                "sequence": seg.get("sequence"),
                "start_seconds": seg.get("start_seconds"),
                "end_seconds": seg.get("end_seconds"),
                "speaker_label": seg.get("speaker_label"),
                "text": seg.get("text"),
            }
            for seg in segments
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)

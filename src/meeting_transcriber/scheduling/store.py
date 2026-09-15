"""Persistencia de agendamentos: um unico arquivo JSON (`schedules.json`),
escrita atomica (tmp file + `os.replace` com retry -- mesmo padrao de
`settings.py`/`session.py`, incluindo o retry que um teste de concorrencia
real desta fase de audio ja mostrou ser necessario no Windows).

Interface deliberadamente pequena (`list_all`/`get`/`save`/`delete`) para
poder trocar a implementacao por SQLite depois (missao, secao 19) sem
precisar mudar quem chama (`service.py`/`engine.py`) -- so a classe
`ScheduleStore` muda de implementacao, nunca o contrato. Fica FORA da
pasta de reunioes (mesmo raciocinio de `settings.py`): agendamentos sao
configuracao do app, nao conteudo de uma reuniao especifica, e cada
agendamento pode apontar pra uma `meetings_root` diferente.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from .models import Schedule

SCHEDULES_FILE_NAME = "schedules.json"


def _replace_with_retry(src: Path, dst: Path, attempts: int = 5, delay: float = 0.05) -> None:
    last_exc: Optional[OSError] = None
    for attempt in range(attempts):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            last_exc = exc
            if attempt < attempts - 1:
                time.sleep(delay)
    assert last_exc is not None
    raise last_exc


class ScheduleStore:
    """Guarda todos os agendamentos num unico arquivo JSON. Thread-safe
    (protegido por um lock proprio) porque o motor do scheduler roda numa
    thread de background enquanto requests HTTP podem criar/editar/cancelar
    agendamentos ao mesmo tempo."""

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()

    def _read_raw(self) -> Dict[str, dict]:
        if not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _write_raw(self, data: Dict[str, dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_name(self._path.name + f".tmp-{os.getpid()}")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        _replace_with_retry(tmp_path, self._path)

    def list_all(self) -> List[Schedule]:
        with self._lock:
            raw = self._read_raw()
        schedules = []
        for entry in raw.values():
            try:
                schedules.append(Schedule.from_dict(entry))
            except (KeyError, ValueError, TypeError):
                continue  # entrada corrompida/de versao futura -- ignora, nunca derruba o resto
        schedules.sort(key=lambda s: s.created_at)
        return schedules

    def get(self, schedule_id: str) -> Optional[Schedule]:
        with self._lock:
            raw = self._read_raw()
        entry = raw.get(schedule_id)
        if entry is None:
            return None
        return Schedule.from_dict(entry)

    def save(self, schedule: Schedule) -> None:
        with self._lock:
            raw = self._read_raw()
            raw[schedule.id] = schedule.to_dict()
            self._write_raw(raw)

    def delete(self, schedule_id: str) -> bool:
        with self._lock:
            raw = self._read_raw()
            if schedule_id not in raw:
                return False
            del raw[schedule_id]
            self._write_raw(raw)
            return True

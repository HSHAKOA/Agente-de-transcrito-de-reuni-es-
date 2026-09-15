"""Camada de repositorio (Fase E, secao E.9): toda leitura/escrita no
SQLite passa por aqui -- nunca SQL espalhado pela UI/webui.py. Um lock
proprio serializa escritas (SQLite aceita um escritor por vez; sem isto,
duas requests HTTP concorrentes podem esbarrar em "database is locked").
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .db import has_fts5

MEETING_COLUMNS = [
    "id", "title", "status", "started_at", "finished_at", "duration_seconds",
    "root_directory", "meeting_directory", "language", "model",
    "system_audio_enabled", "system_device_id", "system_device_name",
    "microphone_enabled", "microphone_device_id", "microphone_device_name",
    "deleted_at", "created_at", "updated_at",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _row_to_dict(row: sqlite3.Row) -> Dict:
    return {key: row[key] for key in row.keys()}


class MeetingRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.Lock()
        self._fts5 = has_fts5(conn)

    # -- meetings -----------------------------------------------------------

    def upsert_meeting(self, data: Dict) -> None:
        """Insere ou atualiza (por `id`) -- idempotente de proposito
        (missao, secao E.7: importar a mesma reuniao duas vezes nunca
        duplica, so atualiza os campos)."""
        now = _now_iso()
        payload = {col: data.get(col) for col in MEETING_COLUMNS if col not in ("created_at", "updated_at")}
        payload["updated_at"] = now

        with self._lock, self._conn:
            existing = self._conn.execute("SELECT id FROM meetings WHERE id = ?", (data["id"],)).fetchone()
            if existing is None:
                payload["created_at"] = now
                columns = list(payload.keys())
                placeholders = ", ".join(f":{c}" for c in columns)
                self._conn.execute(
                    f"INSERT INTO meetings ({', '.join(columns)}) VALUES ({placeholders})", payload
                )
            else:
                set_clause = ", ".join(f"{c} = :{c}" for c in payload if c != "id")
                self._conn.execute(f"UPDATE meetings SET {set_clause} WHERE id = :id", {**payload, "id": data["id"]})

            if self._fts5 and data.get("title"):
                self._conn.execute("DELETE FROM search_index WHERE meeting_id = ? AND kind = 'title'", (data["id"],))
                self._conn.execute(
                    "INSERT INTO search_index (meeting_id, kind, text) VALUES (?, 'title', ?)",
                    (data["id"], data["title"]),
                )

    def get_meeting(self, meeting_id: str) -> Optional[Dict]:
        row = self._conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def list_meetings(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        include_deleted: bool = False,
    ) -> List[Dict]:
        clauses = []
        params: List = []
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        if status:
            clauses.append("status = ?")
            params.append(status)
        if date_from:
            clauses.append("started_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("started_at <= ?")
            params.append(date_to)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.extend([limit, offset])
        rows = self._conn.execute(
            f"SELECT * FROM meetings {where} ORDER BY started_at DESC, created_at DESC LIMIT ? OFFSET ?", params
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    def count_meetings(self, status: Optional[str] = None, include_deleted: bool = False) -> int:
        clauses = []
        params: List = []
        if not include_deleted:
            clauses.append("deleted_at IS NULL")
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        row = self._conn.execute(f"SELECT COUNT(*) AS n FROM meetings {where}", params).fetchone()
        return row["n"]

    def soft_delete_meeting(self, meeting_id: str) -> bool:
        """Marca `deleted_at` -- NUNCA apaga a linha nem toca em nenhum
        arquivo real (missao, secao E.12: exclusao explicita e segura,
        nunca um endpoint destrutivo silencioso)."""
        with self._lock, self._conn:
            cur = self._conn.execute(
                "UPDATE meetings SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (_now_iso(), _now_iso(), meeting_id),
            )
            return cur.rowcount > 0

    # -- segments -------------------------------------------------------------

    def replace_segments(self, meeting_id: str, segments: List[Dict]) -> None:
        """Substitui TODOS os segmentos de uma reuniao pelos passados --
        usado pela importacao (le o .md/estado inteiro de uma vez), nunca
        pelo caminho de gravacao ao vivo (que nao usa o SQLite)."""
        now = _now_iso()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM meeting_segments WHERE meeting_id = ?", (meeting_id,))
            if self._fts5:
                self._conn.execute("DELETE FROM search_index WHERE meeting_id = ? AND kind = 'segment'", (meeting_id,))
            for seq, seg in enumerate(segments):
                self._conn.execute(
                    "INSERT INTO meeting_segments "
                    "(meeting_id, sequence, start_seconds, end_seconds, speaker_label, text, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (meeting_id, seq, seg["start_seconds"], seg["end_seconds"], seg.get("speaker_label"), seg["text"], now),
                )
                if self._fts5 and seg.get("text"):
                    self._conn.execute(
                        "INSERT INTO search_index (meeting_id, kind, text) VALUES (?, 'segment', ?)",
                        (meeting_id, seg["text"]),
                    )

    def list_segments(self, meeting_id: str) -> List[Dict]:
        rows = self._conn.execute(
            "SELECT * FROM meeting_segments WHERE meeting_id = ? ORDER BY sequence ASC", (meeting_id,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    # -- busca ------------------------------------------------------------

    def search_meetings(self, query: str, limit: int = 50) -> List[Dict]:
        """Busca em titulo + segmentos de transcricao. Usa FTS5 quando
        disponivel; cai para `LIKE` (mais lento, mas funcional) quando o
        SQLite do ambiente nao foi compilado com FTS5 (missao, secao
        E.11: fallback documentado, nunca uma dependencia externa tipo
        Elasticsearch)."""
        query = (query or "").strip()
        if not query:
            return []
        if self._fts5:
            rows = self._conn.execute(
                """
                SELECT m.* FROM meetings m
                WHERE m.deleted_at IS NULL AND m.id IN (
                    SELECT DISTINCT meeting_id FROM search_index WHERE search_index MATCH ?
                )
                ORDER BY m.started_at DESC LIMIT ?
                """,
                (_fts5_query(query), limit),
            ).fetchall()
        else:
            like = f"%{query}%"
            rows = self._conn.execute(
                """
                SELECT DISTINCT m.* FROM meetings m
                LEFT JOIN meeting_segments s ON s.meeting_id = m.id
                WHERE m.deleted_at IS NULL AND (m.title LIKE ? OR s.text LIKE ?)
                ORDER BY m.started_at DESC LIMIT ?
                """,
                (like, like, limit),
            ).fetchall()
        return [_row_to_dict(r) for r in rows]


def _fts5_query(raw: str) -> str:
    """Escapa a entrada do usuario pra sintaxe de query do FTS5: cada
    palavra vira uma string literal entre aspas (via `""`), unidas por
    AND implicito -- evita que caracteres especiais do FTS5 (`"`, `*`,
    `-`, parenteses) quebrem a query ou sejam interpretados como operador
    quando o usuario so queria buscar um texto literal."""
    words = raw.split()
    escaped = ['"' + w.replace('"', '""') + '"' for w in words if w]
    return " AND ".join(escaped) if escaped else '""'

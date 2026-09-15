"""Conexao e migrations do SQLite local (Fase E).

Migrations sao uma LISTA versionada de scripts SQL, nunca `CREATE TABLE
IF NOT EXISTS` espalhado pelo codigo (missao, secao E.2) -- uma tabela
`schema_version` guarda qual a ultima migration aplicada, e `migrate()`
so aplica as que ainda faltam, em ordem, dentro de uma transacao cada.
Seguro chamar `migrate()` toda vez que o app inicia (idempotente).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Tuple

# cada item: (versao, sql). Versao 1 e o schema inicial -- NUNCA editar um
# script ja publicado; toda mudanca de schema futura entra como uma nova
# versao no fim desta lista.
MIGRATIONS: List[Tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE meetings (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT,
            duration_seconds REAL,
            root_directory TEXT,
            meeting_directory TEXT NOT NULL,
            language TEXT,
            model TEXT,
            system_audio_enabled INTEGER,
            system_device_id TEXT,
            system_device_name TEXT,
            microphone_enabled INTEGER,
            microphone_device_id TEXT,
            microphone_device_name TEXT,
            deleted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE meeting_segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL,
            start_seconds REAL NOT NULL,
            end_seconds REAL NOT NULL,
            speaker_label TEXT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_segments_meeting ON meeting_segments(meeting_id, start_seconds);
        CREATE UNIQUE INDEX idx_segments_meeting_sequence ON meeting_segments(meeting_id, sequence);
        """,
    ),
]


def _fts5_available(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("CREATE VIRTUAL TABLE _fts5_probe USING fts5(x)")
        conn.execute("DROP TABLE _fts5_probe")
        return True
    except sqlite3.OperationalError:
        return False


def connect(db_path: Path) -> sqlite3.Connection:
    """Abre (criando se preciso) o banco em `db_path` e garante que o
    schema esta atualizado. `check_same_thread=False` porque o painel
    atende requests HTTP em threads diferentes (ThreadingHTTPServer) --
    cada operacao ainda serializa via o lock do proprio `Repository`."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> List[int]:
    """Aplica as migrations pendentes, em ordem, cada uma numa transacao
    propria. Devolve a lista de versoes recem-aplicadas (vazia se o
    schema ja estava em dia)."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current = row["v"] if row and row["v"] is not None else 0

    applied = []
    for version, sql in MIGRATIONS:
        if version <= current:
            continue
        with conn:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
        applied.append(version)

    # FTS5 e opcional (depende de como o SQLite foi compilado) -- criada
    # fora do fluxo de migrations versionadas de proposito, porque sua
    # AUSENCIA nunca deveria bloquear o resto do schema (missao, secao
    # E.11: "se runtime nao suportar: fallback funcional documentado").
    if _fts5_available(conn):
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(meeting_id UNINDEXED, kind UNINDEXED, text)"
        )
    return applied


def has_fts5(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='search_index'"
    ).fetchone()
    return row is not None

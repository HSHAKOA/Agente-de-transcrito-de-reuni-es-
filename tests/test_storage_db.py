from __future__ import annotations

from pathlib import Path

from meeting_transcriber.storage.db import connect, has_fts5, migrate


def test_connect_creates_db_file(tmp_path: Path):
    db_path = tmp_path / "data" / "meetings.db"
    conn = connect(db_path)
    assert db_path.exists()
    conn.close()


def test_connect_is_idempotent(tmp_path: Path):
    db_path = tmp_path / "meetings.db"
    connect(db_path).close()
    conn = connect(db_path)  # nao deveria lancar nem duplicar schema
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "meetings" in tables
    assert "meeting_segments" in tables
    conn.close()


def test_migrate_records_schema_version(tmp_path: Path):
    conn = connect(tmp_path / "meetings.db")
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    assert row["v"] == 1
    conn.close()


def test_migrate_second_call_applies_nothing_new(tmp_path: Path):
    conn = connect(tmp_path / "meetings.db")
    applied = migrate(conn)
    assert applied == []
    conn.close()


def test_meetings_table_has_expected_columns(tmp_path: Path):
    conn = connect(tmp_path / "meetings.db")
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(meetings)")}
    for expected in ("id", "title", "status", "meeting_directory", "deleted_at", "created_at", "updated_at"):
        assert expected in columns
    conn.close()


def test_segments_table_has_unique_sequence_per_meeting(tmp_path: Path):
    conn = connect(tmp_path / "meetings.db")
    conn.execute(
        "INSERT INTO meetings (id, title, status, meeting_directory, created_at, updated_at) "
        "VALUES ('m1', 't', 's', 'd', 'c', 'u')"
    )
    conn.execute(
        "INSERT INTO meeting_segments (meeting_id, sequence, start_seconds, end_seconds, text, created_at) "
        "VALUES ('m1', 0, 0, 1, 'a', 'c')"
    )
    import sqlite3

    try:
        conn.execute(
            "INSERT INTO meeting_segments (meeting_id, sequence, start_seconds, end_seconds, text, created_at) "
            "VALUES ('m1', 0, 1, 2, 'b', 'c')"
        )
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    assert raised
    conn.close()


def test_has_fts5_reflects_search_index_table_presence(tmp_path: Path):
    conn = connect(tmp_path / "meetings.db")
    # nesta maquina/ambiente de teste o SQLite do Python normalmente traz
    # FTS5 -- mas o teste so precisa que has_fts5() bata com a realidade,
    # nao que FTS5 esteja disponivel especificamente.
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert has_fts5(conn) == ("search_index" in tables)
    conn.close()

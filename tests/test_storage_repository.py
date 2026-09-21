from __future__ import annotations

import threading
from pathlib import Path

import pytest

from meeting_transcriber.storage.db import connect
from meeting_transcriber.storage.repository import MeetingRepository


@pytest.fixture
def repo(tmp_path: Path) -> MeetingRepository:
    conn = connect(tmp_path / "meetings.db")
    return MeetingRepository(conn)


def _meeting(id_="m1", **overrides) -> dict:
    data = dict(
        id=id_,
        title="Reuniao de teste",
        status="completed",
        started_at="2026-09-15T19:00:00+00:00",
        finished_at="2026-09-15T20:00:00+00:00",
        duration_seconds=3600.0,
        root_directory="D:\\Reunioes",
        meeting_directory=f"D:\\Reunioes\\{id_}",
        language="pt",
        model="small",
        system_audio_enabled=True,
        system_device_id=None,
        system_device_name=None,
        microphone_enabled=False,
        microphone_device_id=None,
        microphone_device_name=None,
    )
    data.update(overrides)
    return data


def test_upsert_then_get_round_trips(repo: MeetingRepository):
    repo.upsert_meeting(_meeting())
    loaded = repo.get_meeting("m1")
    assert loaded is not None
    assert loaded["title"] == "Reuniao de teste"
    assert loaded["created_at"] is not None
    assert loaded["deleted_at"] is None


def test_upsert_twice_updates_instead_of_duplicating(repo: MeetingRepository):
    repo.upsert_meeting(_meeting(title="Original"))
    repo.upsert_meeting(_meeting(title="Atualizado"))
    assert repo.get_meeting("m1")["title"] == "Atualizado"
    assert repo.count_meetings() == 1


def test_get_meeting_returns_none_when_not_found(repo: MeetingRepository):
    assert repo.get_meeting("nao-existe") is None


def test_list_meetings_orders_by_started_at_desc(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", started_at="2026-09-01T00:00:00+00:00"))
    repo.upsert_meeting(_meeting("m2", started_at="2026-09-15T00:00:00+00:00"))
    ids = [m["id"] for m in repo.list_meetings()]
    assert ids == ["m2", "m1"]


def test_list_meetings_filters_by_status(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", status="completed"))
    repo.upsert_meeting(_meeting("m2", status="failed"))
    result = repo.list_meetings(status="failed")
    assert [m["id"] for m in result] == ["m2"]


def test_list_meetings_pagination(repo: MeetingRepository):
    for i in range(5):
        repo.upsert_meeting(_meeting(f"m{i}", started_at=f"2026-09-{i+1:02d}T00:00:00+00:00"))
    page1 = repo.list_meetings(limit=2, offset=0)
    page2 = repo.list_meetings(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert {m["id"] for m in page1}.isdisjoint({m["id"] for m in page2})


def test_list_meetings_excludes_deleted_by_default(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    repo.soft_delete_meeting("m1")
    assert repo.list_meetings() == []
    assert len(repo.list_meetings(include_deleted=True)) == 1


def test_count_meetings_matches_list_length(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    repo.upsert_meeting(_meeting("m2"))
    assert repo.count_meetings() == 2


def test_soft_delete_never_removes_the_row(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    assert repo.soft_delete_meeting("m1") is True
    loaded = repo.get_meeting("m1")
    assert loaded is not None
    assert loaded["deleted_at"] is not None


def test_soft_delete_returns_false_when_not_found(repo: MeetingRepository):
    assert repo.soft_delete_meeting("nao-existe") is False


def test_soft_delete_twice_returns_false_second_time(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    assert repo.soft_delete_meeting("m1") is True
    assert repo.soft_delete_meeting("m1") is False


def test_replace_segments_then_list(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    repo.replace_segments("m1", [
        {"start_seconds": 0.0, "end_seconds": 5.0, "text": "ola"},
        {"start_seconds": 5.0, "end_seconds": 10.0, "text": "mundo", "speaker_label": "Você"},
    ])
    segments = repo.list_segments("m1")
    assert [s["text"] for s in segments] == ["ola", "mundo"]
    assert segments[1]["speaker_label"] == "Você"
    assert segments[0]["sequence"] == 0


def test_replace_segments_is_idempotent_no_duplication(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    repo.replace_segments("m1", [{"start_seconds": 0.0, "end_seconds": 5.0, "text": "primeira versao"}])
    repo.replace_segments("m1", [{"start_seconds": 0.0, "end_seconds": 5.0, "text": "segunda versao"}])
    segments = repo.list_segments("m1")
    assert len(segments) == 1
    assert segments[0]["text"] == "segunda versao"


def test_search_meetings_by_title(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", title="Reuniao Projeto ERP"))
    repo.upsert_meeting(_meeting("m2", title="Aula de Calculo"))
    results = repo.search_meetings("ERP")
    assert [m["id"] for m in results] == ["m1"]


def test_search_meetings_by_segment_text(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", title="Reuniao A"))
    repo.replace_segments("m1", [{"start_seconds": 0, "end_seconds": 1, "text": "vamos falar de orcamento"}])
    repo.upsert_meeting(_meeting("m2", title="Reuniao B"))
    repo.replace_segments("m2", [{"start_seconds": 0, "end_seconds": 1, "text": "assunto totalmente diferente"}])

    results = repo.search_meetings("orcamento")
    assert [m["id"] for m in results] == ["m1"]


def test_search_meetings_empty_query_returns_nothing(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1"))
    assert repo.search_meetings("") == []


def test_search_meetings_no_match_returns_empty(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", title="Reuniao A"))
    assert repo.search_meetings("termo-que-nao-existe-em-nada") == []


def test_search_meetings_excludes_deleted(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", title="Reuniao Especial"))
    repo.soft_delete_meeting("m1")
    assert repo.search_meetings("Especial") == []


def test_search_meetings_handles_special_characters_safely(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("m1", title='Titulo com "aspas" e * asterisco'))
    # nao deveria lancar excecao nenhuma, mesmo com sintaxe especial do FTS5
    repo.search_meetings('"aspas" * (parenteses) OR AND NOT -algo')


# -- concorrencia real (P1-4 pos-auditoria) -------------------------------
#
# `db.py:connect` abre com `check_same_thread=False` porque o painel atende
# cada request HTTP numa thread propria (ThreadingHTTPServer). A auditoria
# encontrou que so as ESCRITAS (upsert/replace_segments/soft_delete) tinham
# um lock -- leituras corriam sem nenhuma serializacao na MESMA conexao
# compartilhada. Os testes abaixo rodam de verdade com threads reais (nao
# so leem o codigo e assumem que "parece certo") para pegar exatamente o
# tipo de falha esporadica que so aparece sob concorrencia real.


def _run_concurrently(fns, seconds=0.5):
    """Roda cada callable em `fns` numa thread propria por `seconds`
    segundos corridos (chamando repetidamente), coletando qualquer
    excecao. Duração fixa (não um número fixo de iterações) para dar
    tempo real de threads se entrelaçarem de verdade."""
    errors: list = []
    stop = threading.Event()

    def _wrap(fn):
        while not stop.is_set():
            try:
                fn()
            except Exception as exc:  # pragma: no cover - so deveria acontecer se o teste falhar
                errors.append(exc)
                return

    threads = [threading.Thread(target=_wrap, args=(fn,)) for fn in fns]
    for t in threads:
        t.start()
    stop.wait(seconds)
    stop.set()
    for t in threads:
        t.join(timeout=5)
    return errors


def test_ten_plus_concurrent_reads_never_raise(repo: MeetingRepository):
    for i in range(5):
        repo.upsert_meeting(_meeting(f"m{i}"))
        repo.replace_segments(f"m{i}", [{"start_seconds": 0, "end_seconds": 1, "text": f"segmento {i}"}])

    readers = [
        (lambda: repo.list_meetings()),
        (lambda: repo.get_meeting("m0")),
        (lambda: repo.count_meetings()),
        (lambda: repo.list_segments("m1")),
        (lambda: repo.search_meetings("segmento")),
    ] * 3  # 15 threads lendo ao mesmo tempo

    errors = _run_concurrently(readers)
    assert errors == []


def test_concurrent_read_and_write_never_raise(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("seed"))
    counter = {"n": 0}
    counter_lock = threading.Lock()

    def _write():
        with counter_lock:
            counter["n"] += 1
            n = counter["n"]
        repo.upsert_meeting(_meeting(f"writer-{n}"))

    def _read():
        repo.list_meetings()
        repo.get_meeting("seed")
        repo.count_meetings()

    errors = _run_concurrently([_write, _write, _read, _read, _read])
    assert errors == []


def test_concurrent_search_and_import_like_workload_never_raises(repo: MeetingRepository):
    """Simula o cenario real que motivou a correcao: o Dashboard fazendo
    busca (`search_meetings`) enquanto uma importacao roda em outra thread
    (`upsert_meeting` + `replace_segments` em sequencia, como
    `import_meeting` faz de verdade)."""
    ids = [f"import-{i}" for i in range(5)]

    def _import_like():
        for meeting_id in ids:
            repo.upsert_meeting(_meeting(meeting_id, title=f"Reuniao {meeting_id}"))
            repo.replace_segments(meeting_id, [{"start_seconds": 0, "end_seconds": 1, "text": "pauta da reuniao"}])

    def _search():
        repo.search_meetings("pauta")
        repo.list_meetings()

    errors = _run_concurrently([_import_like, _search, _search, _search])
    assert errors == []


def test_dashboard_reads_and_meeting_finalize_never_raise_concurrently(repo: MeetingRepository):
    """Simula Dashboard consultando `/api/meetings` (leitura) enquanto uma
    gravacao termina e e indexada (`upsert_meeting`/`replace_segments`) --
    o cenario exato do bug (P1-2 auto-import + P1-4 concorrencia
    combinados)."""

    def _finalize_meeting():
        for i in range(20):
            meeting_id = f"finalized-{i}"
            repo.upsert_meeting(_meeting(meeting_id))
            repo.replace_segments(meeting_id, [{"start_seconds": 0, "end_seconds": 1, "text": "ola"}])

    def _dashboard_poll():
        repo.list_meetings(limit=5)
        repo.count_meetings()

    errors = _run_concurrently([_finalize_meeting, _dashboard_poll, _dashboard_poll])
    assert errors == []


# -- historico paginado: filtros combinaveis + contagem consistente ---------

def _seed_history(repo: MeetingRepository):
    """Cinco reunioes de ERP em dias/status diferentes, uma de Calculo e uma
    excluida. `started_at` em ISO local (-03:00), como o app grava."""
    rows = [
        ("erp1", "Projeto ERP kickoff", "completed", "2026-09-14T19:00:00-03:00"),
        ("erp2", "Projeto ERP revisao", "completed", "2026-09-15T23:30:00-03:00"),  # fim do dia 15
        ("erp3", "Projeto ERP homologacao", "interrupted", "2026-09-16T00:10:00-03:00"),  # comeco do dia 16
        ("erp4", "Projeto ERP treinamento", "failed", "2026-09-17T19:00:00-03:00"),
        ("erp5", "Projeto ERP entrega", "completed", "2026-09-18T19:00:00-03:00"),
        ("calc", "Aula de Calculo", "completed", "2026-09-15T08:00:00-03:00"),
    ]
    for id_, title, status, started in rows:
        repo.upsert_meeting(_meeting(id_, title=title, status=status, started_at=started))
    repo.upsert_meeting(_meeting("gone", title="Projeto ERP apagado", started_at="2026-09-15T10:00:00-03:00"))
    repo.soft_delete_meeting("gone")


def test_date_filter_includes_the_whole_last_day(repo: MeetingRepository):
    """Regressao classica: `started_at <= '2026-09-15'` como texto exclui o
    dia 15 inteiro ('2026-09-15T23:30...' > '2026-09-15')."""
    _seed_history(repo)

    ids = {m["id"] for m in repo.list_meetings(date_from="2026-09-15", date_to="2026-09-15")}

    assert ids == {"erp2", "calc"}  # 23:30 do dia 15 entra; 00:10 do dia 16 nao


def test_date_filter_open_ended_ranges(repo: MeetingRepository):
    _seed_history(repo)

    only_from = {m["id"] for m in repo.list_meetings(date_from="2026-09-17")}
    only_to = {m["id"] for m in repo.list_meetings(date_to="2026-09-14")}

    assert only_from == {"erp4", "erp5"}
    assert only_to == {"erp1"}


def test_meeting_without_started_at_is_excluded_by_any_date_filter(repo: MeetingRepository):
    repo.upsert_meeting(_meeting("never", started_at=None))

    assert repo.list_meetings(date_from="2000-01-01") == []
    assert [m["id"] for m in repo.list_meetings()] == ["never"]


def test_query_pagination_slices_the_matches_and_count_matches_the_filter(repo: MeetingRepository):
    _seed_history(repo)

    first = repo.list_meetings(limit=2, offset=0, query="ERP")
    second = repo.list_meetings(limit=2, offset=2, query="ERP")
    last = repo.list_meetings(limit=2, offset=4, query="ERP")

    ids = [m["id"] for m in first + second + last]
    assert ids == ["erp5", "erp4", "erp3", "erp2", "erp1"]  # mais recente primeiro, sem repetir nem faltar
    assert repo.count_meetings(query="ERP") == 5  # exclui "gone" (soft delete) e "calc"


def test_filters_combine_status_period_and_query(repo: MeetingRepository):
    _seed_history(repo)

    result = repo.list_meetings(query="ERP", status="completed", date_from="2026-09-15", date_to="2026-09-18")

    assert [m["id"] for m in result] == ["erp5", "erp2"]
    assert repo.count_meetings(query="ERP", status="completed", date_from="2026-09-15", date_to="2026-09-18") == 2


def test_count_always_uses_the_same_filters_as_the_list(repo: MeetingRepository):
    _seed_history(repo)
    combos = [
        {},
        {"status": "failed"},
        {"date_from": "2026-09-16"},
        {"date_to": "2026-09-15"},
        {"query": "Calculo"},
        {"query": "ERP", "status": "interrupted"},
    ]
    for combo in combos:
        assert repo.count_meetings(**combo) == len(repo.list_meetings(limit=100, **combo)), combo


def test_query_matches_transcript_text_and_respects_filters(repo: MeetingRepository):
    _seed_history(repo)
    repo.replace_segments("erp1", [{"start_seconds": 0.0, "end_seconds": 5.0, "text": "vamos revisar o orcamento"}])
    repo.replace_segments("erp5", [{"start_seconds": 0.0, "end_seconds": 5.0, "text": "orcamento aprovado"}])

    assert {m["id"] for m in repo.list_meetings(query="orcamento")} == {"erp1", "erp5"}
    assert [m["id"] for m in repo.list_meetings(query="orcamento", date_from="2026-09-18")] == ["erp5"]


def test_soft_deleted_meetings_never_appear_in_query_results_or_counts(repo: MeetingRepository):
    _seed_history(repo)

    assert "gone" not in {m["id"] for m in repo.list_meetings(query="apagado")}
    assert repo.count_meetings(query="apagado") == 0


def test_like_fallback_treats_percent_and_underscore_literally(repo: MeetingRepository):
    """Sem FTS5 a busca cai para LIKE; `%` e `_` do usuario nao podem virar curinga."""
    repo._fts5 = False
    repo.upsert_meeting(_meeting("a", title="Desconto de 100% aprovado"))
    repo.upsert_meeting(_meeting("b", title="Desconto de 100 aprovado"))
    repo.upsert_meeting(_meeting("c", title="arquivo a_b final"))
    repo.upsert_meeting(_meeting("d", title="arquivo axb final"))

    assert {m["id"] for m in repo.list_meetings(query="100%")} == {"a"}
    assert {m["id"] for m in repo.list_meetings(query="a_b")} == {"c"}
    assert repo.count_meetings(query="100%") == 1


@pytest.mark.parametrize("use_fts5", [True, False])
def test_query_is_never_interpreted_as_sql(repo: MeetingRepository, use_fts5):
    if not use_fts5:
        repo._fts5 = False
    _seed_history(repo)

    assert repo.list_meetings(query="'; DROP TABLE meetings; --") == []
    assert repo.count_meetings(query='" OR 1=1 --') == 0
    assert repo.count_meetings() == 6  # a tabela continua la


def test_search_meetings_is_a_thin_wrapper_over_list_meetings(repo: MeetingRepository):
    _seed_history(repo)

    assert [m["id"] for m in repo.search_meetings("Calculo")] == ["calc"]
    assert repo.search_meetings("   ") == []

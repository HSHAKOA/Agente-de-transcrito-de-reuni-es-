from __future__ import annotations

from meeting_transcriber.live.dedup import merge_overlapping_text, normalize_words


def test_normalize_words_lowercases_and_strips_punctuation():
    assert normalize_words("Olá, Mundo!") == ["olá", "mundo"]


def test_mission_example_exact():
    previous = "Precisamos finalizar esse módulo"
    next_text = "esse módulo até sexta-feira"
    assert merge_overlapping_text(previous, next_text) == "até sexta-feira"


def test_no_overlap_returns_full_text():
    assert merge_overlapping_text("olá mundo", "texto totalmente diferente") == "texto totalmente diferente"


def test_full_duplicate_returns_empty_string():
    assert merge_overlapping_text("mesma frase exata", "mesma frase exata") == ""


def test_empty_previous_returns_full_next():
    assert merge_overlapping_text("", "texto novo") == "texto novo"


def test_empty_next_returns_empty():
    assert merge_overlapping_text("algo", "") == ""


def test_case_and_punctuation_insensitive_matching():
    previous = "precisamos FINALIZAR esse módulo."
    next_text = "Esse Módulo, até sexta-feira"
    assert merge_overlapping_text(previous, next_text) == "até sexta-feira"


def test_preserves_original_casing_and_punctuation_of_remainder():
    previous = "ola"
    next_text = "ola, Mundo! Como vai?"
    assert merge_overlapping_text(previous, next_text) == "Mundo! Como vai?"


def test_overlap_limited_to_max_overlap_words():
    # 15 palavras repetidas, mas max_overlap_words=12 por padrao -- so as
    # ultimas 12 sao candidatas a match, entao o resultado ainda remove
    # alguma coisa (nao trava/ignora so por passar do limite).
    words = " ".join(f"palavra{i}" for i in range(15))
    previous = words
    next_text = words + " extra"
    result = merge_overlapping_text(previous, next_text, max_overlap_words=12)
    assert "extra" in result


def test_single_word_overlap():
    assert merge_overlapping_text("isso é um teste", "teste de verdade") == "de verdade"


def test_no_spurious_match_on_common_short_words():
    # "e"/"de" aparecem em muito lugar -- a busca do MAIOR k primeiro evita
    # cortar de menos so por causa de uma palavra curta coincidente.
    previous = "o relatorio de vendas"
    next_text = "de producao aumentou"
    # "de" sozinho nao deveria bastar pra remover "producao aumentou"
    assert "producao" in merge_overlapping_text(previous, next_text)

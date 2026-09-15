"""Deduplicacao deterministica de texto entre janelas de transcricao ao
vivo ADJACENTES (Fase D, secao "D.3").

Janelas de baixa latencia tem uma pequena SOBREPOSICAO de audio de
proposito (evita cortar uma palavra bem na fronteira entre duas janelas
-- ver `window.py`), entao a MESMA fala pode aparecer no fim do texto da
janela anterior e no comeco do texto da janela seguinte. A estrategia
aqui e puramente lexica (nunca embeddings/heuristica fuzzy): normaliza as
duas pontas pra uma lista de palavras e acha a maior sufixo-prefixo em
comum -- determinístico, testavel, sem depender de reprocessar audio.
"""

from __future__ import annotations

import re
from typing import List

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


def normalize_words(text: str) -> List[str]:
    """Minusculas, sem pontuacao -- usado SO pra comparar sobreposicao,
    nunca pra decidir o texto final exibido (esse continua com a
    capitalizacao/pontuacao originais do Whisper)."""
    return _WORD_RE.findall(text.lower())


def merge_overlapping_text(previous_text: str, next_text: str, max_overlap_words: int = 12) -> str:
    """Remove de `next_text` o prefixo que repete o fim de `previous_text`
    (a mesma fala transcrita duas vezes por causa da sobreposicao entre
    janelas), preservando capitalizacao/pontuacao ORIGINAIS de `next_text`
    pro trecho que sobra.

    Exemplo (o mesmo da missao, secao D.3):
        previous_text = "Precisamos finalizar esse módulo"
        next_text     = "esse módulo até sexta-feira"
        -> "até sexta-feira"

    Se nao houver sobreposicao detectavel, devolve `next_text` inteiro
    (nunca tenta "adivinhar" uma seria descartando texto por engano).
    """
    prev_words = normalize_words(previous_text)
    next_words_raw = list(_WORD_RE.finditer(next_text))
    next_words_norm = [m.group(0).lower() for m in next_words_raw]

    max_k = min(max_overlap_words, len(prev_words), len(next_words_norm))
    for k in range(max_k, 0, -1):
        if prev_words[-k:] == next_words_norm[:k]:
            if k == len(next_words_raw):
                return ""
            # tudo depois da k-esima palavra reconhecida como duplicata,
            # preservando o texto ORIGINAL (com pontuacao) a partir dali.
            cut_at = next_words_raw[k].start()
            return next_text[cut_at:].strip()
    return next_text.strip()

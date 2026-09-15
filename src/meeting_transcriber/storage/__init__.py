"""Historico e busca (Fase E) -- ver `docs/DATABASE.md`.

Aditivo de proposito: NUNCA e chamado pelo caminho quente de gravacao
(`cli.py`/`recorder.py`), so por operacoes explicitas de historico
(importar sessoes existentes, listar, buscar). O filesystem continua
sendo a fonte de verdade original (metadata.json/state.json/transcript.md
de cada reuniao) -- o SQLite e um INDICE pesquisavel construido a partir
dele, nunca o unico lugar onde os dados existem.
"""

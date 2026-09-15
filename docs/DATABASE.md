# Histórico e busca (Fase E — escopo reduzido, ver limitações)

Código em `src/meeting_transcriber/storage/`. **Aditivo e somente-leitura
sobre o pipeline de gravação**: nada em `cli.py`/`recorder.py`/`webui.py`'s
`start_transcriber`/`stop_transcriber` foi tocado. O filesystem (pastas
por reunião, `metadata.json`/`state.json`/`transcript.md`) continua sendo
a fonte de verdade original — o SQLite é um **índice pesquisável**
construído a partir dele.

## Por que escopo reduzido

A missão original (E.1-E.13) pede schema completo (meetings, segments,
audio_chunks, schedules, action_items, decisions, topics, speakers,
transcription_jobs...), migração de schedules, FTS5, paginação e mais.
Implementar tudo isso E manter o rigor de teste já estabelecido no resto
do projeto (fakes, sem hardware, testes de concorrência) exigiria muito
mais tempo do que o restante desta sessão permite com segurança —
tentar entregar tudo raso teria um risco real de ficar "grande e
quebrado" (frase da própria missão). Prioridade escolhida: um núcleo
**funcional e testado de ponta a ponta** (histórico + busca), documentado
explicitamente como incompleto, em vez de um schema enorme sem cobertura
de teste real.

**Implementado:** tabelas `meetings` e `meeting_segments`, importação
idempotente do filesystem, busca (FTS5 com fallback `LIKE`), listagem
paginada/filtrada, soft delete.

**Não implementado** (ver `docs/PENDENCIAS.md`): `audio_chunks` /
`transcription_jobs` como tabelas próprias (o filesystem já rastreia
isso via `state.json`), migração de `schedules.json` para SQLite (o
scheduler da Fase C.1 continua em JSON — funcional, sem necessidade
imediata de migrar), `action_items`/`decisions`/`topics`/`speakers` como
tabelas (dependem da Fase G/H, que também não foram implementadas).

## Schema (versão 1)

```sql
meetings (
  id TEXT PRIMARY KEY,              -- meeting_id (nome da pasta)
  title, status, started_at, finished_at, duration_seconds,
  root_directory, meeting_directory,
  language, model,
  system_audio_enabled, system_device_id, system_device_name,
  microphone_enabled, microphone_device_id, microphone_device_name,
  deleted_at,                       -- soft delete; NUNCA apaga a linha
  created_at, updated_at
)

meeting_segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  meeting_id REFERENCES meetings(id) ON DELETE CASCADE,
  sequence, start_seconds, end_seconds,
  speaker_label,                    -- rotulo de CANAL (Fase H leve, ver abaixo), nunca um nome de pessoa
  text, created_at
)
-- + search_index (FTS5, opcional -- ver "Busca")
```

Migrations são uma lista versionada em `storage/db.py:MIGRATIONS`, nunca
`CREATE TABLE IF NOT EXISTS` espalhado — uma tabela `schema_version`
registra o que já foi aplicado; `connect()` roda `migrate()` toda vez
(idempotente).

## Importação (filesystem → SQLite)

`storage/import_filesystem.py:import_meeting`/`import_all` — leem
`metadata.json`/`state.json` (via `session.py`, inalterado) e fazem
*parsing* do `transcript.md` (regex sobre as linhas `**[HH:MM:SS]**
texto` que `MarkdownWriter` já escreve) para extrair os segmentos.
**Limitação conhecida**: o `.md` nunca guardou o fim de cada segmento,
só o início — `end_seconds` é aproximado pelo início do segmento
seguinte (ou igual ao próprio início, no último segmento de cada
reunião). Uma gravação futura que escrevesse direto no banco teria os
dois timestamps exatos; isso não foi feito nesta fase para não alterar o
caminho de gravação já testado.

Idempotente (`upsert_meeting` + `replace_segments` substituem, nunca
duplicam) e resiliente por item: uma pasta corrompida nunca interrompe a
importação das demais (`ImportResult.ok=False` só para aquela).
Disparada explicitamente via `POST /api/meetings/import` — nunca
automática no boot do painel (evita trabalho de fundo surpresa).

## Rótulo de "speaker" (Fase H, versão leve)

Nunca um nome de pessoa (a missão proíbe explicitamente inventar
"João"/"Maria" sem evidência real). Só o CANAL de origem, já disponível
desde a Fase C:

| Config da reunião | `speaker_label` |
|---|---|
| Só microfone | `Você` |
| Só sistema | `Áudio da reunião` |
| Sistema + microfone (mixado) | `Reunião` |

Diarização de verdade (distinguir vozes dentro do mesmo canal) fica como
pendência (Fase H completa — ver `docs/PENDENCIAS.md`).

## Busca

FTS5 se o SQLite do ambiente foi compilado com esse módulo (checado em
runtime, não assumido); fallback automático para `LIKE` sobre
`meetings.title`/`meeting_segments.text` caso contrário — nunca uma
dependência externa (Elasticsearch, etc.). A entrada do usuário nunca é
concatenada na consulta SQL (sempre parâmetro `?`); ao usar FTS5, cada
palavra é colocada entre aspas antes de virar o operando MATCH, evitando
que sintaxe especial do FTS5 (`*`, `-`, `OR`, parênteses) seja
interpretada como operador em vez de texto literal (testado
explicitamente com uma consulta cheia desses caracteres).

## API

`GET /api/meetings` (lista paginada, filtro `status`, busca `q`),
`GET /api/meetings/<id>` (detalhe + segmentos), `POST /api/meetings/import`,
`POST /api/meetings/<id>/delete` (soft delete) — ver `docs/API.md`.

## Exclusão

Somente soft delete (`deleted_at`) — nenhum arquivo real é tocado, nunca
(testado explicitamente: `test_delete_meeting_never_touches_real_files`).
Reverter uma exclusão exigiria hoje uma chamada direta ao repositório
(sem endpoint de "restaurar" ainda — pendência menor).

## Testado

51 testes novos (`tests/test_storage_*.py` + `tests/test_webui.py`,
seção "Fase E"): migrations idempotentes, CRUD completo, paginação,
filtro por status, soft delete (nunca remove a linha, nunca dupla-conta),
busca (título, segmento, exclusão de deletadas, caracteres especiais do
FTS5), parsing de markdown (incluindo cabeçalho/rodapé ignorados),
rótulo de canal (todas as combinações, nunca um nome inventado),
importação idempotente, resiliência a pasta corrompida, importação via
`webui.py` com uma sessão real criada por `MeetingSession`. Todos com
SQLite real (arquivo temporário) — nunca um dublê de banco, já que
`sqlite3` é biblioteca padrão e rápido o suficiente para não precisar.

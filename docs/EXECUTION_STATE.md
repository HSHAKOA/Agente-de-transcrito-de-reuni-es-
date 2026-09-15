# Estado de execução (checkpoint entre fases)

Atualizado ao fim de cada fase concluída nesta sessão longa. Ver também
`docs/HANDOFF_PROXIMA_SESSAO.md` (criado ao final da sessão).

## HEAD atual

Ver `git log -1` — última entrada: wiring da transcrição ao vivo (Fase D)
em `webui.py`/`cli.py`.

## Fase atual

E (SQLite + histórico) — a seguir.

## Última fase concluída

**Fase D — Transcrição quase em tempo real**: núcleo completo e testado.

- `src/meeting_transcriber/live/`: `window.py` (janelas de 8s com
  sobreposição, timestamps por contagem de amostra), `dedup.py`
  (deduplicação lexical determinística no ponto de sobreposição),
  `segments.py`/`transcript.py` (provisional vs. committed, substituição
  por intervalo de tempo, backlog LIVE/PROCESSING/BEHIND, latência média),
  `pipeline.py` (fila com backpressure + retry, nunca bloqueia a
  captura), `whisper_adapter.py` (liga ao Whisper real).
- `whisper_config.py`: presets FAST/BALANCED/ACCURATE/MAXIMUM,
  `resolve_device()` com fallback seguro pra CPU se CUDA não disponível.
- `cli.py`: pipeline ao vivo roda em paralelo à transcrição durável
  (inalterada); `commit_range` substitui previas pelo resultado real a
  cada chunk fechado; flush final ao parar; nunca derruba a gravação se
  o modelo ao vivo falhar ao carregar.
- `audio/dual_capture.py`: `on_raw_block` novo (aditivo) para viabilizar
  a previa ao vivo em modo dual (system+microfone) — sem "mixed" em
  tempo real ainda (documentado como limitação, ver
  `docs/LIVE_TRANSCRIPTION.md`).
- `webui.py`: `GET /api/transcription/live` + `GET /api/transcription/stream`
  (SSE), mesmo padrão dos endpoints de áudio.
- **Sem UI em `index.html`** — mesma decisão da Fase C.1 (Fase F substitui
  por React).
- Testado com dublês (78+ testes novos) e com hardware real (smoke test
  manual: pipeline completo funcionando de ponta a ponta com Whisper
  "tiny" real; conteúdo de texto com fala real sobrepondo duas janelas
  **não foi observado com hardware**, só coberto por testes com dublês —
  ver `docs/LIVE_TRANSCRIPTION.md`, seção "Testado").

## Fase anterior

**Fase C.1 — Agendamento de gravações**: completa e testada.

- `src/meeting_transcriber/scheduling/`: `clock.py`, `models.py`,
  `recurrence.py`, `store.py`, `validation.py`, `conflicts.py`,
  `service.py`, `engine.py`.
- Wiring completo em `webui.py`: `GET/POST /api/schedules`,
  `POST /api/schedules/<id>` (editar), `.../cancel`, `.../start-now`,
  `.../ignore-missed`. Motor sobe em `main()` só depois do bind da porta
  (mesma ordem de `mark_interrupted_sessions`).
- `start_transcriber` ganhou `meetings_root` (por agendamento) e
  `persist_as_default` (config de agendamento nunca vira preferência
  global) — mudança backward-compatible.
- Documentado em `docs/SCHEDULING.md`; rotas em `docs/API.md`.
- **Sem UI em `index.html`** — decisão deliberada: a Fase F substitui o
  HTML legado por React, e o próprio roteiro da missão (F.8) já espera
  "Schedules" como tela React consumindo esta API. Construir uma UI HTML
  hoje seria trabalho descartável.
- Dependências novas: `tzdata`, `tzlocal` (timezone IANA correto no
  Windows — justificado em `docs/SCHEDULING.md`).
- **Nível 2 (Windows Task Scheduler para iniciar com o app fechado) não
  implementado** — pendência documentada em `docs/SCHEDULING.md` e
  `docs/PENDENCIAS.md`.

## Testes passando

441 (backend, `pytest -q`, 2 execuções seguidas sem flakiness) antes de
começar a Fase D. Cobertura da Fase C.1: 89 testes de módulo (clock,
models/store, recurrence, validation, conflicts, service, engine — todos
com `ManualClock`, sem esperar segundo real nenhum) + 13 testes de
integração via `webui.py`.

## Decisões arquiteturais (C.1)

- Persistência: um `schedules.json` atômico, fora de qualquer
  `meetings_root` (é config do app, não conteúdo de reunião) — interface
  pequena (`list/get/save/delete`) pensada para trocar por SQLite na Fase
  E sem tocar quem chama.
- `Schedule` (regra) e `ScheduleRun` (ocorrência concreta) são entidades
  separadas — `ScheduleRun` só guarda o vínculo com a `MeetingSession`
  real, nunca duplica o estado dela.
- Motor movido a tick (nunca `sleep()`/`Timer` calculado por duração) —
  autocorrige mudança de relógio/DST/suspensão no próximo tick.
- Ações manuais (`start_now`/`ignore_missed`) reusam o mesmo `_try_start`
  do disparo automático — uma única implementação de "começar a gravar".

## Bugs encontrados e corrigidos (C.1)

1. `next_occurrence` calculava a janela de busca de 366 dias a partir de
   `after` (podia ser uma data bem no passado), nunca alcançando a âncora
   real do agendamento — corrigido ancorando a busca em
   `max(after, ancora)`.
2. Motor de agendamento chamava `check_folder_health` sem criar a pasta
   primeiro (diferente de `start_transcriber`) — um agendamento apontando
   pra uma pasta nova nunca passaria no preflight. Corrigido replicando o
   `mkdir(parents=True, exist_ok=True)`.

## Limitações conhecidas (C.1)

Ver `docs/SCHEDULING.md`, seção final.

## Próxima tarefa

Fase E (SQLite + histórico): schema versionado, camada de repositório,
migração idempotente das sessões existentes em filesystem (e dos
schedules em JSON) para SQLite, busca (FTS5 se disponível), paginação,
soft delete. Ver `docs/PENDENCIAS.md` para o estado real ao fim desta
sessão (nem toda fase D-I recebeu o mesmo nível de profundidade — ver
priorização documentada lá).

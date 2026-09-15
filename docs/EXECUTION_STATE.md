# Estado de execução (checkpoint)

Snapshot do estado real ao final desta sessão. Para o histórico
narrativo de cada fase, ver `CHANGELOG.md` e `git log`; para o detalhe
técnico de cada uma, `docs/<FASE>.md` (`SCHEDULING`, `LIVE_TRANSCRIPTION`,
`DATABASE`); para o que falta, `docs/PENDENCIAS.md`; para a continuação
exata, `docs/HANDOFF_PROXIMA_SESSAO.md`.

## HEAD atual

Ver `git log -1` no momento da leitura — última entrada desta sessão é a
organização de GitHub/documentação (README, CHANGELOG, CI, fluxogramas).

## Fases concluídas nesta sessão

| Fase | Status | Doc |
|---|---|---|
| C.1 — Agendamento | Completa, testada, sem UI | `docs/SCHEDULING.md` |
| D — Transcrição ao vivo | Núcleo completo, testado | `docs/LIVE_TRANSCRIPTION.md` |
| E — SQLite + histórico | Escopo reduzido, funcional | `docs/DATABASE.md` |
| F — React | Só toolchain + cliente tipado | `docs/PENDENCIAS.md` |
| H (leve) — Speaker por canal | Aplicado na importação (E) | `docs/DATABASE.md` |
| I (parcial) — Exportações | md/txt/json/srt/vtt | `docs/API.md` |
| G — Inteligência | Não iniciada | `docs/PENDENCIAS.md` |

## Testes

Suite completa (`pytest -q`) verde, rodada 2x seguidas sem flakiness ao
final da sessão — ver a mensagem do relatório final da missão para o
número exato de testes. Frontend: `npm run build` (tsc + vite) e
`npx oxlint` verdes.

## Decisões arquiteturais que atravessam várias fases

- Todo subsistema com dependência de hardware/tempo real recebe uma
  abstração injetável (`Clock` em `scheduling/`, `backend=None` em
  `audio/devices.py`, `transcribe_window` callable em `live/pipeline.py`)
  — a suite inteira roda sem hardware e sem esperar tempo real.
- Motores movidos a tick/polling (nunca `sleep()`/`Timer` calculado por
  uma duração) — scheduler e detecção de fim de gravação se
  autocorrigem a cada verificação, nunca dependem de um timer criado
  numa sessão anterior.
- Toda persistência nova (`schedules.json`, `meetings.db`) é ADITIVA:
  nenhuma mudança nesta sessão tocou `cli.py`'s loop principal de
  gravação/transcrição durável, que continua exatamente como testado
  nas fases anteriores.
- Nenhuma fase declarada "completa" sem also documentar explicitamente o
  que ficou de fora (ver a seção final de cada `docs/<FASE>.md`).

## Bugs reais encontrados e corrigidos nesta sessão

1. **C.1** — `next_occurrence` (recorrência) media a janela de busca de
   366 dias a partir de `after`, que podia ser uma data no passado
   distante, nunca alcançando a data real do agendamento. Corrigido
   ancorando a busca em `max(after, âncora do agendamento)`.
2. **C.1** — motor do scheduler chamava `check_folder_health` sem criar a
   pasta primeiro (diferente de `start_transcriber`); um agendamento
   apontando pra uma pasta nova nunca passaria no preflight. Corrigido
   replicando o `mkdir(parents=True, exist_ok=True)`.
3. **Webui** — leitura de `state["proc"]` em `test_audio` sem
   `state_lock` (race check-then-act), encontrada na revisão de
   concorrência da Fase C, corrigida antes de iniciar C.1.

## Próxima tarefa

Ver `docs/HANDOFF_PROXIMA_SESSAO.md`.

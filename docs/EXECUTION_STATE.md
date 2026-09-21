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

> Tabela do **Checkpoint 1** (histórica). Onde a Fase F e o agendamento
> aparecem sem UI/só com toolchain, isso foi superado pelo Checkpoint 2 e
> pelos seguintes — o estado vigente está no último checkpoint deste arquivo.

| Fase | Status | Doc |
|---|---|---|
| C.1 — Agendamento | Completa, testada (a UI veio depois, na Fase F) | `docs/SCHEDULING.md` |
| D — Transcrição ao vivo | Núcleo completo, testado | `docs/LIVE_TRANSCRIPTION.md` |
| E — SQLite + histórico | Escopo reduzido, funcional | `docs/DATABASE.md` |
| F — React | Na época só toolchain + cliente tipado; hoje 7 telas ativas | `docs/PENDENCIAS.md` |
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

---

## Checkpoint 2 — Correção pós-auditoria

Sessão seguinte, disparada por uma auditoria independente
(`auditoria_gemini.md`) que avaliou o estado do checkpoint anterior e
encontrou 5 problemas P1 reais bloqueando uma demonstração confiável,
apesar do núcleo (áudio, transcrição, scheduler, storage) já estar
sólido. Escopo desta sessão: só corrigir os achados da auditoria, nunca
adicionar feature nova (Intelligence/diarização completa/packaging
ficaram explicitamente fora, como já estavam).

### Achados confirmados e corrigidos

| # | Achado | Confirmado como | Correção |
|---|---|---|---|
| P1-1 | Navegação ejetava da tela de Gravação | Real — `App.tsx` checava `status.running` do poll anterior no mesmo render do `onStarted()` | Estado de transição explícito `recording.phase: starting/active`, sem timeout |
| P1-2 | Histórico nunca populado sozinho | Real — nenhuma tela chamava `POST /api/meetings/import` | `_reader_thread` chama `import_meeting` automaticamente ao detectar o fim do processo |
| P1-3 | `webui.py` não servia o React | Real — só `ROOT/index.html` era servido | `_serve_app`: serve `frontend/dist` com fallback SPA quando o build existe |
| P1-4 | Leituras do SQLite sem lock | Real — reproduzido de propósito (`sqlite3.InterfaceError` sob 15+ threads concorrentes) antes de corrigir | Todo método de `MeetingRepository` agora serializado pelo mesmo lock |
| P1-5 | Duplo "Parar" sem proteção | Real — nenhum estado impedia um 2º `POST /api/stop` | `state["stopping"]` explícito, recusa (409) segundo pedido |

Achados P2 do mesmo relatório também corrigidos: estado residual de
áudio/transcrição após parar (checava só `meeting_dir`, não `proc`);
`open_folder` restrito à raiz ativa (agora aceita qualquer raiz
conhecida); recorrência semanal do `ScheduleForm` truncava dias
silenciosamente (agora troca pra `custom_days` visivelmente); CSRF local
via `Origin` ausente; comando completo do subprocesso vazando pro log
exposto via API; fallback de `transcript.md` ausente na importação;
`PytestUnhandledThreadExceptionWarning` real num teste de captura dupla
(corrigido na camada certa — `dual_capture.py`, não `recorder.py`, que
tem um contrato diferente e um teste dedicado confirmando isso).

### Testes

`pytest -q`: 608 passando (era 603 no checkpoint anterior — 5 novos:
fallback de transcript.md + 4 de concorrência real do SQLite). Frontend
ganhou `vitest` pela primeira vez: 26 testes em 6 arquivos, cobrindo
exatamente os fluxos que a auditoria apontou como frágeis. Smoke test
end-to-end (HTTP real, servidor real, subprocesso simulado) verificou o
fluxo crítico completo antes de encerrar a sessão — ver
`docs/HANDOFF_PROXIMA_SESSAO.md` para o detalhe.

### Decisão consciente não tomada

`frontend/dist/` permanece fora do controle de versão (decisão
pré-existente do `.gitignore`, não revertida nesta sessão) — significa
que um checkout novo do repositório precisa rodar `npm run build` uma
vez antes de `iniciar.bat` mostrar o React (documentado em
`docs/APRESENTACAO_PROFESSOR.md`). Considerado versionar o build pra
garantir "iniciar.bat → React" funcionar em qualquer clone sem depender
de Node instalado na máquina da demonstração, mas isso reverteria uma
decisão de higiene de repositório já tomada deliberadamente antes, sem
ter sido pedido — registrado aqui como uma escolha explícita, não um
esquecimento.

### Próxima tarefa

Ver `docs/HANDOFF_PROXIMA_SESSAO.md`.

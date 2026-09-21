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

---

## Checkpoint 3 — Retomada (auditoria de estado + correções)

Sessão que partiu de `cc9c095` (Git limpo e sincronizado com `origin`) para
reconstruir o estado real antes de implementar. Nenhum documento anterior
registrava o estado do CI, e a verificação mostrou que o **CI do GitHub nunca
esteve verde** (9/9 execuções falharam). Detalhe dos achados e das provas em
`docs/HANDOFF_PROXIMA_SESSAO.md`; pendências em `docs/PENDENCIAS.md`.

### Baseline medido antes de mexer em código

| Verificação | Resultado |
|---|---|
| `pytest -q` | 608 passed, 4 warnings (`SoundcardRuntimeWarning`: 4 testes tocavam a placa de som real) |
| `npm test` | 26 passed em 6 arquivos (a 1ª tentativa estourou o timeout dos workers por rodar junto com o pytest; isolado passou) |
| `npm run build` | ok |
| `npx oxlint` | 0 erros, 5 avisos `set-state-in-effect` |
| CI remoto (`gh run list`) | **9 de 9 `failure`** (4 testes no runner Windows) |

### Depois

| Verificação | Resultado |
|---|---|
| `pytest -q` (fuso normal **e** `TZ=UTC0`) | **650 passed**, 0 warnings de hardware nos testes não-hardware |
| `npm test` | **79 passed em 11 arquivos** |
| `npm run build` / `npx oxlint` | ok / 0 erros, os mesmos 5 avisos |
| CI remoto | **não verificado** — nenhum commit foi enviado |

### Matriz de estado

| Área | Estado | Testado | Observação |
|---|---|---|---|
| Storage (pastas, sessões, settings) | PRONTO | sim | layout `chunks/` (uma fonte) ou `audio/{system,microphone,mixed}/` (simultânea) |
| Audio | PRONTO | dublês + `*_hardware.py` | não revalidado com hardware nesta sessão |
| Recovery | PRONTO | sim | marca imediata + banner no React; **nunca com uma gravação longa real desde a correção** |
| Scheduler | PRONTO (em JSON) | sim | só dispara com o painel aberto; mensagens agora no fuso do agendamento |
| Transcription | PRONTO | sim | encerramento gracioso ciente de progresso |
| Live transcription | PRONTO (núcleo) | sim | dedup lexical; limites de backlog fixos |
| SQLite | PRONTO (escopo reduzido) | sim | só `meetings`, `meeting_segments`, `search_index`, `schema_version`; sem tabelas de análise |
| History | PRONTO | sim (repositório, API, tela) | 3 reuniões-fantasma no banco real (ver P2-12) |
| Search | PRONTO | sim | FTS5 com fallback `LIKE` escapado; paginada e combinável |
| React | PRONTO | 79 testes | 8 telas + banner; acessibilidade PARCIAL |
| Intelligence (G) | AUSENTE | — | projeto em `docs/INTELLIGENCE.md` |
| Speakers (H) | PARCIAL | sim | rótulo por reunião, não por segmento |
| Exports | PARCIAL | sim | md/txt/json/srt/vtt; sem DOCX/PDF |
| Packaging | AUSENTE | — | `iniciar.bat`; `frontend/dist/` não versionado |
| Tests | PRONTO | 650 + 79 | hermeticidade verificada (`TZ=UTC0`, sondas de áudio proibidas) |
| Security | PRONTO para o modelo local | sim | ver `docs/SECURITY.md`; sem autenticação (aceito) |
| Documentation | PRONTO para o tocado | — | `ARCHITECTURE.md` reescrito; ver P1 do handoff |

### Decisão consciente não tomada

Nenhum `git push`: publicar em `origin/main` não estava autorizado
explicitamente. Nenhum `LICENSE`, `CODE_OF_CONDUCT.md` ou contato de segurança
foi criado: são decisões do proprietário. Nada nas pastas de reunião reais foi
modificado.

### Próxima tarefa

Ver `docs/HANDOFF_PROXIMA_SESSAO.md`.

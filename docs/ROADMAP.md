# Roadmap — evolucao para Meeting Intelligence local-first

Ordem de execucao definida (ver missao original). Cada fase so comeca depois
da anterior estar implementada, testada e revisada — nao pular etapas.

- [x] **Fase A — Auditoria.** `docs/AUDITORIA_V2.md`.
- [x] **Fase B — Storage, sessoes, recovery, graceful shutdown.** Graceful
      shutdown (sinal em vez de kill duro, com escalonamento
      terminate->kill so se necessario), validacao de entrada da API
      (`meeting_transcriber.validation`), modelo de sessao persistente
      (`meeting_transcriber.session`), deteccao + reprocessamento de sessao
      interrompida, correcao do bug de hang quando o dispositivo de audio
      falha ao abrir. Escolha de pasta: o usuario escolhe onde as reunioes
      ficam salvas (seletor nativo via `folder_dialog.py`, persistido em
      `meeting_transcriber.settings`), cada reuniao vira uma pasta legivel
      (`AAAA-MM-DD_HHMM_Titulo_xxxxxx`) dentro dessa raiz, com checklist de
      saude (existe/e pasta/tem espaco/e gravavel) antes de iniciar, e botao
      "Abrir pasta". O campo `output` (nome de arquivo livre) foi removido
      da API — o path traversal que existia nele foi eliminado por
      construcao. Ver `docs/ARCHITECTURE.md`, `docs/RECOVERY.md`,
      `docs/SECURITY.md`.
- [x] **Fase C — Áudio.** Captura de microfone + loopback do sistema
      simultaneamente (canais separados), seleção de dispositivo, medidor de
      nível de áudio (RMS, SSE), checagem de saúde do áudio antes de
      iniciar a sessão. Ver `docs/API.md`.
- [x] **Fase C.1 — Agendamento de gravações.** Schedules com recorrência
      (once/daily/weekdays/weekly/custom_days), início/fim automático,
      preflight, detecção de conflito, "missed"/"failed" com tolerância,
      início/parada manual, persistência atômica em JSON. Motor movido a
      tick (nunca `sleep()` calculado por duração). **Sem UI** ainda (fica
      pra Fase F) e **sem Nível 2** (Windows Task Scheduler pra iniciar com
      o app fechado — documentado como pendência). Ver `docs/SCHEDULING.md`.
- [x] **Fase D — Transcrição quase ao vivo** (núcleo). Janelas de baixa
      latência (8s, sobreposição de 1,5s) separadas dos chunks duráveis
      (30-120s); segmentos provisórios substituídos pelos definitivos por
      intervalo de tempo; deduplicação determinística por sobreposição de
      texto; backlog LIVE/PROCESSING/BEHIND observável; presets de modelo
      (FAST/BALANCED/ACCURATE/MAXIMUM) com fallback seguro de CUDA. Captura
      nunca depende da velocidade do Whisper (testado). Ver
      `docs/LIVE_TRANSCRIPTION.md`.
- [x] **Fase E — SQLite + histórico** (escopo reduzido, documentado).
      `meetings`/`meeting_segments` com migrations versionadas, importação
      idempotente do filesystem, busca (FTS5 com fallback `LIKE`), listagem
      paginada/filtrada, soft delete. **Não fez**: migrar `schedules.json`
      pra SQLite, tabelas de `action_items`/`decisions`/`topics`/`speakers`/
      `transcription_jobs` (dependem de fases G/H não implementadas). Ver
      `docs/DATABASE.md`.
- [~] **Fase F — Migração do frontend para React.** Toolchain funcionando
      (Vite + React 19 + TypeScript + Tailwind v4, `npm run build`
      verificado) e cliente HTTP tipado (`frontend/src/services/api.ts`,
      `frontend/src/types/api.ts`) cobrindo **todo** o contrato real atual
      (status/settings/recovery + áudio C + agendamento C.1 + transcrição
      ao vivo D + histórico/export E). **Nenhuma tela de produto foi
      construída ainda** (Dashboard/Nova reunião/Gravação/Histórico/
      Agendamentos/Configurações) — `index.html`/`webui.py` continuam
      sendo a interface real e ativa. Próximo passo concreto documentado em
      `docs/PENDENCIAS.md`/`docs/HANDOFF_PROXIMA_SESSAO.md`.
- [ ] **Fase G — Inteligência.** Não implementada. Arquitetura plugável
      (provider de resumo/decisões/tarefas/tópicos, Ollama/OpenAI/
      Anthropic/Gemini opcionais) fica documentada como próximo passo, não
      código — ver `docs/PENDENCIAS.md`.
- [~] **Fase H — Diarização** (versão leve). Rótulo de speaker por CANAL
      (`Você` = microfone, `Áudio da reunião` = sistema, `Reunião` = ambos)
      aplicado na importação pro histórico (Fase E) — nunca um nome de
      pessoa inventado. Diarização de verdade (distinguir vozes dentro do
      mesmo canal) não implementada.
- [x] **Fase I — Exportações** (parcial). Markdown/TXT/JSON/SRT/VTT,
      gerados sob demanda a partir do histórico (Fase E), sem gravar em
      disco. **Não fez**: DOCX/PDF (explicitamente opcional/condicionado a
      tempo na missão), empacotamento Windows de um clique (PyInstaller/
      Nuitka — `iniciar.bat` continua sendo o fluxo de início real e
      funcional).

Legenda: `[x]` concluída, `[~]` parcial (ver a nota da fase), `[ ]` não
iniciada. Nenhuma fase marcada `[x]` significa "100% do escopo original da
missão" — cada uma documenta explicitamente o que ficou de fora.

## Definition of Done da V2 (resumo)

Gravar reuniao longa, capturar computador + microfone, mostrar se o audio
esta chegando, transcrever quase em tempo real sem perder audio se o Whisper
atrasar, encerrar sem perder bloco parcial, recuperar sessao interrompida,
guardar e pesquisar historico, gerar resumo/tarefas/decisoes, exportar —
tudo local, sem servico pago obrigatorio, sem depender de internet pro uso
normal. A interface (React, Fase F) so substitui o painel HTML atual depois
de demonstrar paridade funcional completa — nenhum recurso existente pode
desaparecer durante a migracao.

**Estado real (ver `docs/PENDENCIAS.md` para o detalhe completo):** tudo
acima está feito, exceto "gerar resumo/tarefas/decisões" (Fase G, não
implementada) e a própria interface React (Fase F: toolchain e cliente
tipado prontos, telas de produto ainda não construídas).

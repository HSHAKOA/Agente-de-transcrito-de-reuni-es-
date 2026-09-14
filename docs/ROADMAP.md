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
- [ ] **Fase C — Audio.** Captura de microfone + loopback do sistema
      simultaneamente (canais separados), selecao de dispositivo, medidor de
      nivel de audio na interface, checagem de saude do audio antes de
      iniciar a sessao.
- [ ] **Fase D — Transcricao quase ao vivo.** Separar janela de transcricao
      "quase em tempo real" da persistencia do chunk completo; fila e
      backlog de transcricao visiveis na interface; abstracao de engine
      Whisper (presets, modo avancado, deteccao de CUDA indisponivel).
- [ ] **Fase E — SQLite + historico.** Persistencia estruturada
      (`meetings`, `meeting_segments`, `audio_chunks`, ...), tela de
      historico de reunioes, busca textual.
- [ ] **Fase F — Migracao do frontend para React.** `index.html` +
      JavaScript puro e substituido por React + TypeScript + Vite +
      Tailwind CSS (sem Next.js — nao ha necessidade de SSR/rotas
      server-side num app local-first controlado por backend Python).
      Design system, Dashboard, Nova reuniao, Gravacao, Historico, Tela da
      reuniao, Configuracoes. So comeca depois de C/D/E porque a API vai
      crescer bastante nessas fases — construir telas de produto antes
      significaria refazer boa parte do trabalho depois. **Preparacao
      arquitetural ja iniciada** (permitido pela missao mesmo antes da fase
      comecar de fato): `frontend/` contem o toolchain funcionando
      (Vite + React 19 + TypeScript + Tailwind v4, `npm run build` verificado)
      e um cliente HTTP tipado (`src/services/api.ts`,
      `src/types/api.ts`) para o contrato **real** atual da API — nao e o
      frontend ativo ainda; `index.html`/`webui.py` continuam sendo a
      interface do produto ate a paridade funcional ser demonstrada. Ver
      `frontend/README.md`.
- [ ] **Fase G — Inteligencia.** Pipeline desacoplado de resumo, decisoes,
      tarefas e topicos — funcionando sem exigir nenhuma IA generativa
      configurada; arquitetura plugavel para engines futuras (Ollama,
      OpenAI, Anthropic, Gemini).
- [ ] **Fase H — Diarizacao.** Planejada sem acoplar a stack inteira a uma
      biblioteca especifica; documentar a decisao tecnica antes de
      implementar.
- [ ] **Fase I — Exportacoes + empacotamento.** TXT/JSON/SRT/VTT (e depois
      DOCX/PDF); instalador Windows de um clique.

## Definition of Done da V2 (resumo)

Gravar reuniao longa, capturar computador + microfone, mostrar se o audio
esta chegando, transcrever quase em tempo real sem perder audio se o Whisper
atrasar, encerrar sem perder bloco parcial, recuperar sessao interrompida,
guardar e pesquisar historico, gerar resumo/tarefas/decisoes, exportar —
tudo local, sem servico pago obrigatorio, sem depender de internet pro uso
normal. A interface (React, Fase F) so substitui o painel HTML atual depois
de demonstrar paridade funcional completa — nenhum recurso existente pode
desaparecer durante a migracao.

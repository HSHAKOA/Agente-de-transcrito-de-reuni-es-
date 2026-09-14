# Roadmap — evolucao para Meeting Intelligence local-first

Ordem de execucao definida (ver missao original). Cada fase so comeca depois
da anterior estar implementada, testada e revisada — nao pular etapas.

- [x] **Fase A — Auditoria.** `docs/AUDITORIA_V2.md`.
- [x] **Fase B — Nao perder reunioes.** Graceful shutdown (sinal em vez de
      kill duro, com escalonamento terminate->kill so se necessario),
      validacao de entrada da API (`meeting_transcriber.validation`),
      modelo de sessao persistente (`meeting_transcriber.session`),
      deteccao + reprocessamento de sessao interrompida, correcao do bug de
      hang quando o dispositivo de audio falha ao abrir. Escolha de pasta:
      o usuario escolhe onde as reunioes ficam salvas (seletor nativo via
      `folder_dialog.py`, persistido em `meeting_transcriber.settings`),
      cada reuniao vira uma pasta legivel (`AAAA-MM-DD_HHMM_Titulo_xxxxxx`)
      dentro dessa raiz, com checklist de saude (existe/e pasta/tem
      espaco/e gravavel) antes de iniciar, e botao "Abrir pasta". O campo
      `output` (nome de arquivo livre) foi removido da API — o path
      traversal que existia nele foi eliminado por construcao. Ver
      `docs/ARCHITECTURE.md`, `docs/RECOVERY.md`, `docs/SECURITY.md`.
- [ ] **Fase C — Dispositivos.** Captura de microfone + loopback do sistema
      simultaneamente (canais separados), selecao de dispositivo, medidor de
      nivel de audio na interface, checagem de saude do audio antes de
      iniciar a sessao.
- [ ] **Fase D — Streaming curto.** Separar janela de transcricao "quase em
      tempo real" da persistencia do chunk completo; backlog de transcricao
      visivel na interface; abstracao de engine Whisper (presets,
      modo avancado, deteccao de CUDA indisponivel).
- [ ] **Fase E — SQLite + historico.** Persistencia estruturada
      (`meetings`, `meeting_segments`, `audio_chunks`, ...), tela de
      historico de reunioes, busca textual.
- [ ] **Fase F — Inteligencia.** Pipeline desacoplado de resumo, decisoes,
      tarefas e topicos — funcionando sem exigir nenhuma IA generativa
      configurada; arquitetura plugavel para engines futuras (Ollama,
      OpenAI, Anthropic, Gemini).
- [ ] **Fase G — Diarizacao.** Planejada sem acoplar a stack inteira a uma
      biblioteca especifica; documentar a decisao tecnica antes de
      implementar.
- [ ] **Fase H — Nova UX.** So depois do motor e da persistencia estarem
      estaveis (fases C-F).
- [ ] **Fase I — Exportacoes + empacotamento.** TXT/JSON/SRT/VTT (e depois
      DOCX/PDF); instalador Windows de um clique.

## Definition of Done da V2 (resumo)

Gravar reuniao longa, capturar computador + microfone, mostrar se o audio
esta chegando, transcrever quase em tempo real sem perder audio se o Whisper
atrasar, encerrar sem perder bloco parcial, recuperar sessao interrompida,
guardar e pesquisar historico, gerar resumo/tarefas/decisoes, exportar —
tudo local, sem servico pago obrigatorio, sem depender de internet pro uso
normal.

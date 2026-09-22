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
      tick (nunca `sleep()` calculado por duração). A UI veio na Fase F
      (telas Agendamentos e criar/editar). **Sem Nível 2** (Windows Task
      Scheduler pra iniciar com o app fechado — documentado como
      pendência). Ver `docs/SCHEDULING.md`.
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
      paginada/filtrada, soft delete. Indexação **automática** ao final de
      toda gravação/reprocessamento (`webui.py:_reader_thread` chama
      `import_meeting` sozinho — correção pós-auditoria, antes disso o
      banco só era populado se alguém chamasse `POST /api/meetings/import`
      manualmente, o que a UI nunca fazia sozinha). Leituras concorrentes
      também protegidas por lock (antes só escritas tinham). **Não fez**:
      migrar `schedules.json` pra SQLite, tabelas de `action_items`/
      `decisions`/`topics`/`speakers`/`transcription_jobs` (dependem de
      fases G/H não implementadas). Ver `docs/DATABASE.md`.
- [x] **Fase F — Migração do frontend para React.** Toolchain (Vite +
      React 19 + TypeScript + Tailwind v4) e cliente HTTP tipado cobrindo
      **todo** o contrato real atual. **Todas as 7 telas da missão (F.3)
      construídas** e navegáveis de ponta a ponta: Dashboard, Nova Reunião
      (formulário completo, testar áudio, inicia gravações reais),
      Gravação (níveis de áudio + transcrição ao vivo via SSE, parar com
      estado "Finalizando..." explícito), Detalhe da Reunião (transcrição,
      exportação em 5 formatos), Agendamentos + criar/editar (recorrência
      completa, com correção automática de dias múltiplos em "semanal"),
      Configurações. **React é a interface ativa e padrão**: `webui.py`
      serve `frontend/dist/` automaticamente (correção pós-auditoria P1-3;
      antes só existia o painel legado). Bug de navegação que ejetava o
      usuário da tela de Gravação (P1-1) corrigido com um estado de
      transição explícito, sem timeout arbitrário. **Retomada:** tela de
      **Histórico** dedicada (busca, status, período, paginação), **banner de
      recuperação** com "Reprocessar" (o painel legado tinha, o React não) e a
      tela de Gravação diferencia um reprocessamento de uma gravação. Cada
      uma das telas tem teste de componente (vitest + testing-library; 79
      testes). Falta: exercitar os formulários de escrita contra um navegador
      real (feito via HTTP simulado/smoke test, nunca clicado numa aba real)
      e uma auditoria de acessibilidade. `index.html` continua existindo só
      como fallback quando o build não foi gerado — ver `docs/PENDENCIAS.md`.
- [ ] **Fase G — Inteligência.** Não implementada; **projeto em
      `docs/INTELLIGENCE.md`** (provider plugável, validador contra
      alucinação, modelo de dados, fatias G.1–G.4). Arquitetura plugável
      (provider de resumo/decisões/tarefas/tópicos, Ollama/OpenAI/
      Anthropic/Gemini opcionais) fica documentada como próximo passo, não
      código — ver `docs/PENDENCIAS.md`.
- [~] **Fase H — Diarização** (versão leve). Rótulo de speaker **por
      reunião**, derivado da configuração de captura (`Você` = só
      microfone, `Áudio da reunião` = só sistema, `Reunião` = ambos),
      aplicado na importação pro histórico (Fase E) — nunca um nome de
      pessoa inventado. **Limitação:** na captura simultânea (o caso
      principal) todos os segmentos recebem `Reunião`, porque o mixer junta
      os canais antes da transcrição; atribuição por segmento
      (microfone → `Você`) e por voz não estão implementadas.
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
normal. A interface React (Fase F) substituiu o painel HTML legado como
interface ativa e padrão depois de demonstrar paridade funcional completa
(8 telas navegáveis de ponta a ponta contra o backend real, servidas pelo
próprio `webui.py`, mais o banner de recuperação) — o painel legado continua
existindo só como fallback automático, nenhum recurso desapareceu na migração.

**Estado real (ver `docs/PENDENCIAS.md` para o detalhe completo):** tudo
acima está feito, exceto "gerar resumo/tarefas/decisões" (Fase G, não
implementada; projeto em `docs/INTELLIGENCE.md`). A interface React está
completa e ativa, com histórico paginado e recuperação de sessões
interrompidas.

## Marcos de versão

```text
V0.9 — Academic Demo                                        ✅ core funcional
V1.0 — Open Source Stable                                   ⏳ falta validação com hardware real
      histórico ✅ · testes ✅ · estrutura open source ✅ · licença ✅ · CI verde ✅ · estabilidade ✅
V1.1 — Meeting Intelligence      resumo, tarefas, decisões, tópicos      (docs/INTELLIGENCE.md)
V1.2 — Speakers                  atribuição por segmento; diarização opcional
V1.3 — Automação                 Windows Task Scheduler; integração com calendários (ICS/Google/Outlook)
V2.0 — Knowledge Base            busca semântica; chat com uma reunião / entre reuniões
```

Fechado desde o marco anterior: `LICENSE` (Apache-2.0, com a auditoria de
dependências em `docs/LICENSES.md`), relato privado de vulnerabilidade
habilitado, e o CI **verde** — pela primeira vez na história do projeto, e
agora sem nenhum aviso de depreciação.

O que ainda separa a V1.0 está em `docs/PENDENCIAS.md`: validar com
**hardware real** o encerramento gracioso e o reprocessamento (só rodaram
com dublês), e reprocessar a aula de 21/09 que ficou em 9/11 blocos. Nada de
V1.1+ entra antes disso.

### Trilha visual (paralela, não bloqueia a V1.0)

`DESIGN.md` e `MOTION.md` são a autoridade visual do produto. A
implementação vem depois do núcleo fechado, nesta ordem: tokens
centralizados no `index.css` (hoje o arquivo tem uma linha só), respeito a
`prefers-reduced-motion`, nomes acessíveis nos campos de formulário e
regiões vivas — os três primeiros itens de `docs/PENDENCIAS.md` P2-11.

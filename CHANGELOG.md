# Changelog

Resumo por fase/marco (ver `docs/ROADMAP.md` para o detalhe de escopo de
cada uma e `git log` para o histórico completo de commits).

## Licença, agendamento confiável e base visual (não lançado)

Sessão disparada por um agendamento real que **não gravou**. A investigação
virou o eixo da sessão: a mensagem exibida (*"O aplicativo não estava
disponível naquele horário"*) era falsa, e a causa real nunca chegava a
lugar nenhum. Reconstituição completa em `docs/SCHEDULING.md`.

### Corrigido

- **Preflight do agendamento não derruba mais o tick.** `_check_readiness`
  chamava a sonda de dispositivo direto, e ela levanta `AudioError` quando o
  backend de áudio não está disponível. A exceção atravessava o preflight,
  o `except Exception` do `tick_once` engolia, nada era salvo no agendamento
  e, 60 s depois, a ocorrência virava `missed` com a mensagem genérica de
  "app fechado" — porque a distinção `MISSED`/`FAILED` depende justamente do
  `error_message` que a exceção impediu de existir. Agora toda sonda vira
  veredito e a ocorrência termina em `FAILED` com a causa verdadeira.
- **Fuso que deixa de resolver não paralisa mais o agendamento em silêncio.**
  Sem `tzdata` (no Windows o `zoneinfo` não tem base própria),
  `next_occurrence` estourava em todo tick, para sempre. Agora a causa é
  registrada uma vez, `next_run_at` é zerado para a tela não prometer um
  horário impossível, e o agendamento volta sozinho quando a dependência
  retorna.
- **Medidor de nível não anima mais `width`.** Recebia amostra ~10x por
  segundo com `transition-[width]`: recálculo de layout por quadro numa
  máquina já a 100% de CPU transcrevendo, e a barra ficava atrasada em
  relação ao áudio que ela reporta.
- **Mensagens de inicialização legíveis no console do Windows** (eram ASCII
  quebrado sob cp1252, justamente onde precisam ser lidas).

### Adicionado

- **`LICENSE` (Apache-2.0)** — o repositório não tinha licença, ou seja,
  todos os direitos reservados. Escolhida após auditar 6 dependências de
  backend e 137 pacotes do frontend: nenhum copyleft forte, nenhum código de
  terceiros incorporado (`docs/LICENSES.md`).
- **`check_runtime_health()`** — o painel agora diz o que está faltando
  (pacote, fuso, build do React) **antes** de se anunciar pronto, em vez de
  subir normalmente e falhar só na hora da aula agendada.
- **`iniciar.bat` confiável** — checa Python antes de usar, recusa `.venv`
  incompleto e explica a ausência do build do React em vez de servir a
  interface legada em silêncio.
- **`DESIGN.md` e `MOTION.md`** — autoridade visual do produto. O
  `index.css` tinha uma linha só, sem token nenhum.
- **`prefers-reduced-motion`** respeitado (as utilidades de animação do
  Tailwind não respeitam sozinhas).

### Segurança

- *Private vulnerability reporting* habilitado no GitHub; `docs/SECURITY.md`
  descreve o canal e registra que nenhum e-mail é publicado de propósito.
- Actions atualizadas para v7 — fim dos avisos de depreciação do Node 20.

### Dados

- As 3 reuniões-fantasma deixadas por testes foram removidas do banco real
  pelo endpoint do próprio produto (soft delete, nenhum arquivo tocado),
  com backup e verificação de integridade antes e depois.

### Limitações conhecidas

- Transcrever durante a gravação **satura a CPU** (medido: 100% num
  i5-11400H, com `small` em CPU e blocos de 300 s). Nada se perde, mas o
  backlog cresce e o encerramento precisa drená-lo.
- Nenhum campo de formulário tem nome acessível (`docs/PENDENCIAS.md`,
  P2-11). Auditado, ainda não corrigido.

## Retomada — CI verde, recuperação e histórico (não lançado)

Reconstrução do estado real a partir de `cc9c095`, antes de implementar:

- **CI**: nunca esteve verde (9/9 execuções falharam no GitHub). Causas: um
  teste de agendamento sondava a placa de som real (o fixture não chegava ao
  default capturado no import do `SchedulerEngine`) e mensagens de horário
  usavam o fuso do PC em vez do fuso do agendamento. Corrigido, e o CI passa a
  rodar também `npm test`.
- **Recuperação**: uma sessão cujo processo morre sem finalizar é marcada
  `interrupted` na hora (antes só no boot do painel); o React ganhou o banner
  "Sessões interrompidas" com **Reprocessar**, que só existia no painel
  legado. `/api/status` ganhou `mode` (`record`/`resume`).
- **Encerramento**: a espera gracioso deixou de ser uma janela fixa de 30 s —
  um bloco de 300 s na fila do Whisper fazia todo "Parar" de gravação longa
  cair em `terminate()`. Agora acompanha o progresso do gravador
  (`max(30 s, chunk_seconds)`, reinicia a cada avanço, teto de 30 min).
- **Histórico**: `GET /api/meetings` combina busca, status e período
  (`date_from`/`date_to`, dias inclusivos), pagina também a busca e devolve um
  `total` consistente; data malformada responde `400`. O filtro de data
  antigo excluía o último dia inteiro. Nova tela **Histórico** no React.
- **Servidor**: uma requisição recusada por Host/Origin agora consome o corpo
  antes de responder (antes, um corpo tardio causava reset de conexão em vez do
  403/400).
- **Testes**: backend 608 → 650; frontend 26 → 79 (Recording, Schedules,
  Settings, History, RecoveryBanner). Testes de agendamento agora herméticos.
- **Segurança e higiene**: pastas de reunião ignoradas pelo Git em qualquer
  profundidade; testes deixaram de vazar reuniões-fantasma para o banco real;
  `docs/SECURITY.md` atualizado; templates de issue/PR.
- **Docs**: `ARCHITECTURE.md` reescrito (parava na Fase B), projeto do
  Meeting Intelligence (`docs/INTELLIGENCE.md`), plano de migração dos
  agendamentos, banner "Prévia (Fase F)" removido da interface.

## Correção pós-auditoria (React pronto para demo)

Uma auditoria independente encontrou 5 problemas P1 que impediam uma
demonstração confiável apesar do núcleo já estar sólido — todos
confirmados no código e corrigidos:

- Bug de navegação que ejetava o usuário da tela de Gravação de volta pro
  Dashboard (corrida entre polling de status e o clique de "Iniciar").
- Reuniões terminadas agora são indexadas automaticamente no histórico
  (antes exigia chamar um endpoint manual que nenhuma tela chamava).
- `webui.py` passa a servir o build de produção do React
  (`frontend/dist/`) como interface padrão — antes só o painel HTML
  legado era servido.
- Leituras do SQLite protegidas contra corrida (antes só escritas
  tinham lock; reproduzido um `sqlite3.InterfaceError` real sob carga
  concorrente antes de corrigir).
- Estado explícito de "parando" no backend: um segundo pedido de parar
  é recusado enquanto o primeiro ainda está em andamento; a UI mostra
  "Finalizando reunião..." em vez de assumir que parou na hora.

Também: validação de `Origin` em requests que mudam estado (CSRF
local), `open_folder` aceitando qualquer raiz de reuniões já conhecida
(não só a ativa), correção da recorrência semanal do formulário de
agendamento, fallback de importação quando o caminho do transcript
ficou desatualizado, e a primeira suíte de testes automatizados do
frontend (`vitest` + `testing-library`).

## Fase F — Frontend React

- Migração completa da interface pra React 19 + TypeScript + Vite +
  Tailwind CSS v4: 7 telas (Dashboard, Nova Reunião, Gravação, Detalhe
  da Reunião, Agendamentos + criar/editar, Configurações) navegáveis de
  ponta a ponta contra o backend real.

## Fase I — Exportações (parcial)

- Exportação sob demanda em Markdown, TXT, JSON, SRT e VTT a partir do
  histórico (Fase E), via `GET /api/meetings/<id>/export?format=...`.

## Fase E — SQLite + histórico (escopo reduzido)

- Índice SQLite pesquisável (`meetings`, `meeting_segments`) construído a
  partir das pastas de reunião existentes, sem tocar no pipeline de
  gravação. Importação idempotente, busca (FTS5 com fallback), listagem
  paginada/filtrada, soft delete.
- Rótulo de "quem falou" por canal (Fase H, versão leve): `Você`
  (microfone) / `Áudio da reunião` (sistema) / `Reunião` (ambos) —
  aplicado na importação, nunca inventando um nome de pessoa.

## Fase D — Transcrição quase em tempo real

- Pipeline de transcrição ao vivo (janelas de 8s, deduplicação
  determinística por sobreposição de texto) rodando em paralelo à
  transcrição durável por chunk, sem depender da velocidade dela.
- Presets de modelo Whisper (FAST/BALANCED/ACCURATE/MAXIMUM) e fallback
  seguro quando CUDA é pedido mas não está disponível.
- `GET /api/transcription/live` e `GET /api/transcription/stream` (SSE).

## Fase C.1 — Agendamento de gravações

- Agendamentos com recorrência (uma vez, diário, dias úteis, semanal,
  dias customizados), início/fim automático, preflight, detecção de
  conflito, tratamento explícito de horário perdido, início/parada
  manual antecipada — tudo reagindo a mudança de relógio/DST/suspensão
  do computador corretamente (motor movido a tick, nunca `sleep()`
  calculado por duração).

## Fase C — Áudio

- Captura simultânea de sistema (loopback) e microfone em canais
  separados, com mixagem por chunk, seleção de dispositivo, medidor de
  nível (SSE) e checagem de saúde antes de gravar.

## Fase B — Storage, sessões, recovery

- Escolha de pasta pelo usuário, uma pasta por reunião, checklist de
  saúde de armazenamento, encerramento gracioso com escalonamento
  (sinal → terminate → kill), detecção e reprocessamento de sessão
  interrompida, recuperação através de múltiplas raízes já usadas.

## Fase A — Auditoria

- Levantamento do estado inicial do projeto (`docs/AUDITORIA_V2.md`).

## Origem

- Agente de linha de comando: grava o áudio de saída do sistema e
  transcreve para Markdown com `faster-whisper`, em blocos contínuos.

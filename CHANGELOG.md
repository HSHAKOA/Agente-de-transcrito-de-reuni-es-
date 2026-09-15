# Changelog

Resumo por fase/marco (ver `docs/ROADMAP.md` para o detalhe de escopo de
cada uma e `git log` para o histórico completo de commits).

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

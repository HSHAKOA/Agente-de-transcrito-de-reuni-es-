# Handoff para a próxima sessão

# Estado atual

HEAD: ver `git log -1` (última entrada desta sessão: organização de
GitHub/documentação — commits anteriores cobrem exports, storage,
webui wiring, live transcription, scheduling, nessa ordem reversa).
Branch: `main`.

## O que está 100% pronto

- Captura de áudio real: sistema (loopback WASAPI) + microfone,
  simultânea, com seleção de dispositivo, health check, medidor de nível
  (SSE) — Fase C.
- Agendamento de gravações: recorrência, início/fim automático,
  preflight, conflito, missed/failed, start/stop manual — Fase C.1. Sem
  UI (ver pendências).
- Transcrição quase em tempo real (núcleo): janelas de 8s, dedup
  determinística, backlog observável, presets de modelo — Fase D.
- Histórico + busca em SQLite (escopo reduzido, documentado) — Fase E.
- Exportação markdown/txt/json/srt/vtt — Fase I (parcial).
- Rótulo de speaker por canal (Você/Áudio da reunião/Reunião) — Fase H
  (leve).
- Sessões, recovery multi-root, encerramento gracioso, escolha de pasta,
  validação de API — Fases A/B (herdadas, verificadas, não tocadas).
- README, CHANGELOG, CONTRIBUTING, docs/FLOWCHARTS.md,
  docs/PENDENCIAS.md, docs/APRESENTACAO_PROFESSOR.md, docs/TESTING.md,
  CI (`.github/workflows/ci.yml`), `.gitignore` protegendo dados
  privados do usuário.

## O que está parcialmente pronto

- **Frontend React** (`frontend/`): toolchain funcionando, cliente HTTP
  tipado cobrindo 100% do contrato atual. **Todas as 7 telas da F.3
  construídas** — Dashboard, Nova Reunião, Gravação (SSE), Detalhe da
  Reunião, Agendamentos + criar/editar (recorrência completa),
  Configurações. O ciclo criar → gravar → ver → exportar → agendar é
  navegável inteiramente em React. Falta: tela de Histórico dedicada com
  paginação (hoje só busca + 5 recentes no Dashboard), testes
  automatizados de frontend (nenhum framework instalado ainda), e
  exercitar os caminhos de escrita com dados reais (não feito de
  propósito, pra não criar agendamentos/gravações reais sem pedido).
  `index.html` continua sendo a interface de referência até a paridade
  completa.
- **SQLite** (Fase E): `meetings`/`meeting_segments` prontos e testados;
  faltam `audio_chunks`/`transcription_jobs` como tabelas próprias e a
  migração de `schedules.json`.
- **Diarização** (Fase H): só canal, não voz.

## O que não foi iniciado

- **Meeting Intelligence** (Fase G): resumo/tarefas/decisões/tópicos —
  nenhum código, só arquitetura documentada (`docs/FLOWCHARTS.md`,
  diagrama 7).
- Empacotamento Windows de um clique (PyInstaller/Nuitka).
- DOCX/PDF.
- Windows Task Scheduler para iniciar agendamentos com o app fechado
  (Nível 2, `docs/SCHEDULING.md`).

## Testes

**Backend**: `pytest -q` — 584 passando (2 execuções seguidas sem
flakiness ao fim desta sessão). Rodar de novo antes de continuar, já que
o número pode ter mudado se algo mais foi commitado depois.

**Frontend**: `cd frontend && npm run build && npx oxlint` — ambos
verdes. Sem testes de componente (não há componentes de produto ainda).

**Hardware**: `tests/test_*_hardware.py` — pulados automaticamente sem
dispositivo de áudio; nesta máquina, rodados manualmente com sucesso
durante a Fase C/D (ver `docs/API.md`/`docs/LIVE_TRANSCRIPTION.md`,
seções "Testado").

## Arquitetura atual

Ver `README.md` (visão geral + diagrama resumido) e
`docs/FLOWCHARTS.md` (7 diagramas detalhados). Resumo: Python stdlib-only
no backend (`webui.py` sem framework HTTP), `soundcard` para áudio,
`faster-whisper` para transcrição, `sqlite3` (stdlib) para histórico,
JSON atômico para settings/schedules. Frontend ativo é HTML+JS puro;
React em preparação, não ativo.

## Banco

`data/meetings.db` (SQLite, criado sob demanda pelo `webui.py`). Schema
versão 1: `meetings`, `meeting_segments`, `search_index` (FTS5 opcional).
Ver `docs/DATABASE.md` para o schema completo e o que falta.
`data/schedules.json` continua sendo a persistência dos agendamentos
(não migrada pro SQLite ainda).

## React

`frontend/`. Todas as 7 telas da missão (F.3) existem: Dashboard, Nova
Reunião, Gravação, Detalhe da Reunião, Agendamentos + criar/editar,
Configurações. Próximos passos CONCRETOS, em ordem de valor: (1) instalar
um framework de teste (`vitest` + `@testing-library/react` são a escolha
óbvia pro stack Vite+React já existente) e cobrir os fluxos críticos
listados em F.17; (2) uma tela de Histórico dedicada com paginação de
verdade (`api.getMeetings({limit, offset})` já suporta, só falta a UI);
(3) exercitar de ponta a ponta os formulários de escrita (Nova Reunião,
Schedule Form) contra o backend real, com cuidado pra não deixar
artefatos (uma gravação de teste real, um agendamento de teste real)
sem limpar depois. Ver `docs/PENDENCIAS.md` item P1#1.

## Transcrição

Ao vivo (Fase D) e durável (chunk) coexistem — ver
`docs/LIVE_TRANSCRIPTION.md`. Não hardware-validado: dedup real com fala
sobreposta entre duas janelas (só testado com dublês). Próximo passo se
for aprofundar: um smoke test manual com áudio falado de verdade tocando
durante a gravação (não um teste automatizado — precisa de fala real).

## Intelligence

Não implementado. Ver `docs/FLOWCHARTS.md` diagrama 7 para a arquitetura
de provider plugável planejada (nunca acoplar a uma empresa específica;
o produto deve continuar funcionando sem nenhum provider configurado).

## Diarização

Só rótulo por canal (Fase H leve, `storage/import_filesystem.py`).
Diarização real (Pyannote ou equivalente) não avaliada nesta sessão —
avaliar com cuidado o custo de dependências/modelo antes de comprometer
a estabilidade do produto principal (a missão original é explícita sobre
isso).

## Exports

Markdown/TXT/JSON/SRT/VTT prontos e testados (`src/meeting_transcriber/export/`).
DOCX/PDF não avaliados.

## GitHub

`.gitignore` atualizado: protege `/data/` (já existia), `/Eletrica/`
(pasta de reunião real do usuário nesta máquina, descoberta nesta
sessão) e arquivos `.md` soltos na raiz que são anotações pessoais do
usuário (com exceção de README/CHANGELOG/CONTRIBUTING). CI conservador
em `.github/workflows/ci.yml` (backend em `windows-latest`, frontend em
`ubuntu-latest`, hardware sempre pulado). Sem LICENSE (decisão do
proprietário, não tomada — ver `docs/PENDENCIAS.md`).

## Bugs conhecidos

Nenhum bug aberto conhecido no que foi implementado. Ver
`docs/EXECUTION_STATE.md` para os bugs reais encontrados E corrigidos
durante esta sessão (não deixados pendentes).

## Pendências P0

Nenhuma.

## Pendências P1

1. Telas de produto React (Dashboard/Nova Reunião/Gravação/Histórico).
2. Migrar `schedules.json` para SQLite quando o schema crescer.
3. Windows Task Scheduler (Nível 2 do agendamento).

## Pendências P2

4. Meeting Intelligence (Fase G) — não iniciada.
5. Diarização completa (Fase H) — só canal hoje.
6. Empacotamento Windows (.exe).
7. DOCX/PDF.

Ver `docs/PENDENCIAS.md` para a lista completa (inclui P3).

## Próxima ação exata

1. Rodar `pytest -q` (backend) e `cd frontend && npm run build && npx oxlint`
   (frontend) pra confirmar que nada regrediu desde o fim desta sessão.
2. Ler `docs/PENDENCIAS.md` P1#1.
3. `npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom`
   no `frontend/`, configurar `vite.config.ts` (`test: { environment: "jsdom" }`),
   e escrever o primeiro teste real (ex.: `Dashboard` renderiza o estado
   "sem conexão" quando `api.getStatus()` rejeita) — hoje a única
   verificação do frontend é `tsc`, que não pega bugs de lógica/render.
4. Depois: tela de Histórico dedicada com paginação
   (`frontend/src/pages/History.tsx`, usando `api.getMeetings({limit, offset})`).
5. Com cuidado: testar manualmente os formulários de escrita (Nova
   Reunião, Schedule Form) contra um backend real, criando UMA reunião/
   agendamento de teste claramente identificado (ex.: título "DEMO —
   teste manual") e limpando depois (soft-delete a reunião,
   cancelar o agendamento).
6. Não remover `index.html`/`webui.py` até a paridade funcional da nova
   interface ser demonstrada (ver `docs/ROADMAP.md`, Fase F).

## Comandos úteis

```bash
# backend
pytest -q
python webui.py            # sobe o painel em http://127.0.0.1:8765

# frontend
cd frontend
npm run dev                # dev server com proxy pro backend real
npm run build               # type-check + bundle de producao
npx oxlint

# banco (inspecionar manualmente)
python -c "from meeting_transcriber.storage.db import connect; c = connect(__import__('pathlib').Path('data/meetings.db')); print(c.execute('SELECT id, title, status FROM meetings').fetchall())"
```

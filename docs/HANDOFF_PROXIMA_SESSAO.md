# Handoff para a próxima sessão

## Estado atual

Branch `main`, árvore limpa, sincronizada com `origin/main`. CI verde nos dois
jobs, sem avisos de depreciação.

| Verificação | Resultado |
|---|---|
| `pytest -q` | 670 passed |
| `npm test` | 82 passed em 11 arquivos |
| `npm run build` | ok — 282 KB JS (83 KB gzip), 20,5 KB CSS |
| `npx oxlint` | 0 erros, 5 avisos `set-state-in-effect` (pré-existentes) |

**A V1.0 não tem mais bloqueador técnico conhecido.** Os dois gates que
faltavam foram validados com hardware real (ver `docs/EXECUTION_STATE.md`,
Checkpoint 4): uma gravação de 1h53 parada pelo painel terminou `completed`
com 23/23 blocos, e a aula interrompida de 21/09 foi recuperada para 11/11.

O que falta para *lançar* é decisão, não código: `CODE_OF_CONDUCT.md` (ver
abaixo) e apertar o botão da release.

## Leia antes de mexer em qualquer coisa

1. `docs/SCHEDULING.md`, seção **"Incidente 21/09/2026"**. É a reconstituição
   de um agendamento que não gravou e explicou a causa errada ao usuário. A
   lição vale além do bug: `except Exception` num laço de controle manteve o
   motor vivo e apagou a única informação que explicaria a falha.
2. `src/meeting_transcriber/atomic.py`. Toda escrita de arquivo de estado
   passa por aqui, e o cabeçalho explica por que o retry existe.
3. `DESIGN.md` e `MOTION.md` se for mexer na interface. São a autoridade
   visual; `MOTION.md` lista explicitamente o que **não** pode ser animado.

## Próxima ação exata

**Fase G — Meeting Intelligence.** Projeto pronto e revisável em
`docs/INTELLIGENCE.md`: provider plugável (`MeetingIntelligenceProvider`), o
núcleo continua funcionando sem provider nenhum, e o modelo de dados
(`meeting_analysis`, `action_items`, `decisions`, `topics`,
`open_questions`) liga tudo a `meeting_id`/`segment_id`/timestamp.

A regra inegociável desse projeto, repetida aqui porque é fácil de violar sem
perceber: **não inventar dado**. Responsável não dito → `owner = null`. Prazo
não dito → `due_date = null`. Nunca alucinar tarefa.

Antes de escrever código da Fase G, decidir uma coisa só: qual provider entra
primeiro. O produto é local-first e sem telemetria (`README`, "Privacidade"),
então um provider que manda transcrição para uma API externa **muda uma
promessa do produto** e precisa ser opt-in explícito, desligado por padrão, e
dito na interface. Um modelo local (Ollama) não tem esse problema.

### Se preferir fechar frente antes de abrir outra

Em ordem de valor:

1. **Tokens de design** (`DESIGN.md`, seção 4). `frontend/src/index.css` hoje
   tem o `@import` e o bloco de `prefers-reduced-motion`, nada mais. Converter
   uma tela por vez; não adicionar token que nenhum componente use ainda.
2. **Acessibilidade restante** (`docs/PENDENCIAS.md`, P2-11): Dashboard,
   Detalhe e Agendamentos seguem sem `aria-*`; fora da Gravação não há
   hierarquia de títulos; nada foi testado com leitor de tela real.
3. **Speaker por segmento** (P1-2): o áudio por canal já existe em
   `audio/microphone/` e `audio/system/`, então dá para atribuir cada segmento
   ao canal dominante por energia RMS, sem diarização por voz. Só funciona com
   `keep_audio` ligado.

## Armadilhas desta máquina

- **Sempre rode o painel pelo `.venv`.** O Python global não tem `soundcard`
  nem `tzdata`; com ele o painel sobe e só falha na hora de uma gravação
  agendada. `iniciar.bat` faz isso certo. Se subir na mão, o painel agora
  avisa o que falta — leia o `[ATENCAO]` no terminal.
- **Não rode `pytest` e `vitest` ao mesmo tempo**, e não rode nenhum dos dois
  durante uma gravação real: a transcrição sozinha ocupa 100% de um
  i5-11400H, e o `vitest` falha com *"Timeout waiting for worker to respond"*.
- **Um agendamento marcado `missed` não dispara sozinho** — é de propósito
  (nunca começar atrasado em silêncio). Retomar é `start_now`, ou gravar
  manualmente.

## Pendente de decisão do proprietário

**`CODE_OF_CONDUCT.md`.** O Contributor Covenant exige um canal privado para
denúncias de conduta. O GitHub não tem mensagem direta entre usuários; o
*private vulnerability reporting* é para segurança; e publicar um e-mail
pessoal num repositório público é escolha sua. Um alias dedicado resolve.
Enquanto não houver canal real, é mais honesto não ter o arquivo.

**Nome no copyright.** `LICENSE` linha 190 traz `Copyright 2026 Joao` — o nome
usado nos commits. Troque se quiser outro.

**Backup do banco.** `data/meetings.db.backup-20260921-205941` foi criado
antes da limpeza das reuniões-fantasma. Apague quando estiver satisfeito (está
em `/data/`, que é ignorado pelo Git).

## Limitações reais, não escondidas

- Transcrever durante a gravação satura a CPU nesta máquina (P1-1). Nada se
  perde, mas o backlog cresce e o encerramento precisa drená-lo — foi
  exatamente o caso na gravação de 1h53.
- Captura **simultânea** sistema+microfone nunca foi validada numa gravação
  longa real (a de 1h53 usou só áudio do sistema).
- `device=cuda` nunca foi exercitado nesta máquina.
- Um clone limpo mostra o painel legado até rodar `npm run build`
  (`frontend/dist/` não é versionado). O `iniciar.bat` avisa isso agora.

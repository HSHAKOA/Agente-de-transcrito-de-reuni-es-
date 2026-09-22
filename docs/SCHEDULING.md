# Agendamento de gravações (Fase C.1)

Código em `src/meeting_transcriber/scheduling/`. Roda **dentro do processo
do painel** (`webui.py`) — ver "Nível 1 vs Nível 2" no fim deste documento.

## Modelo

- **`Schedule`** (`models.py`): a regra (título, data-âncora, horário de
  início/fim, timezone, pasta de destino, fontes de áudio, modelo/idioma,
  recorrência). `status` reflete o ciclo de vida da ocorrência
  atual/próxima (`scheduled → preparing → recording → finishing →
  completed`, ou `missed`/`failed`/`cancelled`).
- **`ScheduleRun`**: uma ocorrência concreta que o `Schedule` produziu —
  guarda só o *vínculo* com a reunião de verdade (`meeting_id`,
  `meeting_dir`, horários previstos vs. reais) e nunca duplica o estado da
  reunião em si (isso continua inteiramente em `metadata.json`/`state.json`
  via `MeetingSession`, como sempre foi). Um agendamento recorrente produz
  um `ScheduleRun` (e portanto uma `MeetingSession`/`meeting_id`) por
  ocorrência.

## Persistência

Um único arquivo `data/schedules.json` (`store.py`), atômico (tmp file +
`os.replace` com retry — mesmo padrão de `settings.py`/`session.py`), fora
de qualquer `meetings_root` (cada agendamento pode apontar para uma pasta
diferente). A interface (`list_all`/`get`/`save`/`delete`) é
deliberadamente pequena para poder ser trocada por SQLite mais tarde (Fase
E) sem tocar em quem chama.

## Timezone

Todo horário é timezone-aware. `zoneinfo.ZoneInfo(nome_iana)` resolve o
fuso; como o Windows não traz uma base de dados IANA embutida, o pacote
`tzdata` foi adicionado como dependência (é o que a própria documentação
do `zoneinfo` recomenda). `tzlocal` detecta o fuso IANA da máquina (ex.:
`America/Sao_Paulo`) só como **valor padrão** sugerido no formulário — a
arquitetura aceita qualquer timezone IANA válido, nunca fica presa a um.

Todo cálculo de data (`recurrence.py`) reconstrói o datetime local **do
zero** a partir de (data de calendário + hora de parede + timezone) para
cada dia candidato, em vez de somar `timedelta(days=1)` a um datetime já
"aware" — isso garante que uma virada de horário de verão no meio de uma
recorrência diária/semanal seja resolvida corretamente pelo próprio
`zoneinfo`, não por aritmética manual.

O nome do fuso é validado **no cadastro** (`scheduling/validation.py`
chama `resolve_zone`), então um agendamento salvo tem, por construção, um
fuso que resolvia naquele momento. Se ele parar de resolver depois — o
caso real é o `tzdata` sumir do interpretador que roda o painel —
`next_occurrence` passa a levantar `InvalidTimeZone` em **todo** tick.
`tick_once` trata esse caso explicitamente (`_mark_timezone_unusable`):
registra a causa verdadeira uma única vez, zera `next_run_at` (para a tela
não prometer um horário que não vai acontecer) e mantém `is_open()`
verdadeiro, de modo que o agendamento volta sozinho quando a dependência
for reinstalada. Ver "Incidente 21/09/2026" abaixo.

## Recorrência

Tipos: `once`, `daily`, `weekdays` (seg-sex), `weekly` (um dia fixo),
`custom_days` (conjunto de dias). Dias da semana seguem a convenção de
`date.weekday()` (0=segunda .. 6=domingo). Deliberadamente **não** é um
parser de expressão de calendário (cron/RRULE) — só sabe somar dias de
calendário e filtrar por dia da semana, com um horizonte máximo de
materialização (`MAX_LOOKAHEAD_DAYS = 366`) para nunca variar
indefinidamente.

`end_time <= start_time` é **sempre** interpretado como virada de meia-
noite (fim no dia seguinte), nunca como erro — ex.: `23:00 → 01:00`. Isso
também rejeita por construção um `19:00 → 18:00` no mesmo dia: vira uma
janela de 23h, que estoura o teto de duração razoável (`MAX_DURATION_HOURS
= 12`, `validation.py`).

## Conflitos

Ao criar/editar um agendamento, `conflicts.py` materializa as ocorrências
de ambos os agendamentos dentro de um horizonte de 30 dias
(`CONFLICT_CHECK_HORIZON_DAYS`) e rejeita se alguma janela se sobrepuser —
reflete a regra atual de **uma sessão de captura ativa por aplicação**. Um
conflito além desse horizonte não é pego no cadastro, mas nunca pode
resultar em duas gravações simultâneas de verdade: o motor só permite
iniciar quando `is_recording_active()` (o único slot de gravação do
painel) está livre — o pior caso é uma ocorrência tardia virar
`missed`/`failed` em vez de um aviso antecipado.

## Motor (`engine.py`)

`tick_once()` faz uma passada por todos os agendamentos abertos,
comparando `clock.now()` (UTC) contra os timestamps absolutos gravados em
cada `ScheduleRun` — nunca um `sleep()`/`Timer` calculado a partir de uma
duração. Isso é o que garante que mudança de relógio, horário de verão, ou
o computador voltando de suspensão se autocorrigem no próximo tick, em vez
de exigir tratamento especial.

Transições automáticas:

1. **T-5min** (`DEFAULT_PREFLIGHT_LEAD_SECONDS`): roda o preflight (pasta +
   dispositivos), marca `preparing`. Falha não bloqueia — só aparece no
   campo `preflight` da ocorrência para o usuário corrigir a tempo.
2. **T-0 até T+1min** (`DEFAULT_MISSED_TOLERANCE_SECONDS`): tenta iniciar a
   cada tick (repete se um dispositivo/pasta reconectar dentro da janela).
   Nunca troca silenciosamente o dispositivo configurado por outro.
3. **Falha persistente**: se a tolerância expira sem sucesso, a ocorrência
   vira `failed` (houve tentativa real, com `error_message` claro) ou
   `missed` (o app nem chegou a tentar — provavelmente estava fechado) —
   ver `_process_schedule_step` para a distinção exata. Ambos ficam
   "acionáveis" (`start_now`/`ignore_missed`) até a janela original
   terminar, depois viram histórico automaticamente.
4. **Fim automático**: ao atingir o fim da janela, chama a **mesma**
   rotina de parada graciosa do botão "Parar" manual
   (`webui.stop_transcriber` → `shutdown_sequence`) — nunca `kill()`
   direto. Fica em `finishing` até o motor detectar que o processo
   realmente terminou.
5. **Parada manual antecipada**: detectada por polling (o motor nunca
   precisa de um hook especial no botão "Parar") — se a gravação termina
   sozinha antes do fim previsto, a ocorrência é marcada
   `ended_early=true`.

Ações manuais (`start_now`/`ignore_missed`) reusam exatamente o mesmo
`_try_start` que o tick automático usa — há uma única implementação de
"começar a gravar esta ocorrência".

## API HTTP

Ver `docs/API.md`, seção "Agendamento". Rotas: `GET/POST /api/schedules`,
`POST /api/schedules/<id>` (editar), `POST /api/schedules/<id>/cancel`,
`POST /api/schedules/<id>/start-now`, `POST /api/schedules/<id>/ignore-missed`.

## Nível 1 vs. Nível 2 (app fechado)

**Implementado (Nível 1):** o motor só roda enquanto `webui.py` está de pé
— exatamente como o resto do painel. `main()` só chama
`schedule_engine.start()` depois de confirmar (via bind da porta) que esta
é a única instância rodando, pelo mesmo motivo que a detecção de
recuperação espera isso (ver `docs/RECOVERY.md`).

**Não implementado nesta fase (Nível 2 — pendência documentada):**
iniciar o `webui.py` automaticamente pouco antes de um agendamento via
Windows Task Scheduler, para não exigir manter um processo Python
invisível rodando o tempo todo. Fica como pendência explícita (ver
`docs/PENDENCIAS.md`) porque:

- exige investigar `schtasks`/a API do Task Scheduler com segurança
  (nunca elevar privilégio além do necessário, nunca instalar como serviço
  Windows sem justificativa — a missão pede exatamente isso);
- a opção "Wake the computer to run this task" só deveria ser prometida
  depois de validada de verdade nesta máquina/empacotamento — **este
  software não afirma conseguir acordar qualquer computador** sem essa
  validação real;
- se o computador estiver desligado/hibernado/suspenso, nenhum agendamento
  interno (Nível 1) pode garantir a captura — isso é uma limitação de
  arquitetura, não um bug.

## Incidente 21/09/2026 — "missed" mentindo sobre a causa

Uma aula agendada para 21:00 não gravou. A tela mostrou *"Esta gravação
estava programada para começar às 21:00. O aplicativo não estava
disponível naquele horário."* — **falso**: o painel estava aberto e
tentando iniciar a cada 20 s.

O que realmente aconteceu, na ordem:

1. O painel foi reiniciado com o Python **global** em vez do `.venv`. Ele
   subiu normalmente: a tela abriu, o histórico funcionou, a detecção de
   sessões interrompidas rodou. Nada indicava problema.
2. Sem `soundcard`, `check_device_health` passou a levantar `AudioError`.
   Como `_check_readiness` chamava a sonda diretamente, a exceção
   atravessava o preflight inteiro.
3. `tick_once` capturava com seu `except Exception` genérico, registrava no
   log do terminal e seguia. **Nada era salvo no agendamento** — em
   particular, `run.error_message` continuava `None`.
4. Passados os 60 s de tolerância, o motor marcou `missed`. A escolha entre
   `MISSED` e `FAILED` depende justamente de `run.error_message` estar
   preenchido; como a exceção impediu isso, o caso caiu no ramo errado e
   herdou a mensagem de "app fechado".
5. `missed` é terminal, então todo tick seguinte voltava a reclamar a
   próxima ocorrência e, sem `tzdata`, estourava `InvalidTimeZone` — para
   sempre, em silêncio.

Três correções, todas com teste de regressão que falha no código antigo:

- **`_probe_device`**: toda sonda vira veredito, nunca exceção. Backend
  ausente, driver quebrado ou `OSError` na checagem de pasta agora viram
  problema de preflight, e a ocorrência termina em `FAILED` com a causa
  real.
- **`_mark_timezone_unusable`**: fuso que não resolve vira falha explícita
  uma vez só, em vez de exceção por tick (ver "Timezone").
- **`check_runtime_health()` no `webui.py`**: o painel agora imprime o que
  está faltando (pacote, fuso, build do React) **antes** de se anunciar
  como pronto. É o que teria transformado esse incidente numa linha no
  terminal em vez de uma aula perdida.

Lição que vale além do bug: `except Exception` num laço de controle não é
robustez. Ele manteve o motor vivo e, ao mesmo tempo, apagou a única
informação que permitiria explicar a falha — e o usuário recebeu uma
explicação confiante e errada.

## Limitações conhecidas

- Sem Nível 2 (ver acima): o app precisa estar aberto no horário agendado.
- Uma ocorrência marcada `missed`/`failed` **não** é reavaliada pelos ramos
  de `_process_schedule_step` que citam esses estados: como os dois são
  terminais, o topo da função reclama a próxima ocorrência antes de chegar
  lá. O caminho real de retomada é `start_now`/`ignore_missed` (ação do
  usuário), exatamente como projetado — mas os ramos citados são código
  morto e merecem uma limpeza quando alguém mexer nesse arquivo.
- Checagem de conflito tem horizonte de 30 dias; recorrências que só se
  cruzam além disso não são avisadas no cadastro (mitigado em tempo real
  pelo slot único de gravação).
- `fold` (hora repetida na volta do horário de verão) não é tratado
  explicitamente — usa o comportamento padrão do `zoneinfo` (assume a
  primeira ocorrência). Não é um problema para o Brasil hoje (sem DST
  desde 2019), documentado para o caso de uso em outro timezone.

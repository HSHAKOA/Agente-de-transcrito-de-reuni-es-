# Arquitetura

Este documento descreve o fluxo **real** do codigo (nao um plano aspiracional).
As secoes "Visao geral" e "Modelo de concorrencia" refletem o estado atual
(fases A a F); as demais detalham o pipeline de gravacao, o encerramento
gracioso, a pasta de reunioes e a recuperacao. Fluxogramas: `docs/FLOWCHARTS.md`.

## Visao geral

Dois processos, um navegador. O **painel** (`webui.py`) e um servidor HTTP
local que so escuta em `127.0.0.1`; cada gravacao roda num **subprocesso
separado** (`python -m meeting_transcriber`), de modo que um travamento do
Whisper ou da captura nunca derruba o painel, e o painel nunca precisa
esperar a transcricao.

```
Navegador (React, frontend/dist)
      |  HTTP + JSON  (POST valida Host e Origin)     SSE (niveis, transcricao ao vivo)
      v
webui.py -- processo "painel" (ThreadingHTTPServer, 127.0.0.1:8765)
      |-- Handler ............ roteia /api/*, serve o build do React, valida entrada
      |-- estado da gravacao . `state` protegido por `state_lock` (start/stop/stopping)
      |-- SchedulerEngine .... thread de tick: agenda, preflight, inicia/para sozinho
      |-- MeetingRepository .. SQLite (historico/busca), toda operacao sob um lock
      |-- export/ ............ Markdown, TXT, JSON, SRT, VTT gerados sob demanda
      |
      |  subprocess.Popen(lista de argumentos, sem shell) + sinal de encerramento
      v
python -m meeting_transcriber -- processo "gravador"
      |-- audio/ ............. dispositivos, captura de sistema e/ou microfone
      |                        (dual_capture: uma thread por fonte), mixer, medidor RMS
      |-- recorder + fila .... blocos duraveis (.wav) -> transcricao (faster-whisper)
      |-- live/ .............. janelas curtas (8 s) em thread propria, com dedup
      |-- session.py ......... metadata.json + state.json (escrita atomica)
      '-- escreve, de forma atomica, na pasta da reuniao:
            transcript.md  levels.json  live_transcript.json  chunks/  audio/
```

**Comunicacao painel <-> gravador**: nao ha socket nem fila entre os dois
processos. O gravador escreve arquivos na pasta da reuniao (`levels.json` a
cada 0,2 s e `live_transcript.json`, ambos via arquivo temporario +
`os.replace`, entao o leitor nunca ve um arquivo pela metade); o painel os
le e os repassa ao React como SSE. A saida padrao do gravador e lida por uma
thread (`_reader_thread`) que, ao detectar o fim do processo, indexa a
reuniao no SQLite automaticamente.

### Persistencia

| Dado | Onde | Observacao |
|---|---|---|
| Reuniao (audio, blocos, transcricao, estado) | pasta `AAAA-MM-DD_HHMM_Titulo_xxxxxx/` na raiz escolhida | fonte da verdade; nunca apagada pelo app |
| Historico e busca | `data/meetings.db` (SQLite: `meetings`, `meeting_segments`, indice FTS5 `search_index`, `schema_version`) | indice derivado do filesystem; reconstruivel via importacao idempotente |
| Agendamentos | `data/schedules.json` | JSON com escrita atomica; ainda nao migrado para SQLite (ver `docs/PENDENCIAS.md`) |
| Preferencias | `data/settings.json` | pasta de reunioes, raizes conhecidas, dispositivos de audio |

`data/` e ignorado pelo Git: contem audio e transcricoes pessoais.

### Mapa de modulos (`src/meeting_transcriber/`)

| Modulo | Responsabilidade |
|---|---|
| `cli.py` | processo gravador: junta captura, fila, Whisper, escrita e encerramento |
| `recorder.py`, `transcriber.py`, `markdown_writer.py` | gravacao em blocos, transcricao duravel, `.md` incremental |
| `audio/` | `devices` (enumeracao + checagem de saude), `dual_capture`, `mixer`, `levels`, `loopback`, `microphone`, `models` |
| `live/` | `window`, `pipeline`, `dedup`, `segments`, `transcript`, `whisper_adapter` (transcricao quase ao vivo) |
| `scheduling/` | `models`, `recurrence`, `conflicts`, `engine`, `service`, `store`, `validation`, `clock` |
| `storage/` | `db` (migrations versionadas), `repository`, `import_filesystem` |
| `export/` | um formatador por formato (`markdown`, `txt`, `json_format`, `srt`, `vtt`) |
| `session.py`, `settings.py`, `validation.py`, `folder_dialog.py`, `whisper_config.py` | sessao persistente/recuperacao, preferencias, validacao de entrada, seletor nativo de pasta, presets do Whisper |

## Modelo de concorrencia

- **Gravar nunca espera transcrever**: captura e transcricao ficam em threads
  separadas ligadas por uma fila; se o Whisper atrasa, a fila cresce e a
  gravacao continua (testado em `tests/test_live_pipeline.py`).
- **Um lock por recurso compartilhado**: `state_lock` (estado da gravacao no
  painel), `MeetingRepository._lock` (toda leitura e escrita da conexao SQLite
  compartilhada), `ScheduleStore._lock`, `MeetingSession._lock`, o lock do
  snapshot de transcricao ao vivo e o do medidor de nivel. O acesso a COM do
  Windows e serializado por `_com_lock` em `audio/devices.py`.
- **Encerramento em dois tempos**: `POST /api/stop` marca `state["stopping"]`
  (um segundo pedido recebe 409) e o gravador recebe um sinal (nao um `kill`);
  so se nao terminar dentro do prazo ha escalonamento para `terminate` e, por
  ultimo, `kill`.
- **Instancia unica**: o servidor nao usa `allow_reuse_address` — subir um
  segundo painel falha em vez de virar um processo zumbi. A deteccao de
  recuperacao e o scheduler so iniciam depois de confirmar que a porta e nossa.
- **Threads de vida longa sao daemon** (SSE, captura, tick do scheduler): nenhuma
  impede o encerramento do processo.

## Fluxo de ponta a ponta

O diagrama abaixo detalha o caminho de **uma fonte de audio**
(`audio_capture.get_loopback_microphone`). Com microfone + sistema, o
`audio/dual_capture.py` executa uma captura por fonte e o `audio/mixer.py`
mistura os canais bloco a bloco antes da transcricao duravel; a estrutura
(thread de captura -> fila -> consumidor) e a mesma.

```
audio_capture.get_loopback_microphone()
        |  abre o dispositivo de saida padrao do SO em modo loopback
        |  (WASAPI no Windows / "monitor" no PulseAudio-PipeWire / BlackHole no macOS)
        v
recorder.recording_worker            (thread dedicada, daemon)
        |  le blocos de 0.5s (BLOCK_SECONDS) do microfone
        |  acumula em memoria ate juntar `chunk_seconds` (default 300s)
        |  ao fechar um bloco (ou ao receber sinal de parada, com o que
        |  sobrou no buffer): grava chunk_NNNNN.wav em disco
        |  chama on_chunk_recorded(chunk) se fornecido (usado pra espelhar
        |  o progresso em state.json -- ver session.py)
        v
queue.Queue[Optional[RecordedChunk]]  (produtor: recording_worker; consumidor: cli.run)
        |  ao terminar (normal ou por excecao), SEMPRE poe `None` na fila
        |  (garantido pelo try/finally) -- e o unico jeito do consumidor
        |  saber que a gravacao acabou e sair do loop bloqueante
        v
cli.run()                             (thread principal)
        |  consome a fila um chunk por vez
        |  transcriber.Transcriber.transcribe_file (faster-whisper, VAD on,
        |     sem contexto entre blocos -- cada .wav e isolado)
        |  markdown_writer.MarkdownWriter.append_segments -> escreve no .md
        |     JA, incrementalmente (nao espera a reuniao acabar)
        |  session.MeetingSession.mark_chunk_transcribed/mark_chunk_failed
        |     (se --meeting-dir foi passado) -> state.json atualizado
        v
.md final + state.json "completed"/"interrupted"/"failed"
```

## Shutdown gracioso (Ctrl+C ou painel)

```
Ctrl+C no terminal (SIGINT)              Painel: /api/stop
        |                                        |
        |                          shutdown_sequence(proc) (webui.py)
        |                                        |
        |                    proc.send_signal(CTRL_BREAK_EVENT no Windows,
        |                                       SIGINT no POSIX)
        |                                        |
        v                                        v
cli._make_shutdown_handler  <---------------------
        |  1o sinal: stop_event.set() (nao mata nada)
        |  2o sinal: os._exit(1) (forca saida, usado so se o processo
        |     estiver preso demais pra reagir ao 1o sinal)
        v
recording_worker sai do loop (stop_event.is_set()), grava o bloco PARCIAL
que sobrou no buffer, poe na fila, poe None
        v
cli.run() esvazia a fila, chama writer.finalize() e session.mark_completed()
        v
processo termina sozinho (exit code 0)
```

Se o processo nao terminar sozinho dentro de `GRACEFUL_TIMEOUT_SECONDS` (30s,
tempo pra fila de whisper pendente ser drenada), `shutdown_sequence` escala
para `proc.terminate()`, e so como ultimo recurso (mais `TERMINATE_TIMEOUT_
SECONDS`, 5s) para `proc.kill()`.

## Pasta de reunioes (local escolhido pelo usuario)

O usuario escolhe uma unica vez (botao "Escolher pasta", seletor nativo via
`folder_dialog.py`/`tkinter`) onde TODAS as reunioes ficam guardadas — essa
raiz e persistida em `<projeto>/data/settings.json`
(`meeting_transcriber.settings`) e lembrada entre execucoes; o padrao antes
da primeira escolha e `Documentos/Reunioes`. Trocar a pasta e bloqueado
enquanto uma gravacao/reprocessamento estiver em andamento.

Cada reuniao vira uma subpasta dentro dessa raiz, nomeada com data, hora e
titulo sanitizado (`session.sanitize_title_for_folder` remove caracteres
invalidos no Windows, nomes reservados como `CON`/`NUL`, pontos/espacos nas
pontas) mais um sufixo aleatorio pra garantir unicidade:

```
<raiz escolhida>/2026-09-14_1900_Reuniao-Projeto-ERP_ab12ef/
    metadata.json   título, modelo, idioma, device, root_directory,
                     meeting_directory, transcript_path (nao muda depois de criado)
    state.json      status, contadores, lista de chunks (muda a cada evento,
                     escrito de forma atomica -- tmp file + os.replace)
    transcript.md   a transcricao (nome sempre fixo -- nao vem mais do
                     cliente, ver "Fim do campo output" abaixo)
    chunks/         os .wav de cada bloco (mesma pasta usada como work_dir)
```

Antes de permitir iniciar uma gravacao (ou trocar a pasta-raiz),
`validation.check_folder_health` roda a checklist: a pasta existe (ou pode
ser criada), e realmente um diretorio, tem espaco livre acima do minimo
(200 MB), e aceita um arquivo de teste de verdade (nao so "parece" gravavel
— ACLs do Windows sao traicoeiras demais pra confiar sem testar). Qualquer
falha impede o inicio, com mensagem clara — nunca falha silenciosamente no
meio da reuniao.

### Fim do campo `output`

Antes, o nome do arquivo `.md` vinha de um campo de texto livre no painel
(`output`), validado por `validate_output_filename` para impedir path
traversal. Agora esse campo nem existe mais no contrato da API: o nome e
sempre `transcript.md`, dentro da pasta que o proprio backend calcula a
partir da raiz configurada — a superficie de path traversal foi eliminada
por construcao, nao apenas validada (`validate_output_filename` continua
existindo e testada, disponivel para uso futuro, ex.: nomes de exportacao).

### Recuperacao

Na inicializacao do painel (`webui.py:main`, so depois de confirmar que a
porta foi vinculada — ver nota abaixo), `session.mark_interrupted_sessions`
varre `<raiz>/*/state.json`: qualquer sessao ainda marcada
`recording`/`processing` significa que o processo anterior morreu sem
finalizar -- e marcada `interrupted` (nada e apagado) e aparece em
`/api/recovery` pro usuario mandar reprocessar (`/api/meetings/<id>/resume`,
que roda `python -m meeting_transcriber --resume <meeting_dir>`: nao grava
audio novo, so retranscreve os blocos que ainda nao tinham sido transcritos
com sucesso e reanexa ao `.md` existente). A varredura cobre **todas as
raizes ja usadas** (`settings.get_known_meeting_roots`), nao so a ativa:
uma sessao deixada numa pasta anterior continua aparecendo depois que o
usuario troca de raiz. Nada fora dessas raizes escolhidas e varrido. Ver
`docs/RECOVERY.md`.

## Validacao de entrada (webui.py)

Todo campo vindo do `/api/start` passa por `meeting_transcriber.validation`
antes de virar argumento de linha de comando do subprocesso: `model`/
`device` sao allowlist, `chunk_seconds` tem faixa (5-1800), `title` tem
tamanho maximo. Nao ha mais campo `output` no contrato — ver "Fim do campo
output" acima. Ver `docs/SECURITY.md` para o raciocinio completo.

## Frontend (interface ativa)

`frontend/` e um projeto Vite + React 19 + TypeScript + Tailwind CSS v4 e
**e a interface do produto**: `webui.py` serve o build (`frontend/dist/`) na
mesma origem da API, com fallback de SPA para rotas do cliente e sem nunca
interceptar `/api/*` (que responde 404 quando desconhecida). O painel legado
(`index.html`) so e servido quando o build nunca foi gerado. O cliente HTTP
tipado (`src/services/api.ts`, `src/types/api.ts`) espelha o contrato real
das rotas; nenhuma regra de negocio vive no frontend. Ver `frontend/README.md`.

## O que ainda nao existe

Resumo, tarefas e decisoes automaticas (Meeting Intelligence, Fase G) e
diarizacao (Fase H). Hoje o rotulo de "quem falou" e **por reuniao**, derivado
da configuracao de captura (`Voce` = so microfone, `Audio da reuniao` = so
sistema, `Reuniao` = os dois): na captura simultanea todos os segmentos
recebem `Reuniao`, porque o mixer junta os canais antes da transcricao — nao
ha atribuicao por segmento nem por voz. Agendamentos ainda vivem em
`schedules.json` e so disparam com o painel aberto. Ver `docs/ROADMAP.md` e
`docs/PENDENCIAS.md`.

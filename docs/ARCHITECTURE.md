# Arquitetura

Este documento descreve o fluxo **real** do codigo (nao um plano aspiracional).
Atualizado apos a Fase B (graceful shutdown, validacao, sessao, recuperacao).

## Fluxo de ponta a ponta

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

## Modelo de sessao (recuperacao)

Quando `--meeting-dir` e passado (o painel sempre passa), o progresso e
espelhado em disco:

```
data/meetings/<meeting_id>/
    metadata.json   título, modelo, idioma, device, transcript_path (nao muda)
    state.json      status, contadores, lista de chunks (muda a cada evento,
                     escrito de forma atomica -- tmp file + os.replace)
    chunks/         os .wav de cada bloco (mesma pasta usada como work_dir)
```

O `.md` da transcricao continua onde o usuario pediu (`--output`, por
padrao um arquivo solto na raiz do projeto — assim o fluxo de uso atual,
onde cada reuniao vira um `.md` direto na pasta, continua funcionando sem
mudanca). `metadata.json` guarda o caminho absoluto desse `.md`
(`transcript_path`) para o modo `--resume` saber onde continuar anexando.

Na inicializacao do painel (`webui.py:main`), `session.mark_interrupted_
sessions` varre `data/meetings/*/state.json`: qualquer sessao ainda marcada
`recording`/`processing` significa que o processo anterior morreu sem
finalizar -- e marcada `interrupted` (nada e apagado) e aparece em
`/api/recovery` pro usuario mandar reprocessar (`/api/meetings/<id>/resume`,
que roda `python -m meeting_transcriber --resume <meeting_dir>`: nao grava
audio novo, so retranscreve os blocos que ainda nao tinham sido transcritos
com sucesso e reanexa ao `.md` existente).

## Validacao de entrada (webui.py)

Todo campo vindo do `/api/start` passa por `meeting_transcriber.validation`
antes de virar argumento de linha de comando do subprocesso: `model`/`device`
sao allowlist, `chunk_seconds` tem faixa (5-1800), `title` tem tamanho
maximo, e `output` so aceita um NOME de arquivo (sem `/`, `\`, `..`), sempre
confinado (via `Path.resolve()`) dentro da raiz do projeto. Ver
`docs/SECURITY.md` para o raciocinio completo.

## O que NAO mudou nesta fase

Captura de audio continua so o loopback do sistema (sem microfone/mixer —
isso e Fase C). Nao ha SQLite, historico de reunioes navegavel, resumo/
tarefas/decisoes, nem diarizacao — essas sao as fases D em diante do
roadmap. Ver `docs/AUDITORIA_V2.md` e `docs/ROADMAP.md`.

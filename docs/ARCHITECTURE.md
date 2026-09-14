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
com sucesso e reanexa ao `.md` existente). **Limitacao conhecida:** a
varredura so olha a raiz ATUAL configurada — reunioes deixadas para tras
numa raiz anterior (o usuario trocou de pasta) nao aparecem no banner ate a
raiz ser trocada de volta; os arquivos continuam intactos em disco, so nao
sao descobertos automaticamente por essa tela.

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

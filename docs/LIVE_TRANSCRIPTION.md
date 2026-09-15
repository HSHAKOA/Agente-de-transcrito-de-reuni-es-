# Transcrição quase em tempo real (Fase D)

Código em `src/meeting_transcriber/live/` + `whisper_config.py`. Roda
**dentro do subprocesso** `meeting_transcriber` (`cli.py`), ao lado da
transcrição durável por chunk — nunca a substituindo.

## Por que dois pipelines

```
Audio Sources (system/microphone)
        |
   Continuous Capture (recorder.py, inalterado)
        |
        ├──► Durable Audio Chunks (30-120s, chunk_seconds)
        |         → Whisper "de verdade" → .md final (fonte de verdade)
        |
        └──► on_block (mesmo callback que já alimentava o medidor de nível)
                  → LiveTranscriptionPipeline → janelas de 8s
                  → Whisper rápido (preset FAST por padrão)
                  → segmentos "provisional"
```

Um segmento **committed** (vindo da transcrição durável de um chunk)
sempre substitui qualquer **provisional** que caia dentro da mesma faixa
de tempo — por *intervalo de tempo*, nunca por comparação de texto (ver
`live/transcript.py:commit_range`). O `.md` final nunca é afetado pela
previa ao vivo: `writer.append_segments(segments)` continua usando
exatamente os mesmos segmentos da transcrição durável, como sempre foi.

## Por que a captura nunca espera o Whisper

`LiveTranscriptionPipeline.on_block()` só acumula e enfileira — a
transcrição de verdade roda numa thread própria (`_worker_loop`). Testado
explicitamente (`test_recording_thread_never_blocks_on_slow_transcription`):
mesmo com uma transcrição de 1s, `on_block()` retorna em menos de 0,5s.

Backpressure: a fila tem tamanho máximo; se o Whisper não conseguir
acompanhar (janelas chegando mais rápido que são processadas), a janela
mais ANTIGA na fila é descartada — nunca cresce memória sem limite, nunca
trava a captura. O áudio real nunca é afetado (ele já está salvo no chunk
durável); só a PRÉVIA daquele trecho fica ausente.

## Janelas e deduplicação

Janelas de 8s (`DEFAULT_WINDOW_SECONDS`) com 1,5s de sobreposição
(`DEFAULT_OVERLAP_SECONDS`) — a sobreposição evita cortar uma palavra bem
na fronteira entre duas janelas. Isso cria texto duplicado no ponto de
sobreposição, removido deterministicamente por `dedup.merge_overlapping_text`:
compara a cauda normalizada (minúsculas, sem pontuação) do texto anterior
com o início do texto novo e remove o maior prefixo em comum, preservando
a capitalização/pontuação originais do restante.

```
janela 1: "Precisamos finalizar esse módulo"
janela 2: "esse módulo até sexta-feira"
resultado exibido: "Precisamos finalizar esse módulo" + "até sexta-feira"
```

Timestamps são calculados por **contagem de amostras**, nunca relógio de
parede — o mesmo raciocínio já usado em `audio/dual_capture.py`.

## Captura dupla (sistema + microfone)

Não existe hoje um fluxo de áudio "mixado" em tempo real (a mixagem só
acontece por chunk durável, em `audio/mixer.py`). Por isso, quando as duas
fontes estão ativas:

- **Committed** (transcrição durável): rotulado `"mixed"`, exatamente como
  o chunk durável real que a gerou.
- **Provisional** (ao vivo): duas fontes SEPARADAS, `"system"` e
  `"microphone"`, cada uma com sua própria janela/deduplicação —
  `dual_recording_worker` ganhou um `on_raw_block(source, block)` opcional
  (aditivo, não muda o comportamento de quem não o usa) para viabilizar
  isso.

Documentado como limitação conhecida, não escondido: a previa ao vivo em
modo dual mostra as duas falas separadamente; o `.md` final (committed)
continua mostrando o áudio mixado, sem mudança nenhuma de comportamento
já testado.

## Backlog (D.6)

`LiveTranscript.backlog()`: `recorded_seconds` (atualizado a cada chunk
durável fechado) menos `transcribed_seconds` (atualizado a cada `commit_range`)
= `pending_seconds`. Classificação: `LIVE` (≤1s pendente), `PROCESSING`
(≤30s), `BEHIND` (mais que isso). Limite grosseiro de proposito — só um
sinal pra UI, não uma métrica de precisão.

## Presets de modelo (D.9)

`whisper_config.WHISPER_PRESETS`: `FAST` (tiny), `BALANCED` (small),
`ACCURATE` (medium), `MAXIMUM` (large-v3). A previa ao vivo usa `FAST`
por padrão (`DEFAULT_LIVE_PRESET`) — precisa terminar bem antes da
próxima janela chegar; a transcrição durável continua usando o modelo
escolhido pelo usuário (`--model`), sem mudança.

`resolve_device("cuda")` cai para `"cpu"` com um aviso no log se nenhuma
GPU CUDA compatível for detectada (`is_cuda_available()`, nunca lança
exceção) — nunca deixa a inicialização travar com um erro cru do
CTranslate2.

## Métricas (D.8/D.10)

`model_load_seconds` (tempo de carregar o modelo ao vivo) e
`avg_latency_seconds` (média das últimas 50 janelas: tempo entre o
bloco de áudio chegar e o segmento provisório ficar pronto) aparecem no
snapshot (`GET /api/transcription/live`). Não há alegação de "tempo
real" sem essa medição — os números ficam visíveis, não escondidos.

## API

`GET /api/transcription/live` (snapshot único) e
`GET /api/transcription/stream` (SSE, mesmo padrão de
`/api/audio/levels/stream`) — ver `docs/API.md`.

## Retry e falhas (D.11)

Uma janela que falha ao transcrever tenta de novo até `max_retries`
(padrão 2) antes de desistir e seguir em frente — nunca para a gravação,
nunca apaga áudio (o áudio da janela ao vivo é só um buffer em memória;
o chunk durável correspondente continua intacto em disco
independentemente do resultado da previa). Falha ao CARREGAR o modelo ao
vivo (ex.: sem espaço em disco pro download) desativa só a previa para
aquela sessão — a gravação e a transcrição durável continuam normalmente
(`test_live_transcription_failure_to_load_model_does_not_break_recording`).

## Testado

- **Com dublês** (78+ testes, `tests/test_live_*.py` +
  `tests/test_whisper_config.py`): janelas (incluindo sobreposição,
  timestamps por amostra, flush final), deduplicação (exemplo exato da
  missão + casos de borda), agregador de transcript (substituição
  committed/provisional, backlog, latência, concorrência), pipeline
  (retry, backpressure, nunca bloqueia a captura, shutdown limpo),
  presets/fallback de CUDA.
- **Integração via `cli.run()`** com Whisper fake (`tests/test_cli_
  integration.py`): segmentos committed aparecem no snapshot real após
  cada chunk durável, falha ao carregar o modelo ao vivo não derruba a
  sessão, flag desligada nunca carrega nada.
- **Hardware real** (smoke test manual, não faz parte da suite): pipeline
  completo (captura real → janela de 8s → Whisper "tiny" real → VAD real
  → snapshot atômico em disco → lido enquanto roda → limpo ao final) rodou
  de ponta a ponta sem erros, `model_load_seconds`/`backlog` corretos.
  **Não validado com hardware real**: conteúdo de texto de fato
  transcrito com fala real sobrepondo duas janelas (o teste rodou sem
  áudio falado tocando, então o resultado ficou vazio por VAD — a
  deduplicação em si já está exaustivamente coberta com dublês, mas o
  cenário "duas janelas reais, mesma fala, sobreposição real" não foi
  observado com hardware).

## Limitações conhecidas

- Sem "mixed" em tempo real (ver seção acima) — só na transcrição
  durável.
- `merge_overlapping_text` é lexical (comparação de palavras
  normalizadas), não semântico — uma reformulação da IA entre janelas
  (raro, mas possível) não seria detectada como duplicata.
- Backlog usa limites fixos (1s/30s), não adaptativos ao hardware.

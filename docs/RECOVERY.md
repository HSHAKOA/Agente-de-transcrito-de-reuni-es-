# Recuperacao de sessoes interrompidas

## O problema que isso resolve

Antes da Fase B, se o processo de gravacao morresse no meio (queda de
energia, `kill -9`, crash do driver de audio, painel fechado sem querer), o
unico rastro era um `.md` parcial e uns `.wav` dentro de uma pasta temporaria
do sistema operacional (`tempfile.mkdtemp()`), cujo caminho so existia na
memoria do processo que caiu. Na pratica, isso tende a virar lixo esquecido
em `%TEMP%` — o app nunca sabia que aquela reuniao existiu.

## Como funciona agora

Toda reuniao iniciada pelo painel (`webui.py`) ganha uma pasta persistente:

```
data/meetings/<meeting_id>/
    metadata.json   # titulo, modelo, idioma, device, caminho do .md (fixo)
    state.json      # status atual + lista de chunks (muda a cada evento)
    chunks/         # os .wav de cada bloco gravado
```

`state.json` e escrito de forma **atomica** (grava num arquivo temporario e
substitui com `os.replace`, que e atomico tanto em Windows quanto em POSIX)
— nunca fica corrompido pela metade, mesmo se o processo morrer no exato
momento de uma escrita.

### Estados possiveis

```
created      -> pasta criada, gravacao ainda nao comecou
recording    -> gravando audio
processing   -> gravacao terminou (ou ainda gravando), transcrevendo a fila
completed    -> tudo transcrito com sucesso, sessao fechada
interrupted  -> sobrou pelo menos um chunk sem transcrever (falha ou
                deteccao de crash) — pode ser reprocessada
failed       -> erro que impediu a sessao de rodar (ex.: modelo Whisper nao
                carregou) antes mesmo de gravar
```

### Deteccao automatica na inicializacao

Toda vez que `webui.py` sobe, `mark_interrupted_sessions` varre
`data/meetings/*/state.json`. Qualquer sessao ainda em `recording` ou
`processing` significa que o processo anterior morreu sem chegar a marcar um
estado final — e automaticamente rebaixada para `interrupted` **sem apagar
nenhum arquivo**. Isso e seguro rodar sempre no startup porque uma sessao
que esta genuinamente ativa nunca teria esse estado "preso": ela so existe
enquanto o processo que a criou esta vivo (e so um processo por vez, ver
`SinglePortServer`).

### Reprocessamento

O painel expoe:

- `GET /api/recovery` — lista as sessoes `interrupted` encontradas (titulo,
  quantos blocos ja foram transcritos vs. total).
- `POST /api/meetings/<id>/resume` — sobe
  `python -m meeting_transcriber --resume <meeting_dir>`, que:
  1. Le `metadata.json` (modelo/idioma/device usados originalmente);
  2. Lista os chunks cujo status **nao** e `transcribed` (novos ou que
     falharam antes);
  3. Transcreve so esses, anexando ao `.md` que ja existia (nao reescreve o
     cabecalho, nao duplica o que ja estava la);
  4. Marca `completed` se tudo deu certo, ou continua `interrupted` se
     algum chunk falhar de novo (pode ser reprocessado quantas vezes for
     preciso).

O modo `--resume` **nao abre nenhum dispositivo de audio** — funciona mesmo
numa maquina sem microfone/placa de som, o que tambem o torna facil de
testar sem hardware (ver `tests/test_cli_integration.py::
test_resume_reprocesses_only_pending_chunks_and_appends`).

## O que ainda NAO existe (fora de escopo desta fase)

- Adocao de um processo de gravacao **orfao**: se o painel (nao o
  subprocesso de gravacao) reiniciar enquanto uma gravacao segue rodando, o
  novo painel nao sabe automaticamente que aquele processo existe (ele so
  vai aparecer como "interrupted" da proxima vez que o painel checar, depois
  que a gravacao de fato terminar/morrer). Reconectar a um processo vivo e
  ainda nao gravacao e um problema separado, nao resolvido aqui.
- Exclusao automatica de audio apos processamento bem-sucedido (a opcao
  `--no-keep-audio` ja existe e so apaga cada `.wav` individual apos
  transcrever com sucesso — nunca em caso de falha/pendencia — mas a
  interface para configurar isso por sessao ainda nao existe).

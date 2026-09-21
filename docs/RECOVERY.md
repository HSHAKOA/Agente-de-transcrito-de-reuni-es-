# Recuperacao de sessoes interrompidas

## O problema que isso resolve

Antes da Fase B, se o processo de gravacao morresse no meio (queda de
energia, `kill -9`, crash do driver de audio, painel fechado sem querer), o
unico rastro era um `.md` parcial e uns `.wav` dentro de uma pasta temporaria
do sistema operacional (`tempfile.mkdtemp()`), cujo caminho so existia na
memoria do processo que caiu. Na pratica, isso tende a virar lixo esquecido
em `%TEMP%` — o app nunca sabia que aquela reuniao existiu.

## Como funciona agora

Toda reuniao iniciada pelo painel (`webui.py`) ganha uma pasta persistente,
dentro da raiz que o usuario escolheu (botao "Escolher pasta" — ver
`docs/ARCHITECTURE.md`, secao "Pasta de reunioes"; padrao antes da primeira
escolha: `Documentos/Reunioes`):

```
<raiz escolhida>/2026-09-14_1900_Reuniao-Projeto-ERP_ab12ef/
    metadata.json   # titulo, modelo, idioma, device, root_directory,
                     # meeting_directory, caminho do .md (fixo)
    state.json      # status atual + lista de chunks (muda a cada evento)
    transcript.md   # a transcricao
    chunks/         # os .wav de cada bloco (captura de UMA fonte)
    audio/          # captura simultanea: system/, microphone/ e mixed/,
                    # cada uma com os chunk_NNNNN.wav da fonte
    levels.json, live_transcript.json   # snapshots ao vivo (painel le via SSE)
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

### Deteccao automatica na inicializacao (multi-raiz, Fase B.1)

Toda vez que `webui.py` sobe (e so depois de confirmar que a porta foi
vinculada com sucesso -- rodar isso antes marcaria erroneamente uma sessao
de OUTRA instancia do painel, ainda ativa, como interrompida), `mark_
interrupted_sessions` varre `<raiz>/*/state.json` para **cada raiz
conhecida** (`settings.get_known_meeting_roots`), nao so a raiz ativa hoje.
Qualquer sessao ainda em `recording` ou `processing` significa que o
processo anterior morreu sem chegar a marcar um estado final — e
automaticamente rebaixada para `interrupted` **sem apagar nenhum
arquivo**. Isso e seguro rodar sempre no startup porque uma sessao que
esta genuinamente ativa nunca teria esse estado "preso": ela so existe
enquanto o processo que a criou esta vivo (e so um processo por vez, ver
`SinglePortServer`).

### Deteccao imediata (quando o painel ve o processo morrer)

A varredura de boot so pega o que sobrou de um painel anterior. Quando o
**proprio painel** ve o gravador terminar sem ter finalizado a sessao — o
caso tipico e o encerramento gracioso estourar o prazo e o painel escalar
para `terminate()`, que nao deixa o processo atualizar `state.json` —,
`_reader_thread` chama `session.mark_session_interrupted_if_live` **antes**
de liberar o slot de gravacao. A sessao vira `interrupted` na hora (o
historico SQLite tambem reflete isso, porque a importacao roda depois), e
aparece em `GET /api/recovery` sem precisar reiniciar o painel. Uma sessao
que terminou direito (`completed`/`interrupted`/`failed`) nunca e alterada,
e uma falha de disco ao marcar nunca impede o slot de ser liberado (o
proximo boot ainda pega a sessao).

`GET /api/recovery` e `POST /api/meetings/<id>/resume` seguem a mesma
regra: `settings.json` guarda `known_meeting_roots` (toda raiz que o
usuario ja escolheu explicitamente algum dia, deduplicada e normalizada —
nunca uma varredura arbitraria do computador) alem da `meetings_root`
ativa, e `find_meeting_dir_across_roots` procura `<raiz>/<meeting_id>/`
em cada uma delas na ordem em que aparecem. Se o usuario gravou em
`D:\Reunioes` e depois trocou para `E:\Reunioes`, uma sessao interrompida
deixada em `D:` continua aparecendo no banner e pode ser reprocessada
normalmente. Uma raiz que nao existe mais (disco desconectado) e
simplesmente pulada (`if not root.exists(): continue`) em vez de quebrar o
scan das outras.

Regras de `known_meeting_roots` (`meeting_transcriber.settings`):

- so entram raizes escolhidas explicitamente pelo usuario (botao "Escolher
  pasta" ou entrada manual) — nunca uma pasta descoberta por varredura;
- deduplicadas por caminho normalizado (`Path.resolve()`, sem exigir que a
  pasta exista);
- nunca removidas automaticamente — so `forget_meeting_root` (manual,
  ainda sem botao na UI nesta fase) apaga o REGISTRO, nunca arquivos;
  recusa remover a raiz atualmente ativa;
- uma raiz ausente nao pode quebrar o startup do painel nem `/api/recovery`
  — cada raiz e tratada independentemente, com `try/except` ao redor.

### Reprocessamento

No React, o Dashboard mostra o banner "Sessoes interrompidas encontradas"
(`components/RecoveryBanner.tsx`, hook `useRecovery`) com titulo, blocos
transcritos/total e o botao **Reprocessar**; enquanto o reprocessamento
roda o Dashboard mostra "Reprocessando uma sessao interrompida…"
(`status.mode == "resume"`, ver `docs/API.md`). O painel legado
(`index.html`) tem o mesmo card. O painel expoe:

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

## Sessao/processo orfao (Fase B.1)

### O cenario

```text
painel (webui.py) fecha ou reinicia
        ↓
o subprocesso de gravacao (python -m meeting_transcriber ...) NAO e filho
"preso" ao painel no sentido do SO -- ele continua rodando sozinho
        ↓
o novo painel nao tem mais a referencia em memoria (state["proc"]) que
apontava pra esse processo
```

### Decisao: NAO adotar processos por PID

Foi cogitado usar o PID salvo em `state.json` para "religar" a UI a um
processo de gravacao que continuou vivo depois do painel reiniciar. Essa
abordagem foi **descartada deliberadamente**: PIDs sao reciclados pelo
sistema operacional — nada garante que o processo dono daquele PID hoje
seja o mesmo processo de gravacao que o criou. "Adotar" um PID errado
significaria o painel achar que controla uma gravacao que na verdade e
outro programa qualquer (ou nada), o que e pior do que simplesmente nao
adotar nada.

**Falhar fechado**: qualquer sessao encontrada em `recording`/`processing`
na inicializacao (ver secao anterior) e sempre marcada `interrupted`,
nunca "adotada" ou re-controlada automaticamente — mesmo que o processo
original ainda esteja genuinamente vivo e gravando. Os arquivos (audio +
`state.json` parcial) nunca sao apagados; o usuario reprocessa
manualmente via `--resume` quando o processo original realmente tiver
terminado.

### Camada extra de seguranca no `--resume`: `is_pid_running`

Consequencia direta de nao adotar processos: existe uma janela em que o
usuario pode clicar "Reprocessar" numa sessao cujo processo original **na
verdade ainda esta rodando** (o painel so perdeu a referencia, o gravador
em si nunca morreu). Rodar `--resume` nesse caso faria dois processos
escreverem no mesmo `state.json`/`transcript.md` ao mesmo tempo — corrida
real, nao hipotetica.

Para mitigar isso **sem** reintroduzir adocao por PID,
`meeting_transcriber.session.is_pid_running(pid)` faz uma checagem de
melhor esforco, so Windows, via `ctypes`/API do Win32 (sem dependencia
nova): abre um handle pro PID gravado em `state.json` (`mark_recording`
grava `os.getpid()` na hora que a gravacao comeca) e confere se o
processo ainda esta ativo.

Regras de uso, propositalmente conservadoras:

- devolve `True`/`False` quando consegue verificar, ou `None` quando nao
  consegue (plataforma diferente de Windows, PID ausente, erro ao abrir o
  handle) — **`None` nunca e tratado como "esta rodando"**;
- `resume_meeting` **recusa** reprocessar somente quando a checagem
  devolve `True` (PID afirmativamente vivo) — quando devolve `None` (nao
  foi possivel verificar), o reprocessamento e permitido normalmente, para
  nao bloquear o recurso inteiro em plataformas sem essa checagem;
- isto NAO confirma identidade — um PID reciclado por outro processo
  qualquer pode gerar uma recusa falsa-positiva rara (o usuario ve "PID X
  ainda esta rodando" quando na verdade e outro programa). Esse e um
  efeito colateral aceito: um bloqueio desnecessario e seguro (o usuario
  so precisa conferir o Gerenciador de Tarefas) — o perigoso seria o
  oposto, liberar um reprocessamento que na verdade nao deveria rodar;
- nunca usada para decidir iniciar/parar/controlar um processo — so para
  decidir se `--resume` pode prosseguir com seguranca.

## O que ainda NAO existe (fora de escopo desta fase)

- Reconectar a UI a um processo de gravacao genuinamente ainda vivo depois
  do painel reiniciar (diferente de reprocessar depois que ele morreu) —
  decisao explicita de nao implementar isso por PID (ver acima); uma forma
  robusta exigiria um mecanismo de identidade mais forte que PID sozinho
  (ex.: um lock de arquivo com token unico verificado nos dois lados), que
  nao existe ainda.
- Botao na UI para "esquecer" uma raiz de `known_meeting_roots`
  (`settings.forget_meeting_root` ja existe e e testado, so falta o
  endpoint/HTML).
- Exclusao automatica de audio apos processamento bem-sucedido (a opcao
  `--no-keep-audio` ja existe e so apaga cada `.wav` individual apos
  transcrever com sucesso — nunca em caso de falha/pendencia — mas a
  interface para configurar isso por sessao ainda nao existe).

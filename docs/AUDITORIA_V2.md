# Auditoria tecnica V2 — meeting-transcriber

Data: 2026-09-14
Metodo: leitura integral do codigo real (`src/meeting_transcriber/*.py`, `webui.py`,
`index.html`, `tests/*`, `pyproject.toml`, `README.md`), execucao da suite de testes,
e um smoke test manual do `webui.py` (servidor HTTP + endpoints). Nao foi feita
nenhuma gravacao real de audio durante a auditoria (ver nota operacional no final).

## Mapa real do fluxo (confirmado lendo o codigo, nao a documentacao)

```
audio_capture.get_loopback_microphone()   -> abre o device de saida padrao (WASAPI/monitor/BlackHole)
        |
recorder.recording_worker (thread dedicada)
        |  le blocos de 0.5s (BLOCK_SECONDS) do mic.recorder()
        |  acumula em `buffer` ate juntar `chunk_seconds` (default 300s)
        v
recorder.write_chunk -> chunk_NNNNN.wav em session_dir (tempfile.mkdtemp por padrao)
        |
        v
queue.Queue[RecordedChunk]  (produtor: thread de gravacao; consumidor: thread principal)
        |
cli.run() loop principal
        |  transcriber.Transcriber.transcribe_file (faster-whisper, VAD on, sem contexto entre blocos)
        v
markdown_writer.MarkdownWriter.append_segments -> escreve incrementalmente no .md
        |
        v
webui.py: sobe cli.py como subprocess, guarda stdout/stderr num deque em memoria,
          expoe /api/start, /api/stop, /api/status; index.html faz polling a cada 1.5s.
```

Threading: 1 thread de gravacao (daemon) + thread principal consumidora, sincronizadas
por `queue.Queue` + `threading.Event` (stop_event). No lado do painel: `ThreadingHTTPServer`
(uma thread por request) + 1 thread leitora do stdout do subprocesso + 1 thread timer
de kill forcado: tudo protegido por um unico `state_lock` (`threading.Lock`).

## Baseline de testes (executado nesta auditoria)

- `pytest` direto (como o README manda rodar): **falha na coleta** —
  `ModuleNotFoundError: No module named 'meeting_transcriber'` nos dois arquivos de teste.
  O pacote nunca foi instalado (`pip install -e .`) no `.venv` do projeto e nao ha
  `pythonpath`/`conftest.py` cobrindo isso.
- `PYTHONPATH=src pytest`: **6 passed** (0 falhas). Cobertura real hoje: só
  `markdown_writer` (formatacao de timestamp, escrita incremental, no-op em lista vazia)
  e `recorder.write_chunk` (duracao, nomeacao, buffer vazio). Nada de `cli.py`,
  `webui.py`, `transcriber.py` ou do loop de gravacao com `stop_event`.

## Classificacao de problemas

### P0 — risco de perda de reuniao/dados

**P0-1. O botao "Parar" no painel nao faz shutdown gracioso — derruba o bloco atual.**
`webui.py:stop_transcriber()` chama `proc.terminate()`. No Windows isso e
`TerminateProcess` (kill duro, sem entrega de sinal); no POSIX e `SIGTERM`, para o qual
`cli.py` **nao registra handler nenhum** (só registra `SIGINT`). Ou seja: em nenhuma das
duas plataformas o clique em "Parar" aciona `handle_sigint` — a unica rotina que fecha o
stream, grava o bloco parcial do buffer e chama `writer.finalize()`. Resultado real hoje:
todo clique em "Parar" descarta o audio ainda no buffer (ate `chunk_seconds` inteiro,
i.e. ate 5 minutos por padrao) e pula a finalizacao do markdown. Isso contradiz o que o
README promete ("a gravacao para, os blocos pendentes terminam de ser transcritos") —
essa promessa so vale para `Ctrl+C` no terminal, nunca para o botao do painel.
Evidencia adicional: `webui.py:126` ja seta `creationflags = CREATE_NEW_PROCESS_GROUP`
no Windows — flag que so faz sentido para permitir `CTRL_BREAK_EVENT` via
`GenerateConsoleCtrlEvent` mais tarde — mas nada no arquivo usa isso. Parece migracao
comecada e abandonada. **Este e o item #1 explicito da missao (secao 4.1) — corrigido na Fase B.**

**P0-2. Escrita de arquivo arbitraria via `output` (path traversal / file overwrite).**
`/api/start` aceita `output` do corpo JSON e repassa direto como `--output <valor>` para
o subprocesso; `MarkdownWriter` faz `Path(valor).write_text(...)` sem nenhuma
normalizacao/checagem de diretorio. Um POST com
`{"output": "../../../../Windows/System32/drivers/etc/hosts"}` (ou um path absoluto
`C:\Users\...\qualquercoisa.md`) e aceito e escrito literalmente. Isso e alcancavel por
qualquer pagina/script que consiga bater em `127.0.0.1:8765` (cenario classico de
localhost service + CSRF/DNS-rebinding a partir de uma aba de navegador comum, ja que
o servidor nao valida `Origin`/`Host`). Corrigido na Fase B com allowlist de nome de
arquivo + `Path.resolve()` confinado a um diretorio autorizado.

**P0-3. Nao existe conceito de sessao/recuperacao.**
Se o processo, o painel ou a maquina cai no meio da gravacao, o unico rastro e o `.md`
parcial e os `.wav` dentro de um `tempfile.mkdtemp()` cujo caminho **so existe na
memoria do processo que caiu** (nunca gravado em disco de forma durável). Nao ha
`metadata.json`/`state.json`, nao ha `meeting_id`, nao ha deteccao de sessao incompleta
na proxima abertura do painel. Na pratica, o audio bruto de uma sessao interrompida
tende a virar lixo temporario esquecido em `%TEMP%` ate o SO limpar. Corrigido na Fase B
com o modelo de sessao em `data/meetings/<id>/`.

### P1 — afeta confiabilidade ou experiencia principal

**P1-1.** `pytest` sem `PYTHONPATH=src` falha (ver baseline acima) — contradiz o proprio
README. Corrigido via `[tool.pytest.ini_options] pythonpath = ["src"]`.

**P1-2.** Validacao de entrada da API praticamente inexistente: `chunk_seconds` so passa
por `int(opts.get(...) or 300)` **sem try/except** — um valor tipo `"abc"` faz
`ValueError` propagar de dentro do `state_lock`, atravessar `start_transcriber` e
`do_POST`, e o `BaseHTTPRequestHandler` devolve um 500 com traceback Python cru pro
navegador. `model`/`device`/`language`/`title` nao tem allowlist nem limite de tamanho.
`chunk_seconds` negativo ou gigante e aceito (`-1` faz `chunk_frames` negativo, entao
`buffered_frames >= chunk_frames` vira verdadeiro no primeiro bloco de 0.5s — grava um
arquivo novo a cada leitura, esgotando disco/inodes rapidamente). Sem limite de
`Content-Length` (corpo e lido inteiro em memoria antes do `json.loads`). Sem checagem
de `Origin`/`Host`. Corrigido na Fase B.

**P1-3.** Falha ao carregar o modelo Whisper (ex.: `device=cuda` sem CUDA) propaga como
excecao crua de dentro de `Transcriber.__init__`, **antes** do `try/finally` de
`cli.run()` — o `.md` ja tem cabecalho escrito (por `MarkdownWriter.__init__`) mas
`finalize()` nunca roda. No painel isso aparece so como "processo encerrado (codigo 1)"
com um traceback no log, sem mensagem amigavel nem fallback pra CPU.

**P1-4.** `webui.py` guarda o estado da gravacao (`output`, `chunk_seconds`, etc.) só em
memoria de processo. Se o processo do **painel** reiniciar enquanto o subprocesso de
gravacao continua rodando, o novo painel nao sabe que existe uma gravacao em andamento
("adotar" um processo orfao nao e possivel hoje) — `/api/stop` diria "nenhuma gravacao em
andamento" enquanto o gravador orfao continua ate travar em outro erro. Mitigado
parcialmente pela persistencia de `state.json` (permite pelo menos detectar na proxima
leitura do disco), mas adocao completa de processo orfao fica fora do escopo desta fase.

### P2 — melhorias importantes

**P2-1.** Logs sem estrutura: `logging.basicConfig` manda tudo pro stdout como texto
solto, que o painel guarda cru num `deque` e mostra verbatim — inclusive avisos internos
de bibliotecas (confirmado ao vivo durante a auditoria: linhas
`SoundcardRuntimeWarning: data discontinuity in recording` do proprio `soundcard`
aparecendo no log da sessao real em andamento). Sem separacao INFO/WARNING/ERROR para
usuario final vs. diagnostico tecnico.

**P2-2.** `Transcriber` fixa `vad_filter`, `beam_size` implicito, `temperature` padrao,
`condition_on_previous_text=False`, sem "modo avancado" nem deteccao de
CUDA-indisponivel-mas-selecionado.

**P2-3 (positivo, manter).** `SinglePortServer.allow_reuse_address = False` ja resolve
corretamente o bug classico do Windows de múltiplos processos escutando a mesma porta —
confirmado nesta auditoria: uma segunda instancia detecta `OSError` no bind e so abre o
navegador na existente, sem subir um servidor concorrente. Nao mexer nisso.

### P3 — evolucao de produto

Tudo que a missao reserva para as fases C-I (mixer microfone+loopback, streaming quase
em tempo real, abstracao de engine Whisper/presets, SQLite, historico/busca, pipeline de
inteligencia — resumo/tarefas/decisoes, diarizacao, novos exportadores, nova UI,
empacotamento). Fora de escopo deste passe.

## Nota operacional importante

Durante esta auditoria, o painel (`webui.py`) ja estava rodando em `127.0.0.1:8765` com
**uma gravacao real em andamento** (`ingles140926.md`, uma aula de ingles). Essa sessao
**nao foi tocada**: nenhum arquivo de saida dela foi lido/escrito, nenhum
`/api/stop` foi chamado contra ela, e a tentativa de smoke test desta auditoria subiu uma
segunda instancia do `webui.py` que corretamente detectou a porta ocupada (ver P2-3) e
encerrou sozinha sem competir pela porta. Todos os testes automatizados e manuais da
Fase B usam diretorios temporarios, mocks de microfone e portas efemeras — nada aqui
depende de, nem interfere com, a sessao ao vivo.

## Proxima fase

Fase B (graceful shutdown, validacao de entrada, modelo de sessao, recuperacao,
testes, revisao de seguranca, documentacao) — ver `docs/RECOVERY.md` e `docs/SECURITY.md`
apos a implementacao.

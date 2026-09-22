# Seguranca

## Modelo de ameaça

`webui.py` sobe um servidor HTTP so na interface de loopback
(`127.0.0.1`, nunca `0.0.0.0`), pensado pra um unico usuario controlando a
propria maquina pelo navegador. Mesmo assim, **"so escuta em localhost" nao
e o mesmo que "so o usuario consegue falar com ele"**: qualquer pagina aberta
no mesmo navegador (uma aba de outro site, um anuncio malicioso, uma
extensao) pode, em principio, fazer requisicoes para `127.0.0.1:8765` — esse
e o cenario que a validacao de entrada e os headers abaixo mitigam.

## O que foi corrigido na Fase B

### 1. Escrita de arquivo arbitraria (path traversal) — corrigido (e depois eliminado)

Fase B: o campo `output` do `/api/start` ia direto pra `--output <valor>` do
subprocesso, sem nenhuma checagem. Um payload como
`{"output": "../../../../Windows/System32/drivers/etc/hosts"}` seria escrito
literalmente. Corrigido entao com `validate_output_filename`, que rejeita
qualquer valor com `/`, `\`, `..`, ponto inicial, ou nome reservado do
Windows (`CON`, `NUL`, `COM1`, etc.), confirmando o resultado com
`Path.resolve()` como defesa em profundidade.

Nesta fase (escolha de pasta): o campo `output` foi **removido do contrato
da API**. `start_transcriber` nao le mais esse campo — o nome do arquivo e
sempre `transcript.md`, calculado no servidor a partir da pasta da reuniao
(que por sua vez fica sempre dentro da raiz configurada, nunca escolhida
pelo cliente por requisicao). A superficie de ataque nao esta so validada
agora: nao existe mais. `validate_output_filename` continua no codigo,
testada, disponivel pra uso futuro (ex.: nomes de arquivos de exportacao),
mas nao e mais o unico obstaculo entre uma requisicao maliciosa e uma
escrita fora de lugar. Testado com `../../arquivo.md`, `..\\..\\arquivo.md`,
`C:\\Windows\\teste.md`, `/etc/passwd` em `tests/test_validation.py` e
confirmando em `tests/test_webui.py` que um `output` malicioso simplesmente
nao tem efeito nenhum no `/api/start` real.

### 1b. Pasta-raiz escolhida pelo usuario — superficie nova, mitigada

A pasta-raiz das reunioes agora vem de `Path` fornecido pelo usuario (via
seletor nativo OU entrada manual de texto). Diferente do campo `output`
antigo, aqui NAO faz sentido confinar a um "diretorio autorizado" — o
proprio ato de escolher a raiz e o que autoriza. Mitigacoes aplicadas:
`validate_meetings_root_path` exige uma string nao vazia e resolve com
`Path.resolve()` (normaliza, nao executa nada); `check_folder_health` roda
antes de aceitar a pasta (existe/e diretorio/tem espaco/e gravavel de
verdade); trocar a raiz e bloqueado enquanto uma gravacao esta em
andamento; a raiz e persistida so localmente em `data/settings.json`,
nunca enviada a nenhum servico externo. `POST /api/open-folder` (abre a
pasta no Explorador de Arquivos) SO aceita caminhos dentro da raiz
configurada — nao pode ser usado como oráculo para abrir qualquer pasta
arbitraria da maquina.

### 2. Ausencia de allowlist/limites nos demais campos — corrigido

| Campo | Antes | Agora |
|---|---|---|
| `model` | qualquer string | allowlist (`tiny`/`base`/`small`/`medium`/`large-v3`) |
| `device` | qualquer string (so restrito no argparse da CLI, nao na API) | allowlist (`cpu`/`cuda`) |
| `language` | qualquer string | regex simples (2-5 letras, ou `auto`) |
| `chunk_seconds` | `int(x or 300)` sem try/except — `"abc"` derrubava a request com 500 | inteiro entre 5 e 1800, rejeita bool/float-nao-inteiro/negativo/gigante |
| `title` | sem limite | maximo 200 caracteres |

### 3. Corpo da requisicao sem limite — corrigido

`Content-Length` maior que 1 MB e rejeitado com 413 **antes** de ler o corpo
inteiro pra memoria (e o que e lido pra rejeitar fica limitado a um teto
fixo, mesmo que o `Content-Length` declarado minta e seja muito maior).

### 4. JSON invalido / corpo nao-objeto — corrigido

`json.loads` invalido agora responde 400 com uma mensagem JSON (nao mais uma
excecao nao tratada, que o `BaseHTTPRequestHandler` devolveria como 500 cru).
Um corpo JSON valido mas que nao e um objeto (`[1,2,3]`, `"string"`) tambem e
rejeitado com 400.

### 5. Ausencia de checagem de Host — corrigido

Toda requisicao (GET e POST) agora exige que o header `Host` seja
`127.0.0.1` ou `localhost` — mitigacao basica contra DNS rebinding (uma
pagina de outro dominio conseguindo, via truque de DNS, fazer o navegador
achar que esta falando com o dominio original enquanto na real fala com
`127.0.0.1`).

### 6. Excecoes vazando stack trace pro navegador — corrigido

Toda rota (`do_GET`/`do_POST`) agora tem um `try/except Exception` que loga
no servidor e devolve uma mensagem generica 500 — nunca mais um traceback
Python cru na resposta HTTP.

### 7. Shutdown via `terminate()`/`SIGTERM` (nao gracioso) — corrigido

Nao e uma vulnerabilidade de seguranca no sentido classico, mas e um risco
de integridade de dados: o botao "Parar" matava o processo sem dar chance
dele finalizar o `.md`/gravar o bloco parcial. Ver `docs/ARCHITECTURE.md`
("Shutdown gracioso") e `docs/AUDITORIA_V2.md` (P0-1).

## O que ja estava correto (nao mexemos)

- `SinglePortServer.allow_reuse_address = False`: impede duas instancias do
  painel escutando a mesma porta simultaneamente no Windows (bug classico do
  `http.server` nesse SO). Verificado nesta auditoria como ja funcionando.
- O servidor so escuta em `127.0.0.1` — nunca em `0.0.0.0`. Continua assim;
  nao ha (nem deve haver) opcao de configuracao pra expor isso na rede.
- Nenhuma chamada de subprocesso usa `shell=True` nem concatena entrada do
  usuario numa string de shell — `subprocess.Popen` sempre recebe uma lista
  de argumentos (`cmd = [...]`), o que evita command injection por
  construcao. Mantido assim; qualquer PR que troque isso por
  `shell=True`/f-string de comando deve ser rejeitado. `open_folder` (botao
  "Abrir pasta") segue a mesma regra: `os.startfile` no Windows e uma
  chamada direta de API do SO (nem subprocess, nem shell), e nos demais SOs
  usa `subprocess.Popen(["xdg-open"/"open", path])` — sempre lista, nunca
  string montada.

## Controles adicionados depois da Fase B (auditoria pos-missao)

Cada item abaixo foi verificado no codigo, nao so descrito:

- **Origin em todo `POST`** (`Handler._valid_origin`): uma pagina de outro
  site nao consegue, via `fetch` no navegador do usuario, chamar
  `POST /api/stop` ou `/api/start` — so `127.0.0.1:8765`, `localhost:8765` e o
  dev server do Vite (`localhost:5173`) sao aceitos; qualquer outra origem
  recebe `403`. Requisicoes **sem** `Origin` (curl, testes automatizados) sao
  permitidas de proposito: navegadores sempre mandam `Origin` em `fetch`
  cross-origin, entao a ausencia dele significa "nao veio de uma pagina".
- **Nenhum header CORS** e enviado: outras origens nao conseguem *ler* as
  respostas da API no navegador.
- **`open_folder` restrito**: so abre caminhos dentro de uma raiz de reunioes
  ja usada (`settings.get_known_meeting_roots`); nunca um caminho arbitrario
  vindo do cliente.
- **Arquivos estaticos do React**: `_serve_frontend_asset` resolve o caminho e
  recusa qualquer coisa fora de `frontend/dist/` (path traversal).
- **Exportacao**: o nome do arquivo baixado e `<meeting_id validado>.<extensao
  fixa>`; nada vem do cliente.
- **SQL**: todo valor vai por parametro (`?`) e so trechos fixos de SQL sao
  concatenados; a busca FTS5 escapa a entrada do usuario e o fallback `LIKE`
  escapa `%`, `_` e `\` (testado contra `'; DROP TABLE ...` nos dois caminhos).
- **Filtros de data invalidos** em `GET /api/meetings` respondem `400` em vez
  de serem ignorados.
- **Comando do subprocesso** nao e mais exposto no log devolvido pela API.
- **Corpo de requisicao** limitado a 1 MB (drenagem com teto), JSON invalido
  ou nao-objeto respondem `400`.

## Dados pessoais e privacidade

Audio e transcricoes sao dados pessoais e **nunca** entram no repositorio:
`data/` e ignorado, e as pastas de reuniao (`AAAA-MM-DD_HHMM_Titulo_xxxxxx/`)
sao ignoradas em qualquer profundidade (`.gitignore`) — o usuario pode ter
escolhido uma raiz dentro da propria pasta do projeto. O historico do Git foi
conferido: so contem codigo, testes e documentacao. Nada e enviado a servicos
externos (o unico acesso a rede e o download do modelo Whisper). Ao abrir uma
issue, **nao cole trechos de transcricoes nem anexe audio**.

## Como reportar uma vulnerabilidade

Nao abra uma issue publica com detalhes de exploracao. Use o **"Report a
vulnerability"** da aba *Security* do repositorio no GitHub — o *Private
vulnerability reporting* esta **habilitado**, entao esse botao existe e o
relato chega em privado. Nao ha SLA formal: e um projeto academico/pessoal
mantido por uma pessoa.

Nenhum endereco de e-mail e publicado de proposito: o canal do GitHub evita
expor um contato pessoal e ja entrega o relato em privado.

## O que fica pra depois (fora do escopo desta fase)

- Autenticacao/token no painel (hoje qualquer processo local que consiga falar
  com `127.0.0.1:8765` pode iniciar/parar gravacoes — aceitavel pro modelo de
  ameaca atual de "um usuario, uma maquina", mas relevante se o produto
  crescer). Isto inclui processos sem `Origin`, que a checagem acima permite.
- Rate limiting.
- Cabecalhos como `Content-Security-Policy` completos no `index.html` e no
  build do React servidos (hoje so `X-Content-Type-Options: nosniff` e
  enviado).

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

### 1. Escrita de arquivo arbitraria (path traversal) — corrigido

Antes: o campo `output` do `/api/start` ia direto pra `--output <valor>` do
subprocesso, sem nenhuma checagem. Um payload como
`{"output": "../../../../Windows/System32/drivers/etc/hosts"}` seria escrito
literalmente.

Agora: `meeting_transcriber.validation.validate_output_filename` rejeita
qualquer valor que contenha `/`, `\`, `..`, comece com `.`, ou corresponda a
um nome reservado do Windows (`CON`, `NUL`, `COM1`, etc.) — so um nome de
arquivo simples e aceito. O resultado ainda passa por `Path.resolve()` e uma
segunda checagem confirma que o caminho final continua sendo filho direto do
diretorio autorizado (defesa em profundidade, mesmo que a checagem de string
tenha algum caso nao previsto). Testado adversarialmente em
`tests/test_validation.py` e `tests/test_webui.py` com `../../arquivo.md`,
`..\\..\\arquivo.md`, `C:\\Windows\\teste.md`, `/etc/passwd`, etc.

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
  `shell=True`/f-string de comando deve ser rejeitado.

## O que fica pra depois (fora do escopo desta fase)

- Autenticacao/token no painel (hoje qualquer processo que consiga falar com
  `127.0.0.1:8765` pode iniciar/parar gravacoes — aceitavel pro modelo de
  ameaca atual de "um usuario, uma maquina", mas relevante se o produto
  crescer).
- Rate limiting / CSRF token dedicado (a checagem de `Host` cobre o caso
  mais comum de DNS rebinding, mas nao e uma defesa CSRF completa).
- Cabecalhos como `Content-Security-Policy` completos no `index.html`
  servido (hoje so `X-Content-Type-Options: nosniff` e enviado).

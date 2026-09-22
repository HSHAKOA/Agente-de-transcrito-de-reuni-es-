# Licenças

## A deste projeto

**Apache License 2.0** (`LICENSE`, na raiz).

O arquivo é o texto oficial de <https://www.apache.org/licenses/LICENSE-2.0.txt>
(sha256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`),
com exatamente **uma** linha alterada: o `Copyright [yyyy] [name of copyright
owner]` do apêndice, preenchido como o próprio apêndice instrui. Nenhuma
palavra do texto jurídico foi tocada — se precisar reconferir, baixe o
original e compare linha a linha.

Por que Apache-2.0 e não MIT: as duas são permissivas e compatíveis com tudo
que este projeto usa. A diferença que pesou é a **concessão explícita de
patentes** (seção 3), que a MIT não tem — relevante para um projeto que
processa áudio e pode receber contribuições de terceiros.

> Se quiser trocar o nome do titular do copyright (hoje é o nome usado nos
> commits), é só a linha 190 do `LICENSE`.

## Auditoria das dependências

Feita antes de escolher a licença, para garantir que não havia
incompatibilidade concreta. Nenhuma licença **copyleft forte**
(GPL, AGPL, LGPL, SSPL) foi encontrada em nenhuma camada.

### Backend (`requirements.txt`)

| Pacote | Versão auditada | Licença |
|---|---|---|
| `soundcard` | 0.4.6 | BSD-3-Clause |
| `faster-whisper` | 1.2.1 | MIT |
| `soundfile` | 0.14.0 | BSD-3-Clause |
| `numpy` | 2.5.2 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| `tzdata` | 2026.4 | Apache-2.0 |
| `tzlocal` | 5.4.4 | MIT |

Todas permissivas. O restante da stack é biblioteca padrão do Python
(`http.server`, `sqlite3`, `zoneinfo`), coberta pela PSF License.

### Frontend (`frontend/node_modules`, 137 pacotes)

| Licença | Pacotes |
|---|---|
| MIT | 112 |
| Apache-2.0 | 6 |
| ISC | 6 |
| MPL-2.0 | 4 |
| MIT-0 | 2 |
| BSD-2-Clause | 2 |
| BSD-3-Clause | 2 |
| CC-BY-4.0 | 1 |
| BlueOak-1.0.0 | 1 |
| CC0-1.0 | 1 |

Os quatro **MPL-2.0** são `lightningcss` e seu binário nativo
(`lightningcss-win32-x64-msvc`), puxados pelo Tailwind/Vite. A MPL-2.0 é
copyleft **por arquivo**: a obrigação só alcança modificações nos arquivos
cobertos por ela. Este projeto não modifica nem redistribui esses pacotes —
`node_modules/` não é versionado — então nada se propaga para o nosso código.

O `CC-BY-4.0` é `caniuse-lite`, uma base de dados de compatibilidade de
navegadores usada em build, também não redistribuída.

## Por que não existe `THIRD_PARTY_NOTICES.md`

Porque hoje o repositório **não redistribui código de terceiros**. Nada de
`vendor/`, nenhum arquivo copiado de outro projeto, `node_modules/` e
`frontend/dist/` fora do controle de versão. As licenças acima obrigam quem
*distribui* os binários/fontes delas — e quem faz isso, aqui, é o `pip` e o
`npm` na máquina de cada pessoa, não este repositório.

**Isso muda se:**

- o `frontend/dist/` passar a ser versionado (o build embute React e outras
  dependências MIT → vira redistribuição, e as notas de copyright MIT/BSD
  passam a ser obrigatórias); ou
- o projeto for empacotado num instalador Windows (PyInstaller/Nuitka, ver
  `docs/PENDENCIAS.md` P2) — o executável embute `numpy`, `soundcard`,
  `faster-whisper` e as bibliotecas nativas do CTranslate2.

Nos dois casos, gerar um `THIRD_PARTY_NOTICES.md` com o texto das licenças
BSD/MIT dos pacotes embutidos deixa de ser opcional. Não antecipe o arquivo
agora: uma lista de atribuições que não corresponde ao que é realmente
distribuído é pior que nenhuma.

## Modelos de Whisper

O `faster-whisper` baixa os pesos do Whisper (OpenAI) pelo Hugging Face Hub
na primeira execução. Os pesos **não** ficam neste repositório e não são
redistribuídos por ele; o modelo original do Whisper é publicado sob MIT.
Quem empacotar o app com os pesos embutidos precisa revisar isso
separadamente.

## Como reauditar

```bash
# backend
python -c "import importlib.metadata as md; [print(n, md.metadata(n).get('License') or md.metadata(n).get('License-Expression')) for n in ('soundcard','faster-whisper','soundfile','numpy','tzdata','tzlocal')]"

# frontend: percorre node_modules e agrupa pelo campo "license"
cd frontend && npm ls --all --json > /dev/null   # garante a arvore instalada
```

A varredura completa do `node_modules` usada aqui lê o campo `license` de
cada `package.json` e sinaliza qualquer ocorrência de GPL/AGPL/SSPL/
proprietário. Rode de novo depois de qualquer `npm install` que mude o
`package-lock.json`.

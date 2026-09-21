# Contribuindo

## Instalar

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Testar

```bash
pytest
```

A suite (600+ testes) roda majoritariamente com dublês (áudio, relógio,
Whisper) — não precisa de microfone/placa de som real nem de baixar
nenhum modelo. Testes que exigem hardware real de áudio ficam em
`tests/test_*_hardware.py` e são pulados automaticamente quando não há
dispositivo de áudio disponível no ambiente.

Frontend (`frontend/`, a interface ativa — servida por `webui.py` a partir
de `frontend/dist/`):

```bash
cd frontend
npm ci
npm run build   # tsc (type-check) + vite build -> dist/
npx oxlint
npm test        # vitest (componentes e hooks)
```

O CI (`.github/workflows/ci.yml`) roda exatamente estes passos, mais
`pytest` no backend — rode-os localmente antes de abrir um PR.

## Arquitetura

Ver `docs/ARCHITECTURE.md` para a visão geral e `docs/FLOWCHARTS.md` para
os fluxos detalhados. Cada subsistema novo tem seu próprio doc
(`docs/SCHEDULING.md`, `docs/LIVE_TRANSCRIPTION.md`, `docs/DATABASE.md`).

## Estilo de commit

Commits pequenos e semânticos, no padrão `tipo(escopo): descrição`:

```
feat(transcription): add low-latency transcription windows
fix(recovery): scan known meeting roots
docs(architecture): add end-to-end system flowcharts
test(audio): verify one source crashing mid-recording doesn't hang the other
```

Nunca `"update"`, `"fix stuff"`, `"final"` — a mensagem deve explicar o
*porquê*, não só repetir o diff.

## Dados pessoais

Áudio e transcrições de reuniões são dados pessoais e **nunca** entram no
repositório. O `.gitignore` já ignora `data/` e as pastas de reunião
(`AAAA-MM-DD_HHMM_Titulo_xxxxxx/`) em qualquer profundidade, mas confira o
`git status` antes de commitar e prefira `git add <caminho>` a `git add -A`.
Em issues e PRs, não cole trechos de transcrições nem anexe áudio.

## Issues, PRs e segurança

Use os modelos em `.github/` (bug, sugestão, pull request). Para uma
vulnerabilidade, **não** abra uma issue pública: veja `docs/SECURITY.md`.

## Princípios do projeto

- **Local-first / offline-first**: nenhuma dependência de nuvem
  obrigatória.
- **Nunca perder áudio**: qualquer mudança na captura/transcrição precisa
  preservar a garantia de que a gravação nunca espera a transcrição.
- **Encerramento sempre gracioso**: nunca `kill()`/`terminate()` como
  primeiro recurso.
- **Nunca fingir**: não declarar uma integração funcionando sem executá-la
  de verdade; distinguir sempre "testado com dublê" de "testado com
  hardware real".

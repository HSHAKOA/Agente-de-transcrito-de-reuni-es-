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

Frontend (`frontend/`, ainda não é a interface ativa — ver
`docs/PENDENCIAS.md`):

```bash
cd frontend
npm ci
npm run build   # tsc (type-check) + vite build
npx oxlint
```

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

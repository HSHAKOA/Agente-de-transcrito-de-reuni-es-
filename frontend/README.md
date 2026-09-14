# Frontend React (preview arquitetural — Fase F)

**Este NÃO é o frontend ativo do produto.** O painel real continua sendo
`index.html` + `webui.py`, em `http://127.0.0.1:8765` — é o que
`iniciar.bat` abre e o que tem paridade funcional completa hoje (escolha
de pasta, iniciar/parar gravação, recuperação de sessão, etc.).

Isto aqui é a preparação arquitetural da migração para React descrita no
roadmap (`docs/ROADMAP.md`), que so acontece de fato na **Fase F** — depois
de dispositivos de áudio (Fase C), transcrição quase em tempo real (Fase
D) e SQLite/histórico (Fase E), porque a API vai crescer bastante nessas
fases e construir telas de produto agora significaria refazer boa parte
do trabalho depois.

## O que existe aqui agora

- Toolchain funcionando de ponta a ponta: Vite + React 19 + TypeScript +
  Tailwind CSS v4, com `npm run build` gerando `dist/` (tipo-checado com
  `tsc -b`, verificado nesta sessão).
- `src/types/api.ts` — tipos TypeScript que espelham o contrato **real**
  atual do backend (`webui.py`), não uma lista hipotética de endpoints.
- `src/services/api.ts` — cliente HTTP tipado para esse contrato.
- `src/hooks/useBackendStatus.ts` / `useSettingsInfo.ts` — polling
  centralizado (substituindo os `setInterval` soltos do `index.html`
  atual) para `/api/status` e `/api/settings`.
- `src/app/App.tsx` — uma tela minima que prova que o toolchain consegue
  ler o estado real do painel Python (conectado/desconectado, pasta
  configurada, espaço livre) — não é a tela de produto (Dashboard, Nova
  reunião, Gravação, ...), que só entra na Fase F de verdade.

`pages/`, `components/ui/`, `features/` e `hooks/` (além do que já existe)
ficam vazios de proposito — não há telas de produto reais pra colocar
neles ainda, e criar arquivos vazios "de mentirinha" so pra preencher a
estrutura violaria a regra de não declarar placeholder como feature
pronta.

## Rodando

```bash
cd frontend
npm install
npm run dev     # abre em http://localhost:5173, com proxy de /api/* para
                 # http://127.0.0.1:8765 (o webui.py real precisa estar rodando)
npm run build   # gera dist/ — ainda nao e servido pelo webui.py
```

## Quando a Fase F realmente começar

Seguir o processo de migração descrito na missão original: entender o
comportamento atual → criar equivalente em React → validar paridade
funcional → testar → só então trocar o frontend ativo → remover o HTML
legado por último. `webui.py` passará a servir `frontend/dist/` em vez de
`index.html` só depois que essa paridade for demonstrada, não antes.

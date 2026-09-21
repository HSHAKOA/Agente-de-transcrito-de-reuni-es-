## O que muda e por quê

<!-- O *porquê* importa mais que o diff. Link para a issue, se houver. -->

## Como foi verificado

- [ ] `pytest -q` (backend)
- [ ] `cd frontend && npm run build && npx oxlint && npm test` (se tocou no frontend)
- [ ] Um bug corrigido tem um teste que **falha sem a correção**
- [ ] Testei o caminho de erro, não só o caminho feliz

## Checklist

- [ ] Commits pequenos, no formato `tipo(escopo): descrição`
- [ ] Documentação atualizada (`docs/`, `README.md`) se o comportamento mudou
- [ ] **Nenhum dado pessoal**: sem áudio, transcrições, `data/`, pastas de reunião nem `.env`
- [ ] Sem `shell=True` nem comando montado por concatenação de string
- [ ] Mantém o offline-first e a garantia de nunca perder áudio

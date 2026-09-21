# Pendências

Priorização honesta do que falta. Nada aqui foi escondido: cada item também
aparece na fase correspondente (`docs/ROADMAP.md`). Também acompanhadas como
[Issues no GitHub](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues)
(agrupadas, não uma por item):

- [#1](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues/1) — Telas de produto React (P1) — **fechada**
- [#2](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues/2) — Migração de schedules + Task Scheduler (P1)
- [#3](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues/3) — Meeting Intelligence (P2)
- [#4](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues/4) — Diarização completa + empacotamento (P2)
- [#5](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues/5) — DOCX/PDF + polimento (P2/P3)

## O que separa o estado atual da V1.0

A V1.0 ("Open Source Stable") não é ter todas as features: é produto
reproduzível, core estável, testes, docs e GitHub organizados.

| Critério | Estado |
|---|---|
| Core estável (áudio, transcrição, recovery, agendador, SQLite) | pronto, com a ressalva da validação real abaixo |
| React funcional, 8 telas + recuperação, cada uma testada | pronto |
| Histórico dedicado (busca, status, período, paginação) | pronto |
| Testes reproduzíveis (backend 648, frontend 79) | pronto localmente; **CI ainda não confirmado verde** |
| CI verde (backend, build, lint, testes do frontend) | corrigido e verificado localmente; **precisa do push** |
| Sem dados pessoais no repositório | pronto (histórico do Git conferido; `.gitignore` por assinatura) |
| Docs alinhados com o código | pronto para o que foi tocado; ver "Documentação" abaixo |
| Templates de issue/PR, CONTRIBUTING, SECURITY | pronto |
| **`LICENSE`** | **decisão do proprietário — pendente** |
| **Relato privado de vulnerabilidade** | **habilitar no GitHub — pendente** |
| Instalação reproduzível num clone limpo | parcial: `frontend/dist/` não é versionado (ver P2) |

## P0 — bloqueiam uma demonstração completa

Nenhuma. O fluxo principal (gravar, transcrever ao vivo e de forma durável,
parar, recuperar, agendar, buscar, exportar) funciona e está testado.

## P1 — valem antes de chamar de V1.0

1. **Confirmar o CI verde depois do push.** O CI nunca esteve verde (9/9 runs
   falharam). Foram corrigidas as 4 causas e a suíte roda igual sob `TZ=UTC0`
   e com sondas de áudio reais proibidas — mas isso só é prova local. O job de
   frontend (Ubuntu, Node 22) passou a rodar `npm test` e não foi exercitado
   fora do Windows.
2. **Validar com hardware real o que mudou no encerramento e no
   reprocessamento.** Espera ciente de progresso, marca imediata de
   `interrupted` e "Reprocessar" pelo React só rodaram com dublês e HTTP
   simulado. Uma gravação longa real (≥ 15 min) parada pelo painel deve
   terminar em `completed`.
3. **Reunião real de 21/09 aguardando Reprocessar** (9/11 blocos; áudio
   íntegro) — ver `docs/HANDOFF_PROXIMA_SESSAO.md`.
4. **Speaker por segmento.** Hoje o rótulo é por reunião; na captura
   simultânea tudo vira "Reunião". O áudio por canal já é guardado
   (`audio/microphone/`, `audio/system/`), então dá para atribuir cada
   segmento ao canal dominante (energia RMS na janela) sem regravar e sem
   diarização por voz. Só funciona com `keep_audio` ligado.
5. **Migrar `schedules.json` para SQLite** — plano pronto em
   `docs/DATABASE.md`. Sem urgência (o agendador funciona em JSON); vale
   quando algo precisar consultar agendamentos junto com reuniões.
6. **Windows Task Scheduler (Nível 2 do agendamento).** Um agendamento só
   dispara com o painel aberto. Não prometer antes de validar "acordar o
   computador" nesta máquina.

### Corrigido pela retomada (histórico)

CI vermelho (teste tocando a placa de som real; mensagens no fuso do PC);
sessão morta ficava `processing`; React sem banner de recuperação; **todo
"Parar" de gravação longa caía em `terminate()`**; busca sem paginação e
filtro de data que excluía o dia inteiro; testes vazando reuniões-fantasma
para o banco real; pastas de reunião fora do `.gitignore`; docs defasados e
o banner "Prévia (Fase F)" em toda tela. Detalhe e evidências em
`docs/HANDOFF_PROXIMA_SESSAO.md`.

## P2 — features avançadas e polimento

7. **Meeting Intelligence (Fase G)** — projeto revisável em
   `docs/INTELLIGENCE.md` (provider plugável, validador anti-alucinação,
   modelo de dados). Nenhum código escrito.
8. **Diarização por voz (Fase H completa).**
9. **Empacotamento Windows** (PyInstaller/Nuitka) — `iniciar.bat` continua
   sendo o fluxo real. Junto vai o problema de `frontend/dist/` não ser
   versionado: um clone limpo mostra o painel legado até rodar
   `npm run build` (documentado em `docs/APRESENTACAO_PROFESSOR.md`).
10. **DOCX/PDF** — só Markdown/TXT/JSON/SRT/VTT existem.
11. **Acessibilidade** — só o Histórico e o banner de recuperação têm
    `aria-*`/`role` sistemáticos; Dashboard, Nova Reunião, Gravação,
    Agendamentos e Configurações não foram auditados (teclado, foco,
    contraste, leitores de tela).
12. **Reuniões-fantasma no `data/meetings.db` real.** Três linhas
    (`20260101-000000-ffffff`, `-222222`, `-333333`) apontam para pastas
    temporárias do pytest de 15/09. O vazamento foi corrigido na fixture, mas
    as linhas ficaram e aparecem no Histórico como "Interrompida"/"Gravando".
    Limpeza segura (soft delete, não toca em arquivo):
    `POST /api/meetings/<id>/delete` para cada um. Melhoria de produto: a
    importação poderia marcar como removidas as linhas cuja pasta não existe
    mais.
13. **Avisos de depreciação do Node 20 nas Actions** (`actions/checkout@v4`,
    `setup-python@v5`, `setup-node@v4`) — só avisos; atualizar as versões.

## P3 — polimento

14. Sem endpoint para "restaurar" uma reunião excluída (soft delete).
15. `merge_overlapping_text` (Fase D) é lexical, não semântico.
16. Os limites do backlog ao vivo (`LIVE`/`PROCESSING`/`BEHIND`: 1 s / 30 s)
    são fixos, não adaptativos ao hardware.
17. Sem teste automatizado de reconexão do SSE no meio de uma gravação.
18. O `vitest` estoura o timeout de início de workers se rodar junto com o
    `pytest` (CPU saturada) — rode em sequência.
19. O fim de cada segmento importado de um `.md` é aproximado pelo início do
    próximo (o último fica com duração zero; SRT/VTT já aplicam o mínimo de
    0,5 s — limitação documentada em `docs/DATABASE.md`).

## Licença e decisões do proprietário

Sem `LICENSE`: a missão proíbe escolher uma licença jurídica em nome de quem
não decidiu isso. Sem ela, o código é "todos os direitos reservados" — para
um projeto que será portfólio/open source, é a primeira decisão da V1.0
(MIT e Apache-2.0 são as escolhas usuais; a diferença relevante é a
concessão explícita de patentes da Apache). Também dependem do proprietário:
habilitar *Private vulnerability reporting* no GitHub e, se quiser, um
`CODE_OF_CONDUCT.md` (exige um contato de moderação, que não deve ser
inventado).

## Testado com hardware real vs. só com dublês

Ver a seção "Testado" de cada `docs/<FASE>.md` (`AUDIO` em `docs/API.md`,
`docs/LIVE_TRANSCRIPTION.md`, `docs/SCHEDULING.md`, `docs/DATABASE.md`) para a
distinção exata IMPLEMENTADO ≠ TESTADO COM FAKE ≠ TESTADO COM HARDWARE REAL em
cada fase — nunca conflate os três. Nesta retomada **nada foi testado com
hardware real**: o que mudou no encerramento e no reprocessamento está
coberto por dublês e por testes HTTP (item P1-2).

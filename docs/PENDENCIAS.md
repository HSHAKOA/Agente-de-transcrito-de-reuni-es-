# Pendências

Priorização honesta do que falta, ao final desta sessão. Nada aqui foi
escondido: cada item também aparece na fase correspondente
(`docs/ROADMAP.md`) e no relatório final da missão. Também
acompanhadas como [Issues no GitHub](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues)
(agrupadas, não uma por item):

- [#1](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues/1) — Telas de produto React (P1)
- [#2](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues/2) — Migração de schedules + Task Scheduler (P1)
- [#3](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues/3) — Meeting Intelligence (P2)
- [#4](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues/4) — Diarização completa + empacotamento (P2)
- [#5](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues/5) — DOCX/PDF + polimento (P2/P3)

## P0 — bloqueiam uma demonstração completa

Nenhuma pendência P0 identificada. O fluxo principal (gravar sistema+
microfone, transcrever ao vivo e de forma durável, recuperar sessão
interrompida, agendar, buscar histórico, exportar) funciona de ponta a
ponta e está testado.

## P1 — reduzem a experiência ou a superfície de produto

1. **Telas de produto React (Fase F)** — maioria do ciclo principal feita.
   - Feito: **Dashboard**, **Detalhe da reunião** (export em 5 formatos,
     abas Resumo/Tarefas/Decisões honestamente marcadas "não
     processado"), **Gravação** (níveis + transcrição ao vivo via SSE,
     parar), **Agendamentos** (listar, iniciar agora, cancelar, ignorar
     perdida), **Nova Reunião** (formulário completo, testar áudio,
     iniciar — a primeira tela que de fato inicia uma gravação real).
     O ciclo criar → gravar → ver já é 100% navegável em React. Todas
     verificadas contra o `webui.py` real (proxy do Vite).
   - Falta: **criar/editar agendamento** (precisa de um formulário de
     data/hora/recorrência — o backend já suporta tudo,
     `POST /api/schedules`/`POST /api/schedules/<id>`); **Configurações**
     (hoje só a pasta é ajustável, dentro de Nova Reunião). `index.html`
     continua sendo a referência até esses dois ficarem prontos e a
     paridade funcional completa ser demonstrada.

2. **Migração de `schedules.json` para SQLite**
   - Impacto: nenhum na prática (o scheduler funciona corretamente em
     JSON), mas duas fontes de persistência coexistem.
   - Próximo passo: quando o schema SQLite crescer para incluir
     `SCHEDULE`/`SCHEDULE_RUN` (ver `docs/FLOWCHARTS.md`, diagrama 6),
     migrar com o mesmo padrão de `storage/import_filesystem.py`
     (idempotente, nunca apaga o JSON até a migração ser confirmada).

3. **Windows Task Scheduler (Nível 2 do agendamento)**
   - Impacto: um agendamento só dispara se o painel já estiver aberto no
     horário. Documentado explicitamente em `docs/SCHEDULING.md`, nunca
     escondido.
   - Próximo passo: investigar `schtasks`/API do Task Scheduler para
     iniciar `webui.py` alguns minutos antes de um agendamento — só
     depois de validar `Wake the computer to run this task` de verdade
     nesta máquina/empacotamento (nunca prometer sem testar).

## P2 — features avançadas não iniciadas

4. **Meeting Intelligence (Fase G)** — resumo/tarefas/decisões/tópicos.
   Nenhum código escrito; arquitetura de provider plugável documentada
   em `docs/FLOWCHARTS.md` (diagrama 7).
5. **Diarização completa (Fase H)** — hoje só rótulo por canal (`Você`/
   `Áudio da reunião`), nunca por voz individual dentro do mesmo canal.
6. **Empacotamento Windows (PyInstaller/Nuitka)** — `iniciar.bat`
   continua sendo o fluxo real e funcional; um `.exe` de um clique não
   foi avaliado.
7. **DOCX/PDF** — só Markdown/TXT/JSON/SRT/VTT foram implementados.

## P3 — polimento

8. Sem endpoint de "restaurar" uma reunião soft-deletada (precisa ir
   direto ao repositório hoje).
9. `merge_overlapping_text` (Fase D) é lexical, não semântico — uma
   reformulação da IA entre janelas adjacentes não seria detectada como
   duplicata (caso raro na prática).
10. Backlog de transcrição ao vivo (`LIVE`/`PROCESSING`/`BEHIND`) usa
    limites fixos (1s/30s), não adaptativos ao hardware da máquina.
11. Sem teste de fluxo completo (SSE) automatizado para reconexão de
    cliente no meio de uma gravação — coberto só pelo tratamento de
    exceção no servidor (`BrokenPipeError`/etc.), não por um teste
    dedicado de reconexão.

## Licença

Repositório sem `LICENSE` — decisão do proprietário, não tomada nesta
sessão de propósito (a missão explicitamente proíbe escolher uma licença
jurídica em nome de quem não decidiu isso). Pendência registrada aqui,
não um arquivo criado por suposição.

## Testado com hardware real vs. só com dublês

Ver a seção "Testado" de cada `docs/<FASE>.md` (`AUDIO` em
`docs/API.md`, `docs/LIVE_TRANSCRIPTION.md`, `docs/SCHEDULING.md`,
`docs/DATABASE.md`) para a distinção exata IMPLEMENTADO ≠ TESTADO COM
FAKE ≠ TESTADO COM HARDWARE REAL em cada fase — nunca conflate os três.

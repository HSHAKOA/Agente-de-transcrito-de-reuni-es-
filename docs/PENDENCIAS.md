# Pendências

Priorização honesta do que falta, ao final desta sessão. Nada aqui foi
escondido: cada item também aparece na fase correspondente
(`docs/ROADMAP.md`) e no relatório final da missão.

## P0 — bloqueiam uma demonstração completa

Nenhuma pendência P0 identificada. O fluxo principal (gravar sistema+
microfone, transcrever ao vivo e de forma durável, recuperar sessão
interrompida, agendar, buscar histórico, exportar) funciona de ponta a
ponta e está testado.

## P1 — reduzem a experiência ou a superfície de produto

1. **Telas de produto React (Fase F)**
   - Impacto: `index.html` continua sendo a única interface real; a
     migração para React não avançou além do toolchain + cliente HTTP
     tipado (`frontend/`).
   - Próximo passo: construir Dashboard, Nova Reunião, Gravação (com o
     player de nível + transcrição ao vivo via SSE) e Histórico, nessa
     ordem — são as telas com maior valor de demonstração. `frontend/src/services/api.ts`
     e `frontend/src/types/api.ts` já cobrem 100% do contrato atual.

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

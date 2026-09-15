# Pendências

Priorização honesta do que falta, ao final desta sessão. Nada aqui foi
escondido: cada item também aparece na fase correspondente
(`docs/ROADMAP.md`) e no relatório final da missão. Também
acompanhadas como [Issues no GitHub](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues)
(agrupadas, não uma por item):

- [#1](https://github.com/HSHAKOA/Agente-de-transcrito-de-reuni-es-/issues/1) — Telas de produto React (P1) — **fechada**: as 5 falhas P1 da auditoria pós-missão foram corrigidas; resta só Histórico paginado (ver abaixo)
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

Uma auditoria independente pós-missão (`auditoria_gemini.md`) encontrou 5
problemas P1 reais que impediam considerar o produto pronto pra demo,
todos confirmados no código e corrigidos numa sessão dedicada:

1. ~~Bug de navegação ejetava o usuário da tela de Gravação~~ **CORRIGIDO**
   — `App.tsx` checava `status.running` do poll ANTERIOR no mesmo render
   em que `NewMeeting` mudava a view, voltando pro Dashboard antes do
   status novo chegar. Corrigido com um estado de transição explícito
   (`recording.phase: "starting" | "active"`), sem timeout arbitrário.
2. ~~Reuniões terminadas nunca eram indexadas no SQLite~~ **CORRIGIDO**
   — `_reader_thread` agora chama `import_meeting` automaticamente
   quando o processo de gravação termina; antes disso o histórico só
   era populado se alguém chamasse `POST /api/meetings/import`
   manualmente, o que nenhuma tela fazia.
3. ~~`webui.py` não servia o build do React~~ **CORRIGIDO** — React é
   agora a interface ativa e padrão, servida direto por `webui.py`
   quando `frontend/dist/` existe (fallback SPA pra rotas client-side,
   nunca intercepta `/api/*`). `index.html` legado só é servido se o
   build não existir.
4. ~~Leituras do SQLite sem lock~~ **CORRIGIDO** — só escritas eram
   protegidas; leituras concorrentes na mesma conexão compartilhada
   causavam `sqlite3.InterfaceError` sob carga real (reproduzido antes
   de corrigir). Agora toda operação do `MeetingRepository` é
   serializada.
5. ~~Duplo clique em "Parar" podia disparar shutdown concorrente~~
   **CORRIGIDO** — `state["stopping"]` explícito recusa (409) um
   segundo `POST /api/stop` enquanto o primeiro ainda está em
   andamento; o React mostra "Finalizando reunião..." em vez de
   assumir que a gravação parou assim que o endpoint responde 200.

**Ainda falta pra "paridade funcional completa" de verdade** (Fase F):
uma tela de Histórico dedicada com paginação (hoje só a busca + últimas
5 reuniões do Dashboard); cobertura de teste automatizado mais ampla no
frontend (vitest cobre o ciclo de vida da gravação, formulários
críticos e o hook de SSE — não cobre ainda `Schedules.tsx`/
`Settings.tsx`/`Recording.tsx` isoladamente); exercitar os formulários
de escrita (Nova Reunião, agendamento) clicando de verdade num navegador
contra o backend real — verificado por testes automatizados (vitest com
backend mockado, e um smoke test HTTP end-to-end com o servidor real e
um subprocesso de gravação simulado), nunca clicando manualmente numa
aba de navegador aberta pra essa finalidade nesta sessão.

6. **Migração de `schedules.json` para SQLite**
   - Impacto: nenhum na prática (o scheduler funciona corretamente em
     JSON), mas duas fontes de persistência coexistem.
   - Próximo passo: quando o schema SQLite crescer para incluir
     `SCHEDULE`/`SCHEDULE_RUN` (ver `docs/FLOWCHARTS.md`, diagrama 6),
     migrar com o mesmo padrão de `storage/import_filesystem.py`
     (idempotente, nunca apaga o JSON até a migração ser confirmada).

7. **Windows Task Scheduler (Nível 2 do agendamento)**
   - Impacto: um agendamento só dispara se o painel já estiver aberto no
     horário. Documentado explicitamente em `docs/SCHEDULING.md`, nunca
     escondido.
   - Próximo passo: investigar `schtasks`/API do Task Scheduler para
     iniciar `webui.py` alguns minutos antes de um agendamento — só
     depois de validar `Wake the computer to run this task` de verdade
     nesta máquina/empacotamento (nunca prometer sem testar).

## P2 — features avançadas não iniciadas

8. **Meeting Intelligence (Fase G)** — resumo/tarefas/decisões/tópicos.
   Nenhum código escrito; arquitetura de provider plugável documentada
   em `docs/FLOWCHARTS.md` (diagrama 9).
9. **Diarização completa (Fase H)** — hoje só rótulo por canal (`Você`/
   `Áudio da reunião`), nunca por voz individual dentro do mesmo canal.
10. **Empacotamento Windows (PyInstaller/Nuitka)** — `iniciar.bat`
    continua sendo o fluxo real e funcional; um `.exe` de um clique não
    foi avaliado.
11. **DOCX/PDF** — só Markdown/TXT/JSON/SRT/VTT foram implementados.

## P3 — polimento

12. Sem endpoint de "restaurar" uma reunião soft-deletada (precisa ir
    direto ao repositório hoje).
13. `merge_overlapping_text` (Fase D) é lexical, não semântico — uma
    reformulação da IA entre janelas adjacentes não seria detectada como
    duplicata (caso raro na prática).
14. Backlog de transcrição ao vivo (`LIVE`/`PROCESSING`/`BEHIND`) usa
    limites fixos (1s/30s), não adaptativos ao hardware da máquina.
15. Sem teste de fluxo completo (SSE) automatizado para reconexão de
    cliente no meio de uma gravação — coberto só pelo tratamento de
    exceção no servidor (`BrokenPipeError`/etc.), não por um teste
    dedicado de reconexão.
16. `frontend/dist/` não é versionado (`.gitignore`) -- um checkout novo
    do repositório precisa rodar `cd frontend && npm run build` uma vez
    antes de `iniciar.bat` mostrar o React (senão cai pro painel legado,
    que continua funcional). Documentado em `docs/APRESENTACAO_PROFESSOR.md`.

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

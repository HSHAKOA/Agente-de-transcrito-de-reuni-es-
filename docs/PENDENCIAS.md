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
| Testes reproduzíveis (backend, frontend) | pronto |
| CI verde (backend, build, lint, testes do frontend) | **verde** desde o run 35668708065 (era 9/9 vermelho) |
| Sem dados pessoais no repositório | pronto (histórico do Git conferido; `.gitignore` por assinatura) |
| Docs alinhados com o código | pronto para o que foi tocado (ARCHITECTURE, API, RECOVERY, SECURITY, DATABASE, TESTING, FLOWCHARTS, SCHEDULING, LICENSES); os demais `docs/<FASE>.md` não foram reauditados |
| Templates de issue/PR, CONTRIBUTING, SECURITY | pronto |
| `LICENSE` | **pronto** — Apache-2.0, com auditoria em `docs/LICENSES.md` |
| Relato privado de vulnerabilidade | **habilitado** no GitHub |
| Instalação reproduzível num clone limpo | parcial: `frontend/dist/` não é versionado (ver P2) |
| `CODE_OF_CONDUCT.md` | **pendente — depende do proprietário** (ver abaixo) |

## P0 — bloqueiam uma demonstração completa

Nenhuma. O fluxo principal (gravar, transcrever ao vivo e de forma durável,
parar, recuperar, agendar, buscar, exportar) funciona e está testado.

## P1 — valem antes de chamar de V1.0

1. **Validar com hardware real o que mudou no encerramento e no
   reprocessamento.** Espera ciente de progresso, marca imediata de
   `interrupted` e "Reprocessar" pelo React só rodaram com dublês e HTTP
   simulado. Uma gravação longa real (≥ 15 min) parada pelo painel deve
   terminar em `completed`.
2. **Reunião real de 21/09 aguardando Reprocessar** (9/11 blocos; áudio
   íntegro) — ver `docs/HANDOFF_PROXIMA_SESSAO.md`.
3. **Transcrição durante a gravação satura a CPU.** Medido em 21/09/2026
   num i5-11400H (6 núcleos/12 threads): com `small` em CPU e blocos de
   300 s, a transcrição durável mantém a máquina em **99-100%** durante toda
   a gravação, e o `soundcard` emite `data discontinuity in recording`. A
   gravação não é perdida (o áudio já está em disco antes da transcrição),
   mas o backlog cresce e o encerramento precisa drená-lo. Não há hoje
   nenhum limite de paralelismo nem opção de "transcrever só no final".
   Investigar antes de prometer transcrição ao vivo em máquina modesta.
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
filtro de data que excluía o dia inteiro; servidor que recusava Host/Origin
sem ler o corpo (reset de conexão sob carga); testes vazando reuniões-fantasma
para o banco real; pastas de reunião fora do `.gitignore`; docs defasados e
o banner "Prévia (Fase F)" em toda tela. Detalhe e evidências em
`docs/HANDOFF_PROXIMA_SESSAO.md`.

Na sessão seguinte (21/09, noite), disparado por um agendamento real que não
gravou: preflight que **levantava exceção** e fazia a ocorrência ser marcada
`missed` com a causa errada; fuso que deixa de resolver derrubando todo tick
em silêncio; painel que subia sem as dependências e só falhava na hora da
aula; `iniciar.bat` sem checagem de Python/venv/build. Reconstituição
completa em `docs/SCHEDULING.md` ("Incidente 21/09/2026"). Também nesta
sessão: `LICENSE` (Apache-2.0), relato privado de vulnerabilidade habilitado,
as 3 reuniões-fantasma removidas do banco real e as Actions atualizadas
(fim dos avisos de Node 20).

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
11. **Acessibilidade** — auditada em 21/09/2026 (só leitura de código; nada
    testado com leitor de tela real ainda). Em ordem de impacto:

    **Corrigido nesta sessão** (3 testes que falham no código anterior):

    - **Campos sem nome acessível.** Em Nova Reunião e Agendamento os
      `<label>` eram **irmãos** do campo, sem `htmlFor`/`id` — um leitor de
      tela anunciava "campo de edição, vazio" e clicar no rótulo não focava
      nada. Pareados (11 campos). Os `<select>` de dispositivo do
      `AudioSourcePicker` e o campo de caminho de Configurações, que não
      tinham rótulo visível próprio, ganharam `aria-label`.
    - **`<label>` sobre grupo de botões.** "Dispositivo de inferência"
      rotulava dois `<button>`, e `<label>` só rotula controle de
      formulário — na prática não rotulava nada. Virou `role="group"` com
      `aria-labelledby`, e os botões ganharam `aria-pressed` (a cor sozinha
      não comunica seleção).
    - **Regiões vivas na tela de Gravação.** Transcrição ao vivo com
      `aria-live="polite"` (nunca `assertive`: chega texto novo a cada
      poucos segundos por horas), "Finalizando…" com `role="status"`, erro
      de parada com `role="alert"`.
    - Os dois rótulos de seção da Gravação viraram `<h2>`.

    **Correção de uma afirmação anterior deste documento:** estava escrito
    que *nenhum* campo tinha nome acessível. Falso. O **Histórico já estava
    correto** (busca com `aria-label`, e os três filtros envolvem o controle
    dentro do `<label>`, que é associação implícita válida), e os
    *checkboxes* do `AudioSourcePicker` também já estavam. O erro veio de
    contar `<label>` e `htmlFor` por arquivo sem verificar se o rótulo
    envolvia o campo.

    **Ainda pendente:**

    1. Dashboard, Detalhe da Reunião e Agendamentos seguem sem nenhum
       `aria-*`/`role`.
    2. Fora da Gravação, os rótulos de seção continuam `<p>` estilizado —
       não há hierarquia de títulos para navegar.
    3. Não auditados com ferramenta: contraste medido, ordem de tabulação,
       foco visível em todos os controles, alvo de toque.
    4. Nada testado com leitor de tela real.

    Regras-alvo em `DESIGN.md`, seção 9.
12. **`LevelBar` anima `width` 10x por segundo.** `transition-[width]
    duration-150` num medidor que recebe amostra a cada 100 ms: cada quadro
    força recálculo de layout, numa máquina que já está a 100% de CPU
    transcrevendo. Pior, a transição faz a barra **atrasar** em relação ao
    áudio — um medidor atrasado é um medidor mentiroso. Remover a transição
    (ver `MOTION.md`, seção 5).
13. **Código morto no `_process_schedule_step`.** Os ramos que tratam
    `MISSED`/`FAILED` são inalcançáveis: os dois status são terminais, então
    o topo da função reclama a próxima ocorrência antes de chegar neles. O
    caminho real é `start_now`/`ignore_missed`. Limpar quando alguém mexer
    no arquivo — não vale um commit isolado, mas confunde quem lê.
14. **Importação não reconcilia status.** Uma reunião importada enquanto
    estava `processing` continua `processing` no SQLite mesmo depois de a
    sessão em disco virar `interrupted`/`completed` (três das quatro
    reuniões reais estão assim hoje). O Histórico mostra um status
    desatualizado até a reunião ser reimportada.
    **Não** resolver marcando como removida toda linha cuja pasta sumiu: a
    pasta pode estar num disco externo desconectado, e isso apagaria do
    histórico reuniões perfeitamente válidas.

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

## Decisões do proprietário

**Resolvidas:** `LICENSE` (Apache-2.0, com a auditoria de dependências em
`docs/LICENSES.md`) e *Private vulnerability reporting*, agora habilitado no
GitHub — `docs/SECURITY.md` já descreve o canal.

**Ainda pendente — `CODE_OF_CONDUCT.md`.** O Contributor Covenant exige um
canal **privado** para denúncias de conduta, e hoje não existe nenhum que
possa ser publicado sem uma decisão sua:

- o GitHub não tem mensagem direta entre usuários, então "falar com o
  mantenedor no GitHub" não é um canal real;
- o *private vulnerability reporting* é para segurança, não para conduta;
- publicar um e-mail pessoal num repositório público é uma escolha de
  privacidade que não cabe a mais ninguém fazer.

O caminho usual é criar um endereço dedicado (um alias qualquer serve) e
usá-lo só nesse arquivo. Enquanto isso não for decidido, é mais honesto não
ter o arquivo do que ter um com um contato que não funciona.

## Testado com hardware real vs. só com dublês

Ver a seção "Testado" de cada `docs/<FASE>.md` (`AUDIO` em `docs/API.md`,
`docs/LIVE_TRANSCRIPTION.md`, `docs/SCHEDULING.md`, `docs/DATABASE.md`) para a
distinção exata IMPLEMENTADO ≠ TESTADO COM FAKE ≠ TESTADO COM HARDWARE REAL em
cada fase — nunca conflate os três. Nesta retomada **nada foi testado com
hardware real**: o que mudou no encerramento e no reprocessamento está
coberto por dublês e por testes HTTP (item P1-2).

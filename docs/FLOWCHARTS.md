# Fluxogramas

Todos os diagramas abaixo refletem o **código real** implementado nesta
sessão (verificado por leitura direta de `cli.py`/`webui.py`/`recorder.py`/
`session.py`/`scheduling/engine.py`/`live/pipeline.py`/`storage/`, não uma
intenção futura). Onde uma etapa não existe ainda, ela é explicitamente
marcada como **Planejado**.

## 1 — Visão geral

```mermaid
flowchart TD
    U[Usuário] --> UI[index.html - painel ativo]
    UI -.Fase F, planejado.-> REACT[React]

    UI --> API[webui.py - API local]

    API --> SM[Session Manager]
    API --> SCHED[Scheduler]

    SCHED --> SM

    SM --> PIPE[Audio Pipeline]
    PIPE --> WHISPER[Transcrição]
    WHISPER --> SQLITE[(SQLite)]
    SQLITE --> INTEL[Meeting Intelligence]:::planned
    SQLITE --> EXPORT[Exportações]
    SQLITE --> SEARCH[Histórico e busca]

    classDef planned stroke-dasharray: 5 5
    class INTEL planned
```

`Meeting Intelligence` (resumo/tarefas/decisões, Fase G) está tracejado:
arquitetura planejada, sem implementação ainda.

## 2 — Gravação

```mermaid
flowchart TD
    START[POST /api/start] --> SPRE[Storage Preflight]
    SPRE --> APRE[Audio Preflight]
    APRE --> CREATE[Create MeetingSession]

    CREATE --> SYS[System Capture]
    CREATE --> MIC[Mic Capture]

    SYS --> REC[Recorder threads]
    MIC --> REC

    REC --> WAV[Durable WAV chunks<br/>30-120s]
    REC --> LIVEWIN[Live windows<br/>8s, on_block callback]

    WAV --> WHISPERDUR[Whisper - transcrição durável]
    LIVEWIN --> WHISPERLIVE[Whisper - prévia rápida]

    WHISPERDUR --> SEG[Segmentos definitivos]
    WHISPERLIVE --> PROV[Segmentos provisórios]

    SEG --> MD[transcript.md]
    SEG -->|substitui por intervalo de tempo| PROV
    PROV --> SSE1[SSE /api/transcription/stream]
    SEG --> SSE1

    REC --> LEVELS[Nível RMS] --> SSE2[SSE /api/audio/levels/stream]

    SSE1 --> UI2[index.html]
    SSE2 --> UI2
```

## 3 — Agendamento

```mermaid
flowchart TD
    CREATE[POST /api/schedules] --> VALID[Validação + checagem de conflito]
    VALID --> PERSIST[schedules.json - escrita atômica]
    PERSIST --> TICK[SchedulerEngine.tick_once]

    TICK --> CLAIM{Ocorrência atual?}
    CLAIM -->|não| NEXT[Calcula próxima ocorrência]
    NEXT --> TICK

    CLAIM -->|sim| WINDOW{now vs janela}
    WINDOW -->|T-5min| PREFLIGHT[Preflight: pasta + dispositivos]
    PREFLIGHT --> WINDOW

    WINDOW -->|dentro da tolerância| TRYSTART[Tentar iniciar]
    TRYSTART -->|ok| REC2[Recording]
    TRYSTART -->|falha| RETRY{Ainda dentro da tolerância?}
    RETRY -->|sim| TRYSTART
    RETRY -->|não, nunca tentou| MISSED[missed]
    RETRY -->|não, tentou e falhou| FAILED[failed]

    WINDOW -->|passou da tolerância, nunca iniciado| MISSED

    REC2 -->|now >= fim| STOP[request_stop - graceful]
    STOP --> FINISH[finishing]
    FINISH -->|processo terminou| DONE{ended_early?}
    DONE -->|não| COMPLETED[completed]
    DONE -->|sim, usuário parou antes| COMPLETED

    MISSED -->|start_now| TRYSTART
    MISSED -->|ignore_missed| NEXT
    FAILED -->|start_now| TRYSTART
```

## 4 — Encerramento gracioso

```mermaid
flowchart TD
    REQ[Parar solicitado<br/>botão manual OU scheduler no fim da janela] --> SIG[Sinal gracioso<br/>SIGINT / CTRL_BREAK_EVENT]
    SIG --> STOPEVT[stop_event.set]
    STOPEVT --> FINISHBLOCK[Termina o bloco de áudio atual]
    FINISHBLOCK --> PARTIALWAV[Escreve o chunk parcial]
    PARTIALWAV --> CLOSESTREAMS[Fecha streams de áudio]
    CLOSESTREAMS --> DRAIN[Drena a fila de transcrição pendente]
    DRAIN --> FINALIZEMD[Finaliza transcript.md]
    FINALIZEMD --> MARKSESSION[MeetingSession.mark_completed]
    MARKSESSION --> DONE2[completed / interrupted se sobrou pendência]

    SIG -.timeout 30s sem resposta.-> TERM[terminate - exceção]
    TERM -.timeout 5s sem resposta.-> KILL[kill - último recurso]

    style TERM stroke-dasharray: 5 5
    style KILL stroke-dasharray: 5 5
```

`terminate()`/`kill()` são o caminho de **exceção**, nunca o fluxo normal
— só acontecem se o processo não responder ao sinal gracioso dentro do
timeout (ver `webui.py:shutdown_sequence`).

## 5 — Recovery

```mermaid
flowchart TD
    BOOT[webui.py inicia] --> BIND{Bind da porta<br/>bem-sucedido?}
    BIND -->|não, já tem instância| OPEN[Abre navegador na instância existente]
    BIND -->|sim, somos a única instância| ROOTS[Carrega raízes conhecidas<br/>settings.get_known_meeting_roots]

    ROOTS --> SCAN[Varre cada raiz por sessões travadas]
    SCAN --> STATUS{status == recording/processing?}
    STATUS -->|não| SKIP[Ignora - sessão normal]
    STATUS -->|sim| PIDCHECK{PID gravado ainda vivo?<br/>is_pid_running}

    PIDCHECK -->|sim - camada de segurança, NÃO adoção| REFUSE[Recusa reprocessar<br/>evita 2 processos escrevendo junto]
    PIDCHECK -->|não ou indeterminado| INTERRUPTED[Marca como interrupted]

    INTERRUPTED --> USERUI[Painel mostra banner de recuperação]
    USERUI --> RESUME[POST /api/meetings/id/resume]
    RESUME --> PENDING[Reprocessa só os blocos pendentes]
    PENDING --> COMPLETE2[completed]

    ROOTS --> ENGINESTART[Scheduler engine.start - tick imediato]
```

## 6 — Dados (SQLite, Fase E)

```mermaid
erDiagram
    MEETINGS ||--o{ MEETING_SEGMENTS : contém
    MEETINGS {
        text id PK
        text title
        text status
        text started_at
        text finished_at
        real duration_seconds
        text meeting_directory
        text deleted_at
        text created_at
    }
    MEETING_SEGMENTS {
        int id PK
        text meeting_id FK
        int sequence
        real start_seconds
        real end_seconds
        text speaker_label
        text text
    }
```

`speaker_label` é preenchido na importação (Fase H leve): `"Você"`
(microfone), `"Áudio da reunião"` (sistema) ou `"Reunião"` (ambos) —
nunca um nome de pessoa. `search_index` (FTS5, quando disponível) não é
modelado aqui por ser uma tabela de apoio interna à busca, não uma
entidade de domínio.

Tabelas planejadas e **não implementadas**: `audio_chunks` e
`transcription_jobs` como entidades próprias (hoje cobertas por
`state.json` no filesystem), `SCHEDULE`/`SCHEDULE_RUN` em SQLite (hoje em
`schedules.json`, ver `docs/SCHEDULING.md`), `action_items`, `decisions`,
`topics`, `speakers`/`meeting_speakers` como tabelas de verdade (Fase G/H
completa).

## 7 — Inteligência (Fase G — planejado, não implementado)

```mermaid
flowchart TD
    TRANSCRIPT[Transcrição definitiva] -.-> CHUNKING[Chunking semântico/temporal]
    CHUNKING -.-> PROVIDER[Provider plugável<br/>local / Ollama / OpenAI / Anthropic / Gemini]
    PROVIDER -.-> VALIDATE[Validação de saída estruturada]
    VALIDATE -.-> SUMMARY[Resumo]
    VALIDATE -.-> ACTIONS[Tarefas]
    VALIDATE -.-> DECISIONS[Decisões]
    VALIDATE -.-> TOPICS[Tópicos]

    style CHUNKING stroke-dasharray: 5 5
    style PROVIDER stroke-dasharray: 5 5
    style VALIDATE stroke-dasharray: 5 5
    style SUMMARY stroke-dasharray: 5 5
    style ACTIONS stroke-dasharray: 5 5
    style DECISIONS stroke-dasharray: 5 5
    style TOPICS stroke-dasharray: 5 5
```

Todo este diagrama é planejado — nenhuma linha de código da Fase G existe
ainda. Mantido aqui só para mostrar onde ela se encaixaria na arquitetura
real já construída.

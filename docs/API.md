# API do painel (`webui.py`)

Contrato HTTP real, servido em `http://127.0.0.1:8765` (nunca `0.0.0.0`).
Existe hoje para o `index.html` atual, mas e documentado aqui pensando no
consumo futuro pelo frontend React (Fase F do roadmap) — nenhuma rota daqui
foi inventada so pra "parecer completa"; todas ja existem de verdade no
codigo (`webui.py`).

Convenções gerais:

- Toda mutação usa **POST**, nunca `PUT`/`PATCH` (inclusive
  `/api/audio/config`, que num design "REST puro" seria `PUT` — mantido
  como `POST` pra ficar consistente com o resto desta API já existente,
  ex. `/api/settings/meetings-root`).
- Corpo de requisição sempre JSON (objeto, nunca array/string na raiz) ou
  vazio. Corpo malformado → `400`. Corpo maior que 1 MB → `413`.
- Toda resposta é JSON. Nenhuma rota devolve HTML exceto `GET /`.
- `Host` precisa ser `127.0.0.1` ou `localhost` (defesa contra DNS
  rebinding) → do contrário, `400`.
- Nenhuma resposta contém stack trace/texto cru de exceção — erros de
  domínio usam o formato `{"error": {"code": "...", "message": "..."}}`
  (ver "Códigos de erro" no fim) ou, nas rotas mais antigas, um simples
  `{"ok": false, "message": "..."}` amigável.

## Sessão / gravação

### `GET /api/status`

Consultado a cada 1.5s pela página. Resposta:

```json
{
  "running": true,
  "output": "C:\\...\\transcript.md",
  "chunk_seconds": 300,
  "meeting_dir": "C:\\...\\2026-09-14_1900_Reuniao_ab12ef",
  "started_at": 1789427515.8,
  "finished_at": null,
  "exit_code": null,
  "log": ["...ultimas ate 300 linhas..."],
  "block_elapsed": 42.1,
  "block_index": 0,
  "output_path": "C:\\...\\transcript.md",
  "output_exists": true,
  "output_saved_at": 1789427520.1,
  "output_size": 1024
}
```

`block_elapsed`/`block_index`/`output_*` só aparecem quando há uma gravação
com `output` definido.

### `POST /api/start`

Body (todos os campos opcionais — cada um cai no valor validado/salvo por
padrão quando omitido):

```json
{
  "title": "Reunião Projeto ERP",
  "model": "small",
  "device": "cpu",
  "language": "pt",
  "chunk_seconds": 300,
  "keep_audio": true,
  "capture_system": true,
  "capture_microphone": false,
  "system_device_id": null,
  "microphone_device_id": null
}
```

- `model`: um de `tiny`/`base`/`small`/`medium`/`large-v3`.
- `device`: `cpu`/`cuda`.
- `language`: código de 2-5 letras ou `"auto"`.
- `chunk_seconds`: inteiro entre 5 e 1800.
- Sem campo `output`/nome de arquivo: o arquivo é sempre
  `transcript.md` dentro da pasta da própria reunião (ver
  `docs/ARCHITECTURE.md`) — superfície de path traversal eliminada por
  construção, não só validada.
- `capture_system`/`capture_microphone`: pelo menos um precisa ser `true`.
- `system_device_id`/`microphone_device_id`: id estável do dispositivo
  (ver `GET /api/audio/devices`), ou `null`/omitido para o padrão do
  sistema.
- `meetings_root`: opcional — raiz **desta gravação especifica**, se
  diferente da raiz global do painel (usado pelo agendamento, Fase C.1,
  cujo "Salvar em" pode ser uma pasta distinta por agendamento). Omitido:
  usa a raiz global de sempre. Quando informado, **não** persiste como
  preferência de áudio padrão (ver `docs/SCHEDULING.md`).

Antes de responder, o servidor roda a checklist de saúde de
armazenamento (pasta existe/é gravável/tem espaço) e de áudio
(`check_device_health` para cada fonte habilitada) — qualquer falha
devolve `{"ok": false, "message": "..."}` com `409`, sem subir nenhum
processo. Sucesso persiste a escolha de dispositivos como preferência
padrão (ver `POST /api/audio/config`).

Resposta: `{"ok": true, "message": "Gravacao iniciada."}` (`200`) ou
`{"ok": false, "message": "..."}` (`409`).

### `POST /api/stop`

Sem corpo. Inicia o encerramento gracioso (sinal → aguarda até 30s →
`terminate()` → aguarda até 5s → `kill()` só como último recurso; ver
`docs/ARCHITECTURE.md`). Resposta imediata, antes do processo
efetivamente terminar: `{"ok": true, "message": "Parando a gravacao
(encerramento gracioso, aguarde)."}` (`200`), ou `{"ok": false, "message":
"Nenhuma gravacao em andamento."}` (`409`) se nada estiver rodando.

## Armazenamento

### `GET /api/settings`

```json
{
  "meetings_root": "C:\\Users\\...\\Documents\\Reunioes",
  "folder_dialog_available": true,
  "free_bytes": 195596632064
}
```

`free_bytes` é `null` se a pasta ainda não existir.

### `POST /api/choose-folder`

Sem corpo. Abre o seletor nativo de pasta (`tkinter`). Resposta (sempre
`200` — cancelar não é erro):

```json
{
  "ok": true,
  "cancelled": false,
  "message": "Pasta de reunioes atualizada.",
  "meetings_root": "D:\\Reunioes",
  "folder_dialog_available": true,
  "free_bytes": 195596632064
}
```

`cancelled: true` quando o usuário fecha o diálogo sem escolher nada
(`ok` também `false` nesse caso, mas não é um erro de verdade — o
cliente não deve mostrar isso como falha).

### `POST /api/settings/meetings-root`

Fallback manual (quando `folder_dialog_available` é `false`). Body:
`{"path": "D:\\Reunioes"}`. Mesma resposta de `/api/choose-folder`
(exceto `cancelled`, que aqui é sempre `false`).

### `POST /api/open-folder`

Body: `{"path": "C:\\...\\<meeting_dir>"}`. Abre o Explorador de Arquivos
nessa pasta — só aceita caminhos dentro da raiz de reuniões configurada.
`{"ok": true, "message": "Pasta aberta."}` (`200`) ou `{"ok": false,
"message": "..."}` (`409`).

## Recuperação

### `GET /api/recovery`

Varre **todas** as raízes já conhecidas (não só a ativa — ver
`docs/RECOVERY.md`). `{"sessions": [ {...estado da sessao...} ]}`, só
sessões com `status == "interrupted"`. Cada item tem o formato de
`state.json` (`meeting_id`, `title`, `status`, `chunk_count`,
`chunks_transcribed`, `pid`, ...).

### `POST /api/meetings/<meeting_id>/resume`

Sem corpo. Localiza a sessão em qualquer raiz conhecida e reprocessa só
os blocos pendentes (sem gravar áudio novo). Recusa com `409` se: id
inválido, sessão não encontrada, já há algo rodando, ou o PID registrado
na sessão ainda parece estar ativo (ver `docs/RECOVERY.md` — camada de
segurança, não adoção de processo).

## Áudio (Fase C)

### `GET /api/audio/devices`

```json
{
  "inputs": [
    {"id": "{0.0.1...}", "name": "Microfone USB", "is_default": true}
  ],
  "outputs": [
    {"id": "{0.0.0...}", "name": "Fones de ouvido", "is_default": true, "loopback_supported": true}
  ]
}
```

Em falha do motor de áudio: `{"error": {"code": "AUDIO_BACKEND_UNAVAILABLE", "message": "..."}}`.

### `GET /api/audio/config`

```json
{
  "capture_system": true,
  "capture_microphone": false,
  "system_device_id": null,
  "microphone_device_id": null
}
```

### `POST /api/audio/config`

Body: qualquer subconjunto das mesmas chaves de `GET`. Atualiza só o que
for enviado (as demais são preservadas); `""`/`null` num `*_device_id`
limpa a preferência (volta a usar o padrão do sistema). Resposta: a
configuração completa resultante (mesmo formato do `GET`).

### `POST /api/audio/test`

Testa dispositivo(s) de verdade **sem criar nenhuma reunião** (abre,
mede ~1s, fecha). Body opcional, mesmas chaves de `/api/audio/config` —
campos omitidos usam a preferência salva. Recusa com `{"ok": false, ...}`
se houver uma gravação em andamento ou nenhuma fonte selecionada.

```json
{
  "ok": true,
  "results": {
    "system": {"ok": true, "device_id": "...", "device_name": "Fones de ouvido", "level": 0.42},
    "microphone": {"ok": false, "code": "AUDIO_DEVICE_NOT_FOUND", "message": "O microfone selecionado nao esta mais disponivel.", "device_id": "..."}
  }
}
```

Síncrono de propósito: um teste de ~1-2s por fonte não justifica um job
em background com endpoint de polling (`POST` + `GET .../:id`) — a
missão permite essa simplificação quando não há necessidade demonstrada.

### `GET /api/audio/levels`

Um snapshot único do nível mais recente de cada fonte da gravação ATIVA:

```json
{
  "system": {"level": 0.63, "active": true, "updated_at": 1789427515.8},
  "microphone": {"level": 0.02, "active": false, "updated_at": 1789427515.8}
}
```

`{}` se não há gravação rodando ou o arquivo ainda não foi escrito.

### `GET /api/audio/levels/stream` (Server-Sent Events)

Mesmo conteúdo de `GET /api/audio/levels`, enviado como eventos
`data: {...}\n\n` sempre que o snapshot muda, checado a cada ~150ms
(~6.7 Hz — dentro da faixa de 5-15 atualizações/s pedida). Conexão de
vida longa; termina quando o cliente desconecta.

**Por que SSE, não WebSocket nem polling HTTP comum:** o fluxo é
estritamente backend→frontend (o cliente nunca precisa mandar nada de
volta nesse canal), então SSE cobre o caso inteiro com `http.server`
puro da biblioteca padrão — sem dependência nova, sem handshake bidirecional
que não seria usado. Polling HTTP no ritmo de `/api/status` (1.5s) é
longe demais da frequência pedida pro medidor parecer responsivo.

## Agendamento (Fase C.1 — ver `docs/SCHEDULING.md`)

### `GET /api/schedules`

```json
{
  "schedules": [
    {
      "id": "sch_ab12cd34ef56",
      "title": "Aula de Calculo",
      "scheduled_date": "2026-09-15",
      "start_time": "19:00",
      "end_time": "20:40",
      "timezone": "America/Sao_Paulo",
      "meetings_root": "D:\\Reunioes\\Faculdade",
      "system_audio_enabled": true,
      "system_device_id": null,
      "microphone_enabled": true,
      "microphone_device_id": "...",
      "transcription_model": "small",
      "language": "pt",
      "device": "cpu",
      "chunk_seconds": 300,
      "recurrence": {"type": "weekly", "days": [0]},
      "status": "scheduled",
      "next_run_at": "2026-09-15T22:00:00+00:00",
      "seconds_until_next_run": 12345.6,
      "current_run": { "...ver ScheduleRun.to_dict()..." },
      "history": ["...ate 200 ocorrencias passadas..."]
    }
  ]
}
```

`seconds_until_next_run` é calculado pelo servidor (nunca confie no
relógio do navegador para a contagem regressiva).

### `POST /api/schedules`

Body: mesmos campos de `GET` (exceto os calculados). `title`,
`scheduled_date` (`AAAA-MM-DD`), `start_time`/`end_time` (`HH:MM`),
`timezone` (IANA; padrão: detectado do computador),
`meetings_root`, `system_audio_enabled`/`microphone_enabled` (pelo menos
um `true`), `recurrence` (`{"type": "once"|"daily"|"weekdays"|"weekly"|
"custom_days", "days": [0..6]}`, padrão `once`). Recusa com `409` e
`{"ok": false, "message": "..."}` se a validação falhar OU se houver
conflito de horário com outro agendamento aberto (mensagem nomeia o
agendamento conflitante). Sucesso: `{"ok": true, "schedule": {...}}`.

### `POST /api/schedules/<id>`

Edita (mesmo corpo de `POST /api/schedules`, substituindo os campos).
Recusa se houver uma gravação em andamento para este agendamento.
Recalcula a ocorrência atual do zero (limpa `current_run`).

### `POST /api/schedules/<id>/cancel`

Sem corpo. Cancela o agendamento inteiro (nunca so uma ocorrencia).
Recusa se uma gravação estiver em andamento (pare a gravação primeiro).

### `POST /api/schedules/<id>/start-now`

Sem corpo. Inicia a próxima ocorrência imediatamente — antes do horário
previsto (útil), ou depois dele ter virado `missed`/`failed` (resolve a
pendência). Recusa se a janela da ocorrência já tiver terminado, se já
houver outra gravação ativa, ou se o preflight falhar.

### `POST /api/schedules/<id>/ignore-missed`

Sem corpo. Descarta uma ocorrência `missed`/`failed` sem iniciar
gravação — libera a próxima ocorrência (agendamentos recorrentes) ou
encerra o agendamento (`once`).

## Códigos de erro (`AudioErrorCode`)

Usados no formato `{"error": {"code": "...", "message": "..."}}` (hoje
só em `GET /api/audio/devices`) e no campo `code` de cada entrada de
`POST /api/audio/test`'s `results`:

| Código | Significado |
|---|---|
| `AUDIO_DEVICE_NOT_FOUND` | O id de dispositivo informado não corresponde a nenhum dispositivo atual (removido/desconectado/nunca existiu). |
| `AUDIO_DEVICE_BUSY` | Reservado para quando o backend distinguir "ocupado" de "não encontrado" — `soundcard` hoje não faz essa distinção de forma confiável, então não é emitido ainda. |
| `AUDIO_STREAM_FAILED` | O dispositivo foi resolvido mas abrir/ler o stream falhou. |
| `AUDIO_BACKEND_UNAVAILABLE` | O motor de áudio (`soundcard`) não pôde ser carregado/consultado. |
| `AUDIO_NO_SOURCE_ENABLED` | Reservado (hoje essa validação devolve `{"ok": false, "message": "..."}` simples em vez do formato `{"error": ...}` — mencionado aqui porque o código já existe em `audio.models.AudioErrorCode` para uso futuro consistente). |

Mensagens são sempre em português, amigáveis, e nunca contêm o texto cru
de uma exceção do backend nativo (`soundcard`/PortAudio) — o detalhe
técnico vai só para o log do servidor (`logger.error`/`logger.exception`).

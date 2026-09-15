# Estratégia de testes

## Backend (Python)

```bash
pytest -q
```

600+ testes, organizados por módulo (`tests/test_<modulo>.py`). Convenção
do projeto: **testes com dublês primeiro, sempre** — cada subsistema com
dependência de hardware/tempo real (áudio, relógio, Whisper) recebe uma
abstração injetável (`backend=None` em `audio/devices.py`, `Clock` em
`scheduling/`, `transcribe_window` callable em `live/pipeline.py`) para
que a suite inteira rode sem hardware, sem esperar tempo real, e sem
baixar nenhum modelo.

### Hardware real

`tests/test_*_hardware.py` usam o backend de áudio de verdade desta
máquina — pulados automaticamente (`pytest.mark.skipif`) quando não há
dispositivo de áudio disponível no ambiente (ex.: CI). Nunca fazem parte
da suite "obrigatória" — são evidência de validação manual, não
cobertura que todo ambiente precisa rodar.

### Relógio injetável (Fase C.1/D)

`scheduling.clock.ManualClock` e fakes equivalentes eliminam qualquer
`time.sleep()` real nos testes de agendamento/transcrição ao vivo — uma
mudança de relógio, virada de DST, ou "computador voltando de suspensão"
é simulada avançando o relógio manualmente, nunca esperando de verdade.

### Concorrência

Testes dedicados de concorrência cobrem: múltiplos starts simultâneos,
teste de áudio durante gravação, mudança de configuração durante
gravação, parada no meio de uma tentativa de abertura de stream, uma
fonte de áudio falhando enquanto a outra continua, retry de escrita
atômica sob concorrência real no Windows (reproduzido e corrigido nesta
sessão).

## Frontend (`frontend/`)

```bash
cd frontend
npm ci
npm run build   # tsc --build (type-check) + vite build (bundle de produção)
npx oxlint      # lint
```

Sem testes automatizados de componente ainda (não há telas de produto
construídas — ver `docs/PENDENCIAS.md`). O contrato de tipos
(`src/types/api.ts`) é verificado por `tsc`; qualquer divergência com o
que `webui.py` realmente devolve quebra o build.

## O que NUNCA fazer nesta suite

- Fingir que um teste passou sem executá-lo.
- Chamar um resultado com dublê de "testado com hardware real".
- Adicionar um teste que precise de segundos reais de espera (`sleep`)
  quando uma abstração de tempo já existe para o módulo em questão.
- Rodar a suite completa a cada linha alterada durante desenvolvimento —
  use testes direcionados (`pytest tests/test_x.py -k caso`) e reserve a
  suite completa para o fim de cada fase/antes de commits estruturais.

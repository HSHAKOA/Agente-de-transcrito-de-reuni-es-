# meeting-transcriber

Agente em Python que grava o audio de saida do computador (o que esta
tocando pelas caixas/fone — ex.: o audio de uma reuniao no Zoom, Google
Meet, Teams etc. rodando no navegador ou app) e gera uma transcricao em
Markdown, com timestamps, usando o modelo Whisper rodando localmente
(`faster-whisper`).

Feito para lidar com gravacoes de **horas de duracao**: o audio e gravado em
blocos (padrao de 5 min) e cada bloco e transcrito assim que fica pronto, em
paralelo com a gravacao continuando — memoria limitada e, se o processo cair,
voce so perde o ultimo bloco parcial (o `.md` ja tem tudo que foi transcrito
ate ali).

## Limitacao importante

Este agente captura **apenas o audio de SAIDA do sistema** (o que voce
ouve). Ele **nao captura o seu microfone**. Na pratica isso significa:

- A fala dos outros participantes da reuniao (que chega pelo seu
  fone/caixa) **e transcrita normalmente**.
- A sua propria fala **so aparece na transcricao se o app de reuniao
  ecoar o seu microfone de volta no seu audio de saida** (a maioria nao
  faz isso).

Se voce quiser transcrever tambem a sua propria fala, e necessario somar a
captura do microfone junto com a captura de loopback (nao implementado
aqui) — ou usar a gravacao/transcricao nativa da propria plataforma de
reuniao para a sua parte.

## Requisitos por sistema operacional

- **Windows**: funciona nativamente (loopback via WASAPI). Nao precisa de
  driver extra.
- **Linux (PulseAudio ou PipeWire com pipewire-pulse)**: funciona
  nativamente, usando a fonte "monitor" do dispositivo de saida padrao.
  Em distros com PipeWire, garanta que o `pipewire-pulse` esta ativo.
- **macOS**: o CoreAudio nao tem loopback nativo. Instale um dispositivo de
  audio virtual, como o [BlackHole](https://github.com/ExistentialAudio/BlackHole)
  e selecione-o como saida de audio padrao (ou crie um "Multi-Output
  Device" no Audio MIDI Setup para continuar ouvindo pelas caixas
  normalmente enquanto grava).

## Instalacao

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# ou: pip install -e .
```

Na primeira execucao, o `faster-whisper` baixa o modelo escolhido
automaticamente (requer internet nessa primeira vez; depois fica em cache
local).

## Uso

```bash
python -m meeting_transcriber --output reuniao-2026-08-12.md --model small --language pt
```

Deixe rodando durante a reuniao. Para encerrar, pressione `Ctrl+C` — a
gravacao para, os blocos pendentes terminam de ser transcritos, e o `.md`
e finalizado automaticamente.

### Opcoes principais

| Opcao | Padrao | Descricao |
|---|---|---|
| `-o, --output` | `transcricao.md` | Caminho do arquivo Markdown de saida |
| `--title` | `Transcricao de reuniao` | Titulo no topo do markdown |
| `--model` | `small` | Tamanho do modelo Whisper: `tiny`, `base`, `small`, `medium`, `large-v3` (maior = mais preciso e mais lento) |
| `--device` | `cpu` | `cpu` ou `cuda` (se tiver GPU NVIDIA compativel) |
| `--language` | `pt` | Codigo do idioma (`pt`, `en`, ...) ou `auto` para deteccao automatica |
| `--chunk-seconds` | `300` | Duracao de cada bloco de gravacao/transcricao, em segundos |
| `--no-keep-audio` | desligado | Por padrao os `.wav` de cada bloco ficam salvos (rede de seguranca para reprocessar manualmente um bloco que falhou); esta opcao apaga cada bloco logo apos transcrever com sucesso |
| `--work-dir` | pasta temporaria | Onde salvar os blocos de audio |

Se a transcricao de algum bloco falhar (ex.: modelo travou, chunk corrompido),
a sessao **nao para**: o erro fica registrado no `.md` e o `.wav` daquele
bloco e preservado (mesmo com `--no-keep-audio`) para voce reprocessar
manualmente depois.

### Escolhendo o modelo

Para reunioes de horas em CPU, `small` costuma ser um bom equilibrio entre
velocidade e qualidade. Se a transcricao nao estiver acompanhando a
gravacao em tempo real, tente `base` ou `tiny`. Com GPU (`--device cuda`),
`medium` ou `large-v3` ficam viaveis.

## Formato do Markdown gerado

```markdown
# Transcricao de reuniao

- **Data/hora de inicio:** 2026-08-12 14:00:00
- **Modelo Whisper:** small
- **Idioma:** pt

## Transcricao

**[00:00:03]** Bom dia a todos, vamos comecar a reuniao...

**[00:00:11]** Sobre o topico anterior...

---

*Duracao total gravada: 01:32:47*
```

## Rodando os testes

Os testes cobrem a logica pura (formatacao do markdown, gravacao dos
blocos WAV a partir de audio sintetico) — nao exigem microfone nem placa de
som real:

```bash
pip install pytest
pytest
```

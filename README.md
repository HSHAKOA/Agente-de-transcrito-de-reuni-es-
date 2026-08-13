# meeting-transcriber

Agente em Python que grava o audio de saida do computador (o que esta
tocando pelas caixas/fone — ex.: o audio de uma reuniao no Zoom, Google
Meet, Teams, uma aula gravada, qualquer coisa que esteja tocando) e gera
uma transcricao em Markdown, com timestamps, usando o modelo Whisper
rodando localmente (`faster-whisper`).

## Pra que serve / por que existe

A ideia e simples: **deixar rodando durante uma reuniao ou aula e, no
final, ter um `.md` com tudo que foi dito, com hora de cada trecho**, sem
depender de um servico pago por minuto e sem o audio sair da sua maquina
(o Whisper roda 100% local, offline depois de baixado uma vez). Nasceu de
uma necessidade bem concreta: gravar aulas/reunioes longas (horas) sem
travar nem perder o que ja foi gravado se algo der errado no meio.

## Como funciona (visao geral)

```
                    thread de gravacao                thread principal
                    (nunca para/espera)                (consome a fila)
                            │                                  │
  loopback do SO ──► grava blocos de N segundos ──► fila ──► Whisper transcreve
  (o que sai no                  │                            cada bloco
   fone/caixa)                   ▼                                  │
                            salva chunk_NNNNN.wav                   ▼
                                                          anexa no .md na hora
                                                          (nao espera a reuniao
                                                           acabar pra escrever)
```

Tres ideias centrais no design:

1. **Grava em blocos, nao a reuniao inteira de uma vez.** Por padrao, a
   cada 300s (5 min) o audio acumulado vira um `.wav` e entra numa fila.
   Isso mantem o uso de memoria limitado (so ficam em RAM os segundos mais
   recentes) em vez de acumular horas de audio.
2. **Gravar e transcrever rodam em paralelo, em threads separadas.** A
   gravacao nunca fica esperando o Whisper terminar de processar o bloco
   anterior — se a transcricao demorar mais que o normal, os blocos so vao
   se acumulando na fila, sem furar a gravacao.
3. **O `.md` e escrito incrementalmente, bloco por bloco.** Cada trecho
   transcrito e anexado ao arquivo na hora, ao inves de tudo ser montado
   em memoria e salvo so no final. Assim, se o processo cair no meio
   (queda de energia, erro, `--no-keep-audio` etc.), voce so perde no
   maximo o ultimo bloco incompleto — tudo que ja foi transcrito antes
   continua salvo em disco.

Ver os comentarios em `src/meeting_transcriber/` (especialmente
`cli.py` e `recorder.py`) pra mais detalhes de cada etapa.

## Modo facil (painel com botao, sem terminal)

Se voce nao quer digitar comando nenhum: de dois cliques em `iniciar.bat`
(Windows). Na primeira vez ele cria o ambiente virtual e instala as
dependencias sozinho (demora um pouco so nessa primeira execucao); nas
proximas abre na hora. Ele sobe um painel local no navegador
(`http://127.0.0.1:8765`) com:

- Campos pra titulo, modelo, idioma, dispositivo (CPU/GPU) e tamanho do
  bloco (`chunk-seconds`);
- Botao **Iniciar gravacao** / **Parar**;
- Log da transcricao ao vivo;
- Barra de progresso do bloco de gravacao atual;
- Indicador de "salvo" com o caminho completo do `.md` e horario da
  ultima atualizacao (util pra confirmar que esta gravando de verdade
  sem precisar ficar abrindo o arquivo manualmente).

Esse painel roda 100% na sua maquina (`webui.py`, so biblioteca padrao do
Python, sem Flask/FastAPI) e apenas liga/desliga o mesmo
`python -m meeting_transcriber` de sempre como um processo em segundo
plano — nao muda nada do comportamento descrito no resto deste README.
Se voce ja tiver o painel aberto e clicar em `iniciar.bat` de novo, ele
detecta e so abre o navegador na instancia existente, em vez de subir
outra por cima.

**Importante sobre `chunk-seconds`:** e sempre **um `.md` so**, do inicio
ao fim da sessao — esse numero so controla de quanto em quanto tempo o
audio e fatiado internamente. Pra reunioes/aulas longas (1h+), o padrao
de `300` (5 min) e um bom equilibrio: poucas chamadas ao Whisper, frases
raramente cortadas ao meio. Pra testar rapido se esta tudo funcionando,
baixe pra `15` ou `30` so durante o teste.

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
  driver extra. O que o app grava e sempre o **dispositivo de saida
  padrao do Windows** (Configuracoes > Som > Saida) — se o app da
  reuniao/video estiver tocando num dispositivo diferente do padrao do
  sistema, o app nao vai captar nada.
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

(No Windows, `iniciar.bat` faz esses 3 passos sozinho — nao precisa
digitar nada disso se for usar o painel.)

Na primeira execucao, o `faster-whisper` baixa o modelo escolhido
automaticamente (requer internet nessa primeira vez; depois fica em cache
local e carrega offline, sem depender de internet de novo).

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

## Estrutura do projeto

```
src/meeting_transcriber/
  audio_capture.py    # acha e abre o dispositivo de saida padrao em modo loopback
  recorder.py          # thread de gravacao: fatia o audio em blocos e enfileira
  transcriber.py        # carrega o Whisper e transcreve cada bloco (.wav -> texto)
  markdown_writer.py    # escreve o .md incrementalmente (cabecalho, blocos, rodape)
  cli.py                 # ponto de entrada `python -m meeting_transcriber`,
                          # junta gravacao + transcricao + escrita num loop so
  __main__.py            # so chama cli.main()
webui.py                 # servidor local (stdlib) que liga/desliga o cli.py
                          # como subprocesso e serve o painel
index.html                # interface do painel (sem framework, so fetch())
iniciar.bat               # launcher de um clique: venv + deps + abre o painel
tests/                     # testes da logica pura (sem precisar de microfone real)
```

## Rodando os testes

Os testes cobrem a logica pura (formatacao do markdown, gravacao dos
blocos WAV a partir de audio sintetico) — nao exigem microfone nem placa de
som real:

```bash
pip install pytest
pytest
```

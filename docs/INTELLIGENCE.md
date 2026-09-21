# Meeting Intelligence (Fase G) — projeto

> **Status: não implementado.** Este documento é o desenho da próxima fase
> grande (V1.1), para ser revisado antes de qualquer código. Hoje o Detalhe
> da Reunião mostra as abas Resumo/Tarefas/Decisões como "não processado".

## Objetivo

```text
Transcrição (já existe, com timestamps)
      │
      ▼
Análise ── Resumo · Tópicos · Decisões · Tarefas (responsável, prazo)
        └─ Perguntas em aberto · Pendências
```

Sem inventar nada: se ninguém disse quem faz uma tarefa, `owner = null`; se
não foi dito um prazo, `due_date = null`. Todo item aponta para o trecho da
transcrição de onde veio.

## Princípios (não negociáveis)

1. **O núcleo funciona sem provider.** Gravar, transcrever, buscar e exportar
   nunca dependem de análise. Sem provider configurado, as abas continuam
   "não processado".
2. **Offline-first.** O provider padrão é local. Provider em nuvem é
   *opt-in explícito* e a interface avisa que o texto da reunião sai da
   máquina; a chave vem de variável de ambiente, nunca do `settings.json` nem
   de um log.
3. **Fora do caminho de gravação.** A análise é um *job* separado, iniciado
   depois que a reunião termina (ou sob demanda). Nunca compete por CPU com a
   captura de uma gravação em andamento.
4. **Nada de dado sem evidência.** Todo item precisa citar ≥ 1 segmento que
   exista naquela reunião; item sem citação válida é descartado, não exibido.
5. **Reprodutível e auditável.** Cada análise registra provider, modelo e
   versão do prompt; reanalisar cria uma nova análise, não sobrescreve.

## Interface do provider

Um único ponto de extensão, sem acoplar o core a nenhuma biblioteca:

```python
class MeetingIntelligenceProvider(Protocol):
    name: str                       # "none" | "ollama" | "openai" | "gemini" | "anthropic"
    requires_network: bool          # a UI usa isto para pedir consentimento

    def analyze(self, meeting: MeetingRef, segments: Sequence[SegmentRef]) -> RawAnalysis: ...
```

- `SegmentRef(id, start_seconds, end_seconds, speaker_label, text)` — o
  `id` é o `meeting_segments.id` do SQLite.
- `RawAnalysis` é o que o provider *diz*; **não é confiável** até passar pelo
  validador (abaixo). O core nunca grava a saída crua de um LLM.
- Implementações previstas, nesta ordem: `NoneProvider` (default, devolve
  "sem análise"), um `FakeProvider` determinístico (só para testes),
  `OllamaProvider` (LLM local via HTTP em `localhost`), e por último os de
  nuvem (OpenAI, Gemini, Anthropic), cada um atrás de consentimento.

### Validador (a barreira contra alucinação)

Roda sempre entre o provider e o banco:

- `owner`/`due_date` só sobrevivem se o texto citado contém a evidência
  (nome / expressão de data); caso contrário viram `null`.
- Cada item precisa de `segment_ids` que existam **nesta** reunião e cujos
  timestamps caibam em `[0, duração]`.
- Tipos e tamanhos checados (campos desconhecidos ignorados, texto truncado
  a um teto, no máximo N itens por categoria).
- Falha fecha: saída que não parseia, ou análise sem nenhum item válido,
  vira `status = failed` com a mensagem — nunca um resumo "otimista".

## Modelo de dados (migration 2, versionada em `storage/db.py`)

Cada resultado importante tem `meeting_id`, `segment_id` e o timestamp.

| Tabela | Colunas principais |
|---|---|
| `meeting_analysis` | `id`, `meeting_id` → `meetings`, `provider`, `model`, `prompt_version`, `status` (`pending/running/done/failed`), `summary`, `error`, `created_at` |
| `action_items` | `id`, `analysis_id`, `meeting_id`, `text`, `owner` **NULL**, `due_date` **NULL**, `status` (`open/done`), `segment_id`, `start_seconds` |
| `decisions` | `id`, `analysis_id`, `meeting_id`, `text`, `segment_id`, `start_seconds` |
| `topics` | `id`, `analysis_id`, `meeting_id`, `title`, `start_seconds`, `end_seconds` |
| `open_questions` | `id`, `analysis_id`, `meeting_id`, `text`, `segment_id`, `start_seconds` |

`ON DELETE CASCADE` a partir de `meetings`. Índices por `meeting_id`. A
migration é aditiva: reuniões antigas continuam válidas sem análise.

## API prevista

- `GET /api/intelligence/providers` — providers disponíveis e se exigem rede.
- `POST /api/meetings/<id>/analyze` — inicia o job (`409` se já houver um
  rodando ou uma gravação em andamento).
- `GET /api/meetings/<id>/analysis` — última análise + itens, ou "não
  processado".
- Marcar tarefa como concluída: `POST /api/action-items/<id>/done`.

Mesmas regras do resto da API: validação no servidor, `Origin` em todo `POST`,
nada de caminho vindo do cliente.

## Transcrições longas

Uma aula de duas horas tem dezenas de milhares de palavras. Estratégia:
janelas de segmentos (com sobreposição) → extração por janela → fusão com
deduplicação → resumo final a partir dos resumos por janela. Cada janela
mantém as referências aos segmentos; a fusão nunca perde a citação.

## Fatias (cada uma entregável e testável)

1. **G.1** — interface + `NoneProvider` + `FakeProvider` + validador +
   migration 2 + repositório + endpoints. Sem UI de verdade, sem LLM.
2. **G.2** — `OllamaProvider` (local) e a aba de análise do Detalhe.
3. **G.3** — exportar a análise (Markdown/JSON) junto da transcrição.
4. **G.4** — providers em nuvem, atrás de consentimento explícito.

## Como testar sem um LLM

O `FakeProvider` devolve saídas roteirizadas — incluindo as **inválidas**:
citação de segmento inexistente, dono inventado, prazo sem evidência, JSON
quebrado, item duplicado. O validador precisa derrubar cada uma. Testes de
"golden file" cobrem o resumo de uma transcrição pequena e fixa. Nenhum teste
da suite obrigatória chama um serviço externo.

## Ligação com a Fase H (speakers)

`meeting_segments.speaker_label` hoje é o mesmo rótulo para a reunião inteira.
A análise melhora muito com "quem disse" — e o dado para isso **já existe**:
a captura simultânea guarda `audio/microphone/` e `audio/system/` por bloco
(verificado numa reunião real: 11 blocos em cada canal), enquanto `keep_audio`
estiver ligado — o `--no-keep-audio` apaga cada bloco depois de transcrevê-lo.
Atribuir cada segmento ao canal dominante (energia RMS de cada canal na janela
do segmento) dá `Você` × `Reunião` por segmento sem regravar nem rodar uma
diarização por voz; para reuniões sem o áudio guardado o rótulo continua
sendo o da reunião. Ver `docs/PENDENCIAS.md`.

# DESIGN.md

Autoridade visual do Meeting Intelligence. Quem for mexer na interface —
pessoa ou agente — decide por aqui. `MOTION.md` cuida do movimento.

Este documento descreve o produto que existe. Onde ele descreve algo que
ainda não foi implementado, diz isso na própria linha.

---

## 1. O que este produto é

Um software que fica **aberto por uma hora e meia enquanto alguém assiste a
uma aula**. Não é um site, não é um dashboard de vendas, não é um app que se
usa em rajadas de trinta segundos.

Isso decide quase tudo:

- A tela em repouso vai ser olhada de relance, no canto do monitor, por
  muito tempo. Ela precisa ser **calma o bastante para ser ignorada** e
  informativa o bastante para uma conferida de dois segundos responder "está
  tudo certo?".
- Os dados são **privados** (aulas, reuniões, às vezes assuntos sensíveis).
  A interface tem que *parecer* privada: nada de brilho de marketing, nada
  que sugira que algo foi para a nuvem.
- Quem usa está fazendo outra coisa ao mesmo tempo. A interface nunca
  disputa atenção, exceto quando algo realmente deu errado.

### Personalidade

```
calmo · preciso · técnico · privado · profissional
```

Referências de atitude (nunca de cópia): a densidade sem ruído do Raycast, a
sobriedade tipográfica do Superhuman, a honestidade de estado do Ollama, o
respeito por hierarquia e foco das Apple HIG.

### O que este produto não é

Proibido, sem exceção:

```
gradientes arco-íris · roxo "de IA" · glassmorphism em tudo
neon · cyberpunk · bordas brilhantes · partículas · decoração 3D
hero gigante · seção de marketing · card dentro de card dentro de card
```

Se um elemento existe para impressionar e não para informar, ele está errado
neste produto.

---

## 2. Estado atual (antes de qualquer mudança)

Registrado para ninguém confundir o que é decisão com o que é herança:

- `frontend/src/index.css` tem **uma linha**: `@import "tailwindcss"`.
  Nenhum token, nenhum tema.
- Todo estilo é utilitário Tailwind inline, com valores escolhidos tela a
  tela (`neutral-950`, `neutral-500`, `red-400`, `amber-200`…).
- **Só existe modo escuro.** `App.tsx` fixa `bg-neutral-950 text-neutral-100`.
- Ícones: `lucide-react` (já instalado).
- 8 telas + banner de recuperação, 2113 linhas de TSX.

Consequência prática: hoje não dá para trocar uma cor em um lugar só. É isso
que a seção 4 resolve.

---

## 3. Tipografia

Stack, nesta ordem:

```css
Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
"Segoe UI", sans-serif
```

**Não empacotar SF Pro.** É fonte da Apple, licenciada para uso em
plataformas Apple; distribuir como webfont num app Windows é problema legal,
não escolha estética.

Inter é opcional e progressiva: se não carregar, `system-ui` no Windows já é
Segoe UI, que é boa. Nunca bloquear a renderização esperando fonte.

### Números

Todo número que muda no tempo — cronômetro, nível, duração, contagem de
blocos — usa `font-mono` **e** `tabular-nums`. Sem isso o cronômetro
"dança" a cada segundo, e uma tela que fica aberta 90 minutos treme no canto
da visão periférica. Já está certo em `Recording.tsx`; manter.

### Escala

| Uso | Classe | Peso |
|---|---|---|
| Título de tela | `text-lg` | `font-medium` |
| Corpo | `text-sm` | normal |
| Rótulo de seção | `text-xs uppercase tracking-wide` | `font-medium` |
| Metadado / secundário | `text-xs` | normal |

Deliberadamente curta. Um app denso com sete tamanhos de fonte vira sopa.
Hierarquia aqui se faz com **cor e espaço**, não com tamanho.

---

## 4. Cor

### Regra

Nenhum valor de cor literal em componente. Tudo sai de token. Tailwind v4
declara token com `@theme` no `index.css`, e isso gera as utilidades
automaticamente.

```css
@import "tailwindcss";

@theme {
  /* superfícies, do fundo para a frente */
  --color-surface:        oklch(0.15 0.005 260);
  --color-surface-raised: oklch(0.19 0.005 260);
  --color-surface-sunken: oklch(0.12 0.005 260);
  --color-border:         oklch(0.27 0.006 260);
  --color-border-strong:  oklch(0.38 0.008 260);

  /* texto, do mais forte para o mais fraco */
  --color-ink:        oklch(0.95 0.005 260);
  --color-ink-muted:  oklch(0.72 0.006 260);
  --color-ink-subtle: oklch(0.55 0.006 260);

  /* estados — nunca decorativos, cada um significa uma coisa */
  --color-live:    oklch(0.63 0.20 25);    /* gravando */
  --color-warn:    oklch(0.78 0.14 75);    /* atenção, atraso */
  --color-danger:  oklch(0.60 0.20 25);    /* erro, destrutivo */
  --color-ok:      oklch(0.70 0.13 155);   /* concluído */
  --color-accent:  oklch(0.70 0.10 240);   /* foco, ação primária */
}
```

`oklch` é proposital: interpolação perceptualmente uniforme, então derivar um
hover (mesma matiz, luminosidade ±0.04) não muda a cor percebida.

### Significado fixo

| Token | Significa | Onde aparece |
|---|---|---|
| `live` | **está acontecendo agora** | ponto de gravação, medidor ativo |
| `warn` | está atrasado, mas nada se perdeu | backlog `BEHIND`, sessão interrompida |
| `danger` | falhou, ou vai destruir algo | erro, "Parar" |
| `ok` | terminou bem | reunião concluída |
| `accent` | foco e ação primária | anel de foco, botão principal |

Uma cor de estado **nunca** é usada por gosto. Se `warn` aparece onde nada
está atrasado, a cor perde o significado e o aviso real deixa de ser lido.

### Vermelho para "Parar"

Hoje o botão de parar é vermelho. Vermelho comunica destruição — e parar uma
gravação **não destrói nada**: o áudio já está em disco, a transcrição
continua até o fim. Vermelho ali ensina a hesitar na única ação que a pessoa
precisa fazer no fim de toda aula.

**Decisão:** "Parar" é um botão neutro com borda, não vermelho. O vermelho
fica reservado para o indicador de **gravação em andamento** (onde significa
"ao vivo", não "perigo") e para erro de verdade. *(Ainda não aplicado.)*

### Modo claro

O produto é escuro-primeiro e continua assim: é usado à noite, em aula, por
horas. Mas escuro-**só** é uma falha de acessibilidade para quem tem
astigmatismo, e é ruim em sala clara.

Regra: todo token acima ganha um par claro, trocado por `data-theme` no
`<html>` com `prefers-color-scheme` como padrão. Nenhum componente pode saber
qual tema está ativo. *(Ainda não implementado — quando for, nenhuma cor
literal pode ter sobrado nos componentes, senão o tema claro nasce quebrado.)*

---

## 5. Espaço, raio e sombra

Espaçamento: só a escala do Tailwind (múltiplos de `0.25rem`). Nada de
`p-[13px]`.

Ritmo vertical do produto, que já está consistente e deve continuar:

```
seção → seção           mt-6
bloco → bloco           mt-4
rótulo → conteúdo       mb-2
linha → linha           gap-3
```

Raio: `rounded-lg` (0.5rem) em card, botão e campo. `rounded-full` só em
ponto de status e pill. **Um raio para tudo** — dois raios diferentes lado a
lado parecem erro.

Sombra: **nenhuma**. Em interface escura, sombra não separa nada; quem separa
é a borda (`--color-border`) e a diferença de superfície. Sombra aqui só
adiciona sujeira. A única exceção legítima seria um popover flutuante de
verdade, que hoje não existe.

---

## 6. Densidade

Este produto mostra, ao mesmo tempo, durante uma gravação: dois medidores de
nível, transcrição rolando, três contadores de backlog, cronômetro e estado.

**Isso não é ruído — é o conteúdo.** Qualquer "limpeza" que esconda backlog
ou nível atrás de um clique está removendo justamente a informação que
responde "está funcionando?".

Regra: pode-se reduzir peso visual (cor mais fraca, rótulo menor, menos
borda). Não se pode reduzir **quantidade de informação** de estado.

O que *pode* sumir: card em volta de coisa que não precisa de container,
borda que repete a separação que o espaço já faz, rótulo que repete o que o
ícone já diz.

---

## 7. Componentes

Inventário atual: `Card`, `LevelBar`, `MeetingRow` (+ `StatusPill`),
`AudioSourcePicker`, `RecoveryBanner`.

Antes de criar componente novo, na ordem (isto não é sugestão):

1. Precisa existir? Muita tela melhora deletando, não somando.
2. CSS/Tailwind puro resolve?
3. Um componente existente resolve?
4. Só então: componente novo.

Não criar abstração para um caso de uso. Duas duplicações são mais baratas
que a abstração errada.

### Estados obrigatórios

Todo componente que busca ou mostra dado precisa ter resposta para:

```
idle · carregando · vazio · sucesso · erro
```

E, nas telas de gravação, também:

```
iniciando · gravando · parando · processando · interrompido · concluído
```

**Estado vazio nunca é uma tela em branco.** Diz o que vai aparecer ali e
como fazer aparecer.

**Estado de erro nunca é só "Erro".** Diz o que falhou, e o que dá para
fazer. O backend já manda mensagem pronta e código estável
(`AudioErrorCode`) — use a mensagem, nunca faça parsing do texto.

---

## 8. Foco e teclado

Todo elemento interativo mostra foco visível com `--color-accent`, com anel
**por fora** da borda (`ring-2 ring-offset-2`), nunca trocando a borda — do
contrário o elemento "pula" ao receber foco.

Nunca `outline: none` sem substituto. Nunca `tabindex` positivo.

Alvo de toque: mínimo 44×44 px de área clicável, mesmo quando o desenho
parece menor.

### Limitação conhecida

A navegação é `useState` em `App.tsx`, sem `react-router`. Consequências
reais, que devem ser ditas e não escondidas:

- o **botão voltar do navegador não funciona** dentro do app;
- não existe URL para uma reunião específica;
- um F5 volta para a Dashboard.

Foi uma decisão consciente (poucas telas, sem dependência extra). Continua
válida — mas quem reclamar disso tem razão, e a resposta é adotar um router,
não maquiar.

---

## 9. Acessibilidade

Nível-alvo: WCAG 2.1 AA.

- Contraste ≥ 4.5:1 para texto normal, ≥ 3:1 para texto grande e para
  elementos de interface. Os tokens `ink-subtle` sobre `surface` são o caso
  mais apertado — medir antes de escurecer mais.
- HTML semântico primeiro: `<button>` para ação, `<a>` para navegação,
  `<h1>`/`<h2>` em ordem, `<dl>` para par rótulo/valor (já usado no backlog).
- Toda região que muda sozinha precisa de `aria-live`:
  - transcrição ao vivo → `aria-live="polite"`;
  - banner "Finalizando…" → `role="status"`;
  - erro → `role="alert"`.
- Medidor de nível é **decorativo para leitor de tela** (`aria-hidden`), com
  o estado real dito em texto ao lado — um número oscilando 10x por segundo
  em `aria-live` torna a tela inutilizável com leitor.
- Cor nunca é o único portador de significado: todo estado tem rótulo em
  texto além da cor.

Estado real hoje: só `History` e `RecoveryBanner` têm `aria-*`/`role`
sistemáticos. Dashboard, Nova Reunião, Gravação, Agendamentos e Configurações
**não foram auditados** (`docs/PENDENCIAS.md`, P2-11).

---

## 10. Ícones

`lucide-react`, que já é dependência. **Não adicionar outra biblioteca de
ícones.**

- Tamanho: `size-4` no corpo, `size-3.5` dentro de botão.
- Ícone sozinho como botão exige `aria-label`.
- Ícone decorativo ao lado de texto leva `aria-hidden`.
- **Emoji nunca é ícone funcional** — renderiza diferente por plataforma e é
  lido em voz alta de forma imprevisível.

---

## 11. Responsividade

Alvo primário é desktop (o app roda em `127.0.0.1` na máquina que grava).
Mas a mesma tela é aberta no celular na mesma rede com frequência, e quebrar
aí é gratuito.

- Largura de conteúdo: `max-w-2xl` (telas de foco) / `max-w-4xl` (listas).
- Abaixo de 640px: coluna única, sem rolagem horizontal, respiro lateral de
  16px.
- A grade de 3 colunas do backlog é o ponto que mais aperta — ela vira 3
  linhas no celular, não 3 colunas espremidas.

---

## 12. Como decidir quando este documento não responde

Nesta ordem:

1. Isso comunica **estado** ou só decora? Se decora, corta.
2. Alguém que olha por 2 segundos entende se está tudo bem?
3. Funciona com teclado? E com leitor de tela?
4. Funciona a 360px de largura?
5. Sobrou algum valor literal que deveria ser token?

Se a resposta a qualquer uma for desconfortável, o desenho ainda não está
pronto.

---

## 13. O que não é decisão visual

Não sacrificar, por estética, em nenhuma hipótese:

```
segurança · recuperação de sessão · tratamento de perda de dados
concorrência · segurança de filesystem · acessibilidade
```

Em particular: o encerramento de uma gravação pode levar minutos
legitimamente (a fila de blocos ainda é transcrita, e em CPU saturada isso
demora). A interface **mostra isso acontecendo** — nunca esconde atrás de
uma animação de sucesso, nunca navega para fora como se tivesse terminado.
Esconder o encerramento real já foi um bug de verdade aqui
(`docs/PENDENCIAS.md`, histórico P1-5).

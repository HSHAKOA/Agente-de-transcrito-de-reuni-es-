# MOTION.md

Regras de movimento do Meeting Intelligence. Complementa `DESIGN.md`, que
manda no resto.

---

## 1. Princípio único

**Animação que não comunica nada é remoção pendente.**

Movimento aqui existe para dizer exatamente quatro coisas:

```
mudou algo   ·   o que veio de onde   ·   isto causou aquilo   ·   recebi seu clique
```

Qualquer outro motivo — "ficou bonito", "parece moderno", "preenche o
silêncio" — reprova.

Este é um app que fica aberto 90 minutos ao lado de uma aula. Movimento
supérfluo aqui não é neutro: é uma distração repetida centenas de vezes, na
visão periférica de alguém que está tentando prestar atenção em outra coisa.

## 2. Personalidade

```
calmo · rápido · preciso · com propósito · confiante
```

Nada de bounce, overshoot, elástico ou mola. Isso é vocabulário de app de
consumo e conflita direto com "técnico, privado, profissional". A interface
se move como um instrumento, não como um brinquedo.

---

## 3. Tempos

Base, a ajustar com evidência e não por gosto:

| Situação | Duração | Easing |
|---|---|---|
| Pressionar (feedback tátil) | 80–120 ms | `ease-out` |
| Hover | 120–180 ms | `ease-out` |
| Elemento pequeno (pill, ícone, toggle) | 160–220 ms | `ease-out` |
| Painel, banner, expandir seção | 180–260 ms | `ease-in-out` |
| Troca de tela | 220–320 ms | `ease-in-out` |
| Feedback de resultado (salvo, erro) | 250–500 ms | `ease-out` |

Curvas concretas:

```css
--ease-out:    cubic-bezier(0.22, 1, 0.36, 1);   /* entrada, expansão */
--ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);   /* troca, movimento entre estados */
--ease-in:     cubic-bezier(0.55, 0, 1, 0.45);   /* saída */
```

### Por que assimétrico

**Entrar é mais lento que sair.** Entrada precisa ser percebida; saída só
precisa liberar o espaço. Sair devagar parece travamento.

Regra prática: saída ≈ 70% da duração da entrada.

### Stagger

Só em lista que aparece de uma vez (resultados do Histórico, por exemplo):
**30–40 ms** entre itens, no **máximo 6 itens**. A partir do sétimo, todos
entram juntos.

Uma lista de 50 resultados com stagger leva dois segundos para ficar legível.
Isso é mais lento que não animar nada.

---

## 4. `prefers-reduced-motion` — sem exceção

Não é item de acessibilidade opcional. Para parte das pessoas, movimento na
tela causa náusea e tontura de verdade.

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

**Reduzido não significa "sem feedback".** Onde o movimento carregava a
informação, ela passa a ser dita de outro jeito:

| Normal | Reduzido |
|---|---|
| Ponto de gravação pulsando | Ponto sólido + texto "GRAVANDO" |
| Barra de nível animada | Barra que atualiza sem transição |
| Banner deslizando | Banner aparece sem deslocamento |
| Spinner girando | Texto "Carregando…" |

No JavaScript, quando houver animação imperativa:

```ts
const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
```

**Estado hoje:** o ponto de gravação usa `animate-pulse` do Tailwind, que
**não** respeita `prefers-reduced-motion` sozinho. O bloco acima corrige
isso globalmente e é a primeira coisa a aplicar.

---

## 5. O que animar, por ordem de valor

Prioridade real, olhando o que o produto faz:

1. **Início de gravação** — a transição mais importante do app. O estado
   muda de "parado" para "ao vivo" e precisa ser inequívoco.
2. **Encerramento** — pode levar **minutos** (fila de blocos ainda sendo
   transcrita). O movimento tem que comunicar "trabalhando", nunca
   "terminado". Jamais um check de sucesso enquanto ainda processa.
3. **Sessão interrompida detectada** — o banner de recuperação precisa ser
   notado sem assustar.
4. **Resultado do Histórico chegando** — inclusive quando a resposta é
   "nenhum resultado".
5. **Erro** — aparece rápido, fica parado, não pisca.

Deliberadamente **não** animados:

- **Medidor de nível**: já se move 10x por segundo por natureza. Adicionar
  transição CSS faz ele atrasar em relação ao áudio real, e um medidor
  atrasado é um medidor mentiroso. Atualização direta, sem `transition`.
- **Cronômetro**: número muda, o elemento não se mexe (`tabular-nums` já
  garante que não empurra layout).
- **Transcrição ao vivo**: texto novo aparece; não desliza, não some, não
  faz fade. Alguém está **lendo** aquilo enquanto chega.

---

## 6. Gravando: vivo sem ser barulhento

O único elemento com movimento contínuo no app inteiro é o indicador de
gravação.

```
pulso do ponto: opacidade 1 → 0.45 → 1
período: 2s
easing: ease-in-out
```

Dois segundos, não um: respiração calma, não alarme. Só **opacidade** —
nunca escala, nunca cor, nunca sombra. Escalar faz o ponto "bater" e chama
atenção repetidamente.

Nada mais no app pode ter animação em laço. Um segundo elemento pulsando
cria competição visual e o olho não sabe mais onde pousar.

---

## 7. Restrições técnicas

Anime **só** `transform` e `opacity`. São as duas propriedades que o
navegador compõe fora do layout.

Nunca anime `width`, `height`, `top`, `left`, `margin`, `padding` — cada
quadro disso força recálculo de layout, e o app está dividindo a CPU com o
Whisper. Numa máquina já a 100% de uso durante a transcrição, animação mal
feita não fica só feia: ela tira ciclo de quem está transcrevendo áudio.

### Quando usar GSAP

Este projeto **não tem GSAP instalado**, e a maioria do que ele precisa é
transição CSS.

Instalar só se aparecer uma necessidade concreta que CSS não cobre:
sequência coreografada com dependência entre passos, ou interrupção no meio
com reversão suave. Antes de instalar, responda: CSS resolve? Já existe algo
no projeto? Se sim, não instale.

Se um dia for usado: `useGSAP` com escopo por ref, timeline por componente,
limpeza no unmount. **Nunca** uma timeline por quadro do medidor de áudio —
seria criar e destruir objetos dezenas de vezes por segundo.

---

## 8. Checklist antes de aceitar uma animação

1. Que informação isso transmite? (Se a resposta demorar, remova.)
2. Funciona com `prefers-reduced-motion: reduce`?
3. É só `transform`/`opacity`?
4. Segura 60fps com o Whisper rodando junto?
5. Tem laço infinito? Se sim, é *o* indicador de gravação? Se não, remova.
6. Atrasa alguma leitura? (Medidor, cronômetro, transcrição: nunca.)
7. Some sozinha quando o componente desmonta?

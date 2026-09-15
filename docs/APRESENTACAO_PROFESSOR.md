# Apresentação — Meeting Intelligence

## 1. Problema

Reuniões e aulas geram informação valiosa que se perde: ninguém consegue
anotar tudo em tempo real, gravações avulsas ficam desorganizadas, e
serviços de transcrição em nuvem cobram por minuto e exigem enviar áudio
(muitas vezes sensível) para servidores de terceiros.

## 2. Solução

Um software local que:

- **captura** o áudio do computador e o microfone simultaneamente;
- **transcreve** localmente com Whisper (`faster-whisper`), sem enviar
  nada para a internet;
- **organiza** cada reunião numa pasta própria, com recuperação
  automática se o processo cair no meio;
- **recupera** sessões interrompidas sem perder o que já foi gravado;
- **agenda** gravações recorrentes (ex.: aula toda segunda às 19h);
- **pesquisa** um histórico de tudo que já foi gravado;
- **resume** — *não implementado ainda* (Fase G, ver seção 6);
- **exporta** em Markdown, TXT, JSON, SRT e VTT.

## 3. Diferenciais

- Sem bot entrando em nenhuma chamada de vídeo.
- Processamento 100% local — sem custo por minuto, sem enviar áudio a
  terceiros.
- Captura sistema **e** microfone ao mesmo tempo, em canais separados.
- Recuperação automática de sessão interrompida (queda de energia,
  crash) sem perder áudio já gravado.
- Agendamento com tratamento explícito de "esqueci de abrir o app"
  (nunca começa silenciosamente atrasado).
- Histórico pesquisável, tudo local.

## 4. Arquitetura

Ver `docs/FLOWCHARTS.md` (9 diagramas: visão geral, gravação,
agendamento, encerramento gracioso [com o estado "stopping"], recovery,
schema de dados, servir o React, inteligência planejada) e `README.md`
para o resumo visual.

## 5. Antes de começar (uma vez só, se ainda não tiver feito)

`frontend/dist/` (o build do React) não é versionado no Git
(`.gitignore` — artefato de build). Se o build do React ainda não existe
neste checkout, `iniciar.bat` funciona normalmente mas mostra o painel
legado (`index.html`) em vez do React. Para garantir a interface nova na
demonstração:

```bash
cd frontend
npm install
npm run build
```

Depois disso, `iniciar.bat` sempre abre o React automaticamente — não
precisa repetir esse passo a menos que o código do frontend mude.

## 6. Roteiro de demonstração sugerido

```
1. Abrir iniciar.bat -- o React abre automaticamente no navegador
2. Mostrar o Dashboard (status de conexão, histórico, pasta ativa)
3. Clicar em "+ Nova reunião"
4. Escolher a pasta onde a reunião será salva
5. Mostrar os dispositivos de áudio disponíveis (sistema + microfone)
6. Testar áudio (botão "Testar áudio" — mede e mostra o nível de cada fonte)
7. Iniciar a gravação
8. Mostrar a tela de Gravação: medidores de nível ao vivo, cronômetro
9. Mostrar a transcrição aparecendo quase em tempo real
10. Parar a reunião -- mostrar o estado "Finalizando reunião..." (o
    encerramento gracioso real leva alguns segundos; a tela NUNCA finge
    que já parou antes de o backend confirmar)
11. De volta ao Dashboard: a reunião já aparece sozinha no histórico
    (indexação automática, sem precisar de nenhum botão de sincronizar)
12. Abrir a reunião: transcrição completa com timecodes, exportar
    (ex.: .srt) -- mostrar também as abas Resumo/Tarefas/Decisões
    marcadas honestamente como "não processado"
13. Mostrar a tela de Agendamentos e criar um novo (recorrência,
    contagem regressiva)
14. (Opcional) Mostrar `docs/FLOWCHARTS.md` pra explicar a arquitetura
```

Cada passo acima usa uma funcionalidade **realmente implementada e
testada** — nenhum passo do roteiro depende de algo simulado. O ciclo
completo (passos 3 a 12) foi verificado por um smoke test automatizado
de ponta a ponta (servidor real, HTTP real, subprocesso de gravação
simulado — nunca hardware de áudio real nesse teste específico) antes
desta sessão ser encerrada; a captura de áudio e a transcrição em si
(passos 5-9) usam o mesmo caminho já validado com hardware real em
sessões anteriores (ver `docs/API.md`/`docs/LIVE_TRANSCRIPTION.md`).

## 7. O que NÃO mostrar como pronto

- **Resumo/tarefas/decisões automáticos** (Fase G): não implementado.
  Se perguntado, a resposta correta é "arquitetura planejada, não
  implementada ainda" — nunca simular esse resultado. A própria tela de
  Detalhe da Reunião já mostra isso honestamente ("não processado").
- **Identificação de pessoas por nome** ("João disse...", "Maria
  perguntou..."): não implementado. O sistema hoje só distingue **canal**
  (`Você` vs `Áudio da reunião`), nunca voz individual.
- **Histórico completo com paginação**: hoje o Dashboard só mostra busca
  + últimas 5 reuniões. Uma tela dedicada de Histórico com paginação de
  verdade ainda não existe.
- **Início do agendamento com o app fechado**: hoje o painel precisa
  estar aberto no horário programado (documentado em
  `docs/SCHEDULING.md`).

## Dados de demonstração

Se for necessário gravar uma reunião de teste para a apresentação,
nomeie o título claramente como demonstração (ex.: `"DEMO — Aula de
Teste"`) para nunca confundir com uma reunião real do usuário. Não
misturar dados fictícios com reuniões reais sem essa identificação.

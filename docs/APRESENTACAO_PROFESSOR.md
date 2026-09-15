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

Ver `docs/FLOWCHARTS.md` (7 diagramas: visão geral, gravação,
agendamento, encerramento gracioso, recovery, schema de dados,
inteligência planejada) e `README.md` para o resumo visual.

## 5. Roteiro de demonstração sugerido

```
1. Abrir o painel (iniciar.bat)
2. Mostrar o dashboard/status
3. Mostrar os dispositivos de áudio disponíveis (sistema + microfone)
4. Testar áudio (botão "Testar áudio" — mede e mostra o nível de cada fonte)
5. Escolher a pasta onde a reunião será salva
6. Iniciar uma reunião de verdade (sistema + microfone)
7. Mostrar o áudio sendo capturado (medidor de nível ao vivo)
8. Mostrar a transcrição aparecendo quase em tempo real
9. Parar a reunião (mostrar o encerramento gracioso, sem perder nada)
10. Abrir o histórico e localizar a reunião recém-gravada
11. Abrir o resultado (transcrição completa) e exportar (ex.: .srt)
12. (Se estável) Mostrar um agendamento criado e sua contagem regressiva
```

Cada passo acima usa uma funcionalidade **realmente implementada e
testada** — nenhum passo do roteiro depende de algo simulado.

## 6. O que NÃO mostrar como pronto

- **Resumo/tarefas/decisões automáticos** (Fase G): não implementado.
  Se perguntado, a resposta correta é "arquitetura planejada, não
  implementada ainda" — nunca simular esse resultado.
- **Identificação de pessoas por nome** ("João disse...", "Maria
  perguntou..."): não implementado. O sistema hoje só distingue **canal**
  (`Você` vs `Áudio da reunião`), nunca voz individual.
- **Interface React**: existe um toolchain funcionando e um cliente HTTP
  tipado, mas nenhuma tela de produto. A interface real e ativa é
  `index.html`.
- **Início do agendamento com o app fechado**: hoje o painel precisa
  estar aberto no horário programado (documentado em
  `docs/SCHEDULING.md`).

## Dados de demonstração

Se for necessário gravar uma reunião de teste para a apresentação,
nomeie o título claramente como demonstração (ex.: `"DEMO — Aula de
Teste"`) para nunca confundir com uma reunião real do usuário. Não
misturar dados fictícios com reuniões reais sem essa identificação.

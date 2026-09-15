# Frontend React

Este **é** o frontend ativo do produto. Desde a missão de correção
pós-auditoria, `webui.py` serve o build de produção daqui
(`frontend/dist/`) como interface padrão em `http://127.0.0.1:8765` — é o
que `iniciar.bat` abre. O painel legado (`index.html` na raiz do
projeto) continua existindo só como fallback automático para quem, por
qualquer motivo, roda o backend sem ter gerado o build (`npm run build`
nunca executado) — nunca precisa ser removido nem mantido manualmente em
paridade a partir de agora.

## Stack

Vite 8 + React 19 + TypeScript 6 + Tailwind CSS v4 (sem Next.js),
`lucide-react` para ícones, `oxlint` para lint (mais rápido que ESLint
pro tamanho atual do projeto), `vitest` + `@testing-library/react` para
testes de componente.

## Estrutura

```
src/
  app/App.tsx          navegação entre telas (useState + discriminated
                        union, sem react-router) e useBackendStatus()
                        centralizado (única fonte de polling de /api/status)
  pages/                as 7 telas de produto (ver abaixo)
  components/           Card, LevelBar, AudioSourcePicker (reutilizados
                        entre NewMeeting e ScheduleForm)
  hooks/                um hook por preocupação (useSchedules,
                        useRecentMeetings, useAudioDevices, useSSE
                        genérico + useAudioLevels/useLiveTranscriptionStream
                        em cima dele, etc.) -- nenhuma lógica de domínio
                        nos componentes de página
  services/api.ts       cliente HTTP tipado; só busca dados e envia
                        intenção do usuário, nenhuma decisão de negócio
  types/api.ts          tipos que espelham o contrato real de webui.py
  utils/                formatação (data, duração, bytes, recorrência),
                        type guards (isAudioBackendError)
  test/setup.ts         `@testing-library/jest-dom` carregado pro vitest
```

## As 7 telas

1. **Dashboard** — status de conexão, próxima gravação agendada com
   contagem regressiva, busca + 5 reuniões recentes, pasta ativa e
   espaço livre.
2. **Nova reunião** — escolher pasta (diálogo nativo ou caminho manual),
   modelo Whisper, idioma, dispositivo (CPU/CUDA), fontes de áudio com
   "Testar áudio" de verdade, inicia uma gravação real.
3. **Gravação** — medidores de nível em tempo real e transcrição ao vivo
   (ambos via SSE), cronômetro, parar. Mostra "Finalizando reunião..."
   enquanto o backend está no encerramento gracioso (`status.stopping`)
   — nunca assume que a gravação parou só porque `POST /api/stop`
   respondeu 200.
4. **Detalhe da reunião** — metadados, transcrição completa com
   timecodes/speaker, exportação em 5 formatos, abas de
   Resumo/Tarefas/Decisões marcadas honestamente como "não processado"
   (Meeting Intelligence, Fase G, não implementada).
5. **Agendamentos** — lista com status, cancelar, iniciar agora, ignorar
   perdido.
6. **Criar/editar agendamento** — recorrência completa (diária, dias
   úteis, semanal, dias específicos — troca sozinho de "semanal" pra
   "dias específicos" se o usuário marcar mais de um dia, já que o
   backend só aceita 1 dia para recorrência semanal).
7. **Configurações** — pasta de reuniões, preferências de dispositivo de
   áudio, aviso de espaço em disco.

O ciclo completo **criar → gravar → ver → exportar → agendar** é
navegável inteiramente aqui, contra o backend real.

## Rodando

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173, com proxy de /api/* pro
                  # webui.py real (precisa estar rodando em 127.0.0.1:8765)
npm run build    # tsc -b (type-check) + vite build -> dist/
                  # webui.py detecta dist/ automaticamente e passa a servi-lo
npx oxlint        # lint
npm test          # vitest run (cobertura descrita abaixo)
```

Em produção (`iniciar.bat` → `python webui.py`), nenhum passo de build
manual é necessário se `frontend/dist/` já existe no repositório/pacote
distribuído — mas se você alterar algo em `frontend/src/`, rode
`npm run build` de novo antes de testar via `iniciar.bat`, senão o
backend continua servindo o build antigo.

## Testes

`vitest` + `@testing-library/react` + `jest-dom` + `user-event`, ambiente
`jsdom`. Cobertura atual (ver `docs/PENDENCIAS.md` para o que ainda
falta):

- **App**: o ciclo de vida completo de uma gravação — idle → nova
  reunião → iniciando → gravando → parar → finalizando → idle — incluindo
  a regressão de navegação que a auditoria encontrou (P1-1: o usuário era
  ejetado de volta pro Dashboard antes de ver a tela de Gravação).
- **useSSE**: o hook genérico de Server-Sent Events por trás dos
  medidores de áudio e da transcrição ao vivo (conexão, parsing,
  reconexão, evento malformado, cleanup) — via um `EventSource` falso,
  já que `jsdom` não implementa isso nativamente.
- **NewMeeting**: payload correto por combinação de fontes de áudio,
  botão desabilitado sem nenhuma fonte selecionada, erro do backend
  exibido, "Testar áudio".
- **ScheduleForm**: recorrência semanal (1 dia), troca automática pra
  "dias específicos" ao marcar um 2º dia, validação de título/pasta
  obrigatórios.
- **Dashboard**: estado vazio, lista de reuniões recentes, busca, banner
  de gravando/finalizando.
- **MeetingDetail**: transcrição com timecodes, os 5 links de
  exportação, abas de Intelligence como "não processado", erro quando a
  reunião não está no índice.

Não cobertos ainda por teste automatizado: Recording.tsx isolado (a
lógica de stopping dele é exercida indiretamente pelo teste de App, mas
não há um teste dedicado ao componente); Schedules.tsx (lista/ações);
Settings.tsx.

## Integração com o backend

Nenhuma lógica de negócio aqui — toda validação (pasta segura, áudio
disponível, recorrência válida) é resposta do backend. Em
desenvolvimento, o Vite faz proxy de `/api/*` pro `webui.py` real
(`vite.config.ts`); em produção, o próprio `webui.py` serve os arquivos
estáticos deste build a partir da mesma origem, então `/api/...`
continua correto sem nenhuma mudança de código entre os dois modos.

import { useState } from "react";
import { useBackendStatus } from "../hooks/useBackendStatus";
import { Dashboard } from "../pages/Dashboard";
import { History } from "../pages/History";
import { MeetingDetail } from "../pages/MeetingDetail";
import { NewMeeting } from "../pages/NewMeeting";
import { Recording } from "../pages/Recording";
import { ScheduleForm } from "../pages/ScheduleForm";
import { Schedules } from "../pages/Schedules";
import { Settings } from "../pages/Settings";
import type { Schedule } from "../types/api";

type View =
  | { name: "dashboard" }
  | { name: "history" }
  /** `from`: pra onde "Voltar" leva (Dashboard ou Histórico). */
  | { name: "meeting"; id: string; from: { name: "dashboard" } | { name: "history" } }
  /**
   * "starting": acabamos de mandar POST /api/start com sucesso, mas o
   * PRÓXIMO /api/status ainda não confirmou `running: true` -- pode levar
   * uma volta de rede. "active": já confirmado. Essa distinção é o que
   * elimina a race condition que a auditoria encontrou (P1-1): sem ela,
   * o efeito abaixo que ejeta pra Dashboard quando `!status.running` via
   * polling anterior ejetava o usuário imediatamente de volta, antes do
   * status novo chegar -- ele nunca chegava a ver a tela de Gravação.
   */
  | { name: "recording"; phase: "starting" | "active" }
  | { name: "schedules" }
  | { name: "new-meeting" }
  | { name: "schedule-form"; existing?: Schedule }
  | { name: "settings" };

/**
 * Telas do produto (ver `pages/`): Dashboard, Histórico, Nova Reunião,
 * Gravação, Detalhe da Reunião, Agendamentos + criar/editar e
 * Configurações. `useBackendStatus` vive aqui (não em cada tela) porque
 * TODAS as telas precisam saber se há uma gravação ativa -- uma só fonte de
 * polling, nunca um `useBackendStatus()` duplicado por tela.
 *
 * Navegação por `useState` simples de propósito -- um router de verdade
 * (`react-router`) não trouxe valor suficiente pro número de telas atual
 * (ver docs/PENDENCIAS.md se isso mudar).
 *
 * Esta é a interface ativa (servida por `webui.py`): criar, gravar,
 * acompanhar ao vivo, parar, reprocessar sessões interrompidas, buscar no
 * histórico, exportar e agendar acontecem inteiramente por aqui.
 */
export function App() {
  const { status, refresh: refreshStatus } = useBackendStatus();
  const [view, setView] = useState<View>({ name: "dashboard" });

  if (view.name === "recording") {
    if (view.phase === "starting") {
      // NUNCA ejeta pro Dashboard neste estado transitório, mesmo que
      // `status` ainda diga `running: false` (pode ser um poll que
      // começou antes do /api/start ser aceito) -- só avança pra "active"
      // quando o backend de fato confirmar. `start_transcriber` (webui.py)
      // seta `state["proc"]` de forma síncrona ANTES de responder 200 ao
      // cliente, então essa confirmação é garantida a chegar na próxima
      // leitura de status, sem precisar de timeout/retry arbitrário aqui.
      if (status?.running) {
        setView({ name: "recording", phase: "active" });
      }
    } else if (status !== null && !status.running) {
      // já confirmada como ativa antes -- se parar por qualquer motivo
      // (parada manual concluída, fim automático de um agendamento, o
      // processo morrer), volta pro Dashboard sozinho.
      setView({ name: "dashboard" });
    }
  }

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 antialiased">
      {view.name === "meeting" && (
        <MeetingDetail meetingId={view.id} onBack={() => setView(view.from)} />
      )}

      {view.name === "history" && (
        <History
          onBack={() => setView({ name: "dashboard" })}
          onSelectMeeting={(id) => setView({ name: "meeting", id, from: { name: "history" } })}
        />
      )}

      {view.name === "recording" && view.phase === "starting" && (
        <div className="mx-auto max-w-2xl px-4 py-10 text-center text-neutral-400">
          <p>Iniciando gravação…</p>
        </div>
      )}

      {view.name === "recording" && view.phase === "active" && status?.running && <Recording status={status} />}

      {view.name === "schedules" && (
        <Schedules
          onBack={() => setView({ name: "dashboard" })}
          onNew={() => setView({ name: "schedule-form" })}
          onEdit={(schedule) => setView({ name: "schedule-form", existing: schedule })}
        />
      )}

      {view.name === "schedule-form" && (
        <ScheduleForm
          existing={view.existing}
          onBack={() => setView({ name: "schedules" })}
          onSaved={() => setView({ name: "schedules" })}
        />
      )}

      {view.name === "new-meeting" && (
        <NewMeeting
          onBack={() => setView({ name: "dashboard" })}
          onStarted={() => {
            setView({ name: "recording", phase: "starting" });
            refreshStatus(); // acelera a confirmacao (ver comentario da phase "starting" acima)
          }}
        />
      )}

      {view.name === "settings" && <Settings onBack={() => setView({ name: "dashboard" })} />}

      {view.name === "dashboard" && (
        <Dashboard
          status={status}
          onSelectMeeting={(id) => setView({ name: "meeting", id, from: { name: "dashboard" } })}
          onViewRecording={() => setView({ name: "recording", phase: "active" })}
          onViewSchedules={() => setView({ name: "schedules" })}
          onViewHistory={() => setView({ name: "history" })}
          onNewMeeting={() => setView({ name: "new-meeting" })}
          onViewSettings={() => setView({ name: "settings" })}
        />
      )}
    </div>
  );
}

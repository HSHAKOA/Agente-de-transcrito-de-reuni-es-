import { TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useBackendStatus } from "../hooks/useBackendStatus";
import { Dashboard } from "../pages/Dashboard";
import { MeetingDetail } from "../pages/MeetingDetail";
import { NewMeeting } from "../pages/NewMeeting";
import { Recording } from "../pages/Recording";
import { ScheduleForm } from "../pages/ScheduleForm";
import { Schedules } from "../pages/Schedules";
import { Settings } from "../pages/Settings";
import type { Schedule } from "../types/api";

type View =
  | { name: "dashboard" }
  | { name: "meeting"; id: string }
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
 * A Fase F ganhou todas as telas nomeadas na missão (Dashboard, Nova
 * Reunião, Gravação, Detalhe da Reunião, Agendamentos + criar/editar,
 * Configurações -- ver `pages/`). `useBackendStatus` vive aqui (não em
 * cada tela) porque TODAS as telas precisam saber se há uma gravação
 * ativa -- uma só fonte de polling, nunca um `useBackendStatus()`
 * duplicado por tela.
 *
 * Navegação por `useState` simples de propósito -- um router de verdade
 * (`react-router`) não trouxe valor suficiente pro número de telas atual
 * (ver docs/PENDENCIAS.md se isso mudar).
 *
 * Já é possível criar, gravar, acompanhar ao vivo, parar, ver, exportar
 * e agendar uma reunião inteiramente por aqui -- mas `index.html`
 * continua sendo a interface de referência até a paridade funcional
 * completa ser demonstrada de ponta a ponta (ver docs/ROADMAP.md, Fase F).
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
      <div className="mx-auto max-w-2xl px-4 pt-4">
        <div className="flex items-center gap-2 rounded-lg border border-amber-800/60 bg-amber-950/40 px-4 py-3 text-sm text-amber-200">
          <TriangleAlert className="size-4 shrink-0" />
          <span>
            Prévia (Fase F) — para iniciar/agendar uma gravação, use{" "}
            <code className="rounded bg-black/30 px-1 py-0.5">http://127.0.0.1:8765</code>.
          </span>
        </div>
      </div>

      {view.name === "meeting" && (
        <MeetingDetail meetingId={view.id} onBack={() => setView({ name: "dashboard" })} />
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
          onSelectMeeting={(id) => setView({ name: "meeting", id })}
          onViewRecording={() => setView({ name: "recording", phase: "active" })}
          onViewSchedules={() => setView({ name: "schedules" })}
          onNewMeeting={() => setView({ name: "new-meeting" })}
          onViewSettings={() => setView({ name: "settings" })}
        />
      )}
    </div>
  );
}

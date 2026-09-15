import { TriangleAlert } from "lucide-react";
import { useState } from "react";
import { useBackendStatus } from "../hooks/useBackendStatus";
import { Dashboard } from "../pages/Dashboard";
import { MeetingDetail } from "../pages/MeetingDetail";
import { NewMeeting } from "../pages/NewMeeting";
import { Recording } from "../pages/Recording";
import { ScheduleForm } from "../pages/ScheduleForm";
import { Schedules } from "../pages/Schedules";
import type { Schedule } from "../types/api";

type View =
  | { name: "dashboard" }
  | { name: "meeting"; id: string }
  | { name: "recording" }
  | { name: "schedules" }
  | { name: "new-meeting" }
  | { name: "schedule-form"; existing?: Schedule };

/**
 * A Fase F ganhou três telas de produto de verdade (Dashboard, Detalhe
 * da Reunião, Gravação -- ver `pages/`) -- não é mais só um preview de
 * conectividade. `useBackendStatus` vive aqui (não em cada tela) porque
 * TODAS as telas precisam saber se há uma gravação ativa (pra Dashboard
 * mostrar o banner, pra decidir se Gravação pode ser exibida) -- uma só
 * fonte de polling, nunca um `useBackendStatus()` duplicado por tela.
 *
 * Navegação por `useState` simples de propósito: poucas telas hoje, um
 * router de verdade (`react-router`) só se justifica quando Nova
 * Reunião/Agendamentos/Configurações também existirem (ver
 * docs/PENDENCIAS.md).
 *
 * Ainda assim, esta interface é SOMENTE LEITURA pra a maior parte das
 * ações -- só "Parar reunião" (Recording) chama de verdade o backend
 * pra mudar algo; iniciar gravação, criar agendamento e escolher pasta
 * continuam exigindo o painel real em `index.html` por enquanto (ver
 * docs/ROADMAP.md, Fase F).
 */
export function App() {
  const { status } = useBackendStatus();
  const [view, setView] = useState<View>({ name: "dashboard" });

  // se a gravação parar por qualquer motivo enquanto a tela de Gravação
  // está aberta (parada manual, fim automático de um agendamento, o
  // processo morrer), volta pro Dashboard sozinho -- nunca fica presa
  // numa tela de "gravando" para uma gravação que já terminou.
  if (view.name === "recording" && status !== null && !status.running) {
    setView({ name: "dashboard" });
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

      {view.name === "recording" && status?.running && (
        <Recording status={status} onStopped={() => setView({ name: "dashboard" })} />
      )}

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
          onStarted={() => setView({ name: "recording" })}
        />
      )}

      {view.name === "dashboard" && (
        <Dashboard
          status={status}
          onSelectMeeting={(id) => setView({ name: "meeting", id })}
          onViewRecording={() => setView({ name: "recording" })}
          onViewSchedules={() => setView({ name: "schedules" })}
          onNewMeeting={() => setView({ name: "new-meeting" })}
        />
      )}
    </div>
  );
}

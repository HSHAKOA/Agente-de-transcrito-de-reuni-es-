import { ArrowLeft, Calendar, Repeat } from "lucide-react";
import { Card } from "../components/Card";
import { useScheduleActions } from "../hooks/useScheduleActions";
import { useSchedules } from "../hooks/useSchedules";
import type { Schedule, ScheduleStatus } from "../types/api";
import { formatTime } from "../utils/formatDate";
import { formatRecurrence } from "../utils/formatRecurrence";

const STATUS_LABELS: Record<ScheduleStatus, string> = {
  scheduled: "Programada",
  preparing: "Preparando",
  recording: "Gravando",
  finishing: "Finalizando",
  completed: "Concluída",
  missed: "Perdida",
  failed: "Falhou",
  cancelled: "Cancelada",
};

const ACTIONABLE_MISSED: ScheduleStatus[] = ["missed", "failed"];
const ACTIONABLE_PENDING: ScheduleStatus[] = ["scheduled", "preparing"];
const IN_PROGRESS: ScheduleStatus[] = ["recording", "finishing"];

function StatusBadge({ status }: { status: ScheduleStatus }) {
  const tone =
    status === "completed"
      ? "text-emerald-400 bg-emerald-950/40 border-emerald-800/50"
      : status === "missed" || status === "failed"
        ? "text-red-400 bg-red-950/40 border-red-800/50"
        : IN_PROGRESS.includes(status)
          ? "text-red-400 bg-red-950/40 border-red-800/50"
          : "text-amber-400 bg-amber-950/40 border-amber-800/50";
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${tone}`}>{STATUS_LABELS[status]}</span>;
}

function ScheduleRow({
  schedule,
  busy,
  onStartNow,
  onCancel,
  onIgnoreMissed,
  onEdit,
}: {
  schedule: Schedule;
  busy: boolean;
  onStartNow: () => void;
  onCancel: () => void;
  onIgnoreMissed: () => void;
  onEdit: () => void;
}) {
  const run = schedule.current_run;
  const window = run ? `${formatTime(run.scheduled_start_at)}–${formatTime(run.scheduled_end_at)}` : "—";

  return (
    <div className="border-b border-neutral-800/60 py-3 last:border-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium">{schedule.title}</p>
          <p className="mt-0.5 flex items-center gap-2 text-xs text-neutral-500">
            <span>{window}</span>
            <span className="flex items-center gap-1">
              <Repeat className="size-3" />
              {formatRecurrence(schedule.recurrence)}
            </span>
          </p>
          {run?.error_message && <p className="mt-1 text-xs text-red-400">{run.error_message}</p>}
        </div>
        <StatusBadge status={schedule.status} />
      </div>

      {(ACTIONABLE_PENDING.includes(schedule.status) || ACTIONABLE_MISSED.includes(schedule.status)) && (
        <div className="mt-2 flex gap-2">
          <button
            onClick={onStartNow}
            disabled={busy}
            className="rounded-md border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 transition-colors hover:bg-neutral-800 disabled:opacity-50"
          >
            Iniciar agora
          </button>
          {ACTIONABLE_MISSED.includes(schedule.status) ? (
            <button
              onClick={onIgnoreMissed}
              disabled={busy}
              className="rounded-md border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 transition-colors hover:bg-neutral-800 disabled:opacity-50"
            >
              Ignorar
            </button>
          ) : (
            <>
              <button
                onClick={onEdit}
                disabled={busy}
                className="rounded-md border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 transition-colors hover:bg-neutral-800 disabled:opacity-50"
              >
                Editar
              </button>
              <button
                onClick={onCancel}
                disabled={busy}
                className="rounded-md border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 transition-colors hover:bg-neutral-800 disabled:opacity-50"
              >
                Cancelar
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

interface SchedulesProps {
  onBack: () => void;
  onNew: () => void;
  onEdit: (schedule: Schedule) => void;
}

/**
 * Lista de agendamentos (F.8), com criar/editar (`pages/ScheduleForm.tsx`)
 * e as ações que já são chamadas simples de API (iniciar agora, cancelar,
 * ignorar perdida).
 */
export function Schedules({ onBack, onNew, onEdit }: SchedulesProps) {
  const { schedules, error: loadError, refresh } = useSchedules();
  const { busyId, error: actionError, startNow, cancel, ignoreMissed } = useScheduleActions(refresh);

  const visible = (schedules ?? []).filter((s) => s.status !== "cancelled");

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <button
        onClick={onBack}
        className="mb-4 flex items-center gap-1.5 text-sm text-neutral-400 transition-colors hover:text-neutral-100"
      >
        <ArrowLeft className="size-4" />
        Voltar
      </button>

      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight">Agendamentos</h1>
        <button
          onClick={onNew}
          className="rounded-md border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 transition-colors hover:bg-neutral-800"
        >
          + Novo agendamento
        </button>
      </div>

      {(loadError || actionError) && <p className="mt-3 text-sm text-red-400">{loadError ?? actionError}</p>}

      <Card icon={<Calendar className="size-4 text-neutral-500" />} className="mt-4">
        {schedules === null && <p className="text-sm text-neutral-500">Carregando…</p>}
        {schedules !== null && visible.length === 0 && (
          <p className="text-sm text-neutral-500">Nenhum agendamento ativo — use “+ Novo agendamento” para criar um.</p>
        )}
        {visible.length > 0 && (
          <div>
            {visible.map((s) => (
              <ScheduleRow
                key={s.id}
                schedule={s}
                busy={busyId === s.id}
                onStartNow={() => startNow(s.id)}
                onCancel={() => cancel(s.id)}
                onIgnoreMissed={() => ignoreMissed(s.id)}
                onEdit={() => onEdit(s)}
              />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

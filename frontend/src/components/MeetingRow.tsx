import type { MeetingRecord } from "../types/api";
import { formatDateTime } from "../utils/formatDate";
import { formatDuration } from "../utils/formatDuration";
import { STATUS_LABELS } from "../utils/meetingStatus";

export function StatusPill({ status }: { status: string }) {
  const label = STATUS_LABELS[status] ?? status;
  const tone =
    status === "completed"
      ? "text-emerald-400 bg-emerald-950/40 border-emerald-800/50"
      : status === "failed" || status === "interrupted"
        ? "text-red-400 bg-red-950/40 border-red-800/50"
        : "text-amber-400 bg-amber-950/40 border-amber-800/50";
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${tone}`}>{label}</span>;
}

/** Linha de reunião reutilizada no Dashboard (recentes/busca rápida) e no
 * Histórico -- um botão só, para abrir o detalhe pelo teclado também. */
export function MeetingRow({ meeting, onSelect }: { meeting: MeetingRecord; onSelect: (id: string) => void }) {
  return (
    <button
      onClick={() => onSelect(meeting.id)}
      className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-neutral-800/60"
    >
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{meeting.title}</p>
        <p className="mt-0.5 text-xs text-neutral-500">{formatDateTime(meeting.started_at)}</p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span className="text-sm text-neutral-400">{formatDuration(meeting.duration_seconds)}</span>
        <StatusPill status={meeting.status} />
      </div>
    </button>
  );
}

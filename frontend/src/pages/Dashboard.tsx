import { Calendar, CircleDot, FolderOpen, HardDrive, History, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { Card } from "../components/Card";
import { formatCountdown, useCountdown } from "../hooks/useCountdown";
import { useBackendStatus } from "../hooks/useBackendStatus";
import { useRecentMeetings } from "../hooks/useRecentMeetings";
import { useSchedules } from "../hooks/useSchedules";
import { useSettingsInfo } from "../hooks/useSettingsInfo";
import { api } from "../services/api";
import type { MeetingRecord } from "../types/api";
import { formatDateTime } from "../utils/formatDate";
import { formatBytes } from "../utils/formatBytes";
import { formatDuration } from "../utils/formatDuration";

const STATUS_LABELS: Record<string, string> = {
  completed: "Concluída",
  recording: "Gravando",
  processing: "Processando",
  interrupted: "Interrompida",
  failed: "Falhou",
};

function StatusPill({ status }: { status: string }) {
  const label = STATUS_LABELS[status] ?? status;
  const tone =
    status === "completed"
      ? "text-emerald-400 bg-emerald-950/40 border-emerald-800/50"
      : status === "failed" || status === "interrupted"
        ? "text-red-400 bg-red-950/40 border-red-800/50"
        : "text-amber-400 bg-amber-950/40 border-amber-800/50";
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs ${tone}`}>{label}</span>
  );
}

function NextRecordingCard() {
  const { schedules } = useSchedules();

  const next = useMemo(() => {
    if (!schedules) return null;
    const withNextRun = schedules.filter(
      (s) => s.status !== "cancelled" && s.seconds_until_next_run !== null && s.seconds_until_next_run >= 0,
    );
    withNextRun.sort((a, b) => (a.seconds_until_next_run ?? 0) - (b.seconds_until_next_run ?? 0));
    return withNextRun[0] ?? null;
  }, [schedules]);

  const remaining = useCountdown(next?.seconds_until_next_run ?? null);

  if (schedules === null) {
    return (
      <Card title="Próxima gravação" icon={<Calendar className="size-4 text-neutral-400" />}>
        <p className="text-sm text-neutral-500">Consultando agendamentos…</p>
      </Card>
    );
  }

  if (!next || remaining === null) {
    return (
      <Card title="Próxima gravação" icon={<Calendar className="size-4 text-neutral-400" />}>
        <p className="text-sm text-neutral-500">Nenhuma gravação agendada.</p>
      </Card>
    );
  }

  const start = next.current_run ? formatDateTime(next.current_run.scheduled_start_at) : "—";

  return (
    <Card title="Próxima gravação" icon={<Calendar className="size-4 text-neutral-400" />}>
      <p className="text-base font-medium">{next.title}</p>
      <p className="mt-1 text-sm text-neutral-400">{start}</p>
      <p className="mt-2 text-sm text-neutral-300">
        Começa em <span className="font-medium text-neutral-100">{formatCountdown(remaining)}</span>
      </p>
    </Card>
  );
}

function MeetingRow({ meeting }: { meeting: MeetingRecord }) {
  return (
    <a
      href={api.meetingExportUrl(meeting.id, "markdown")}
      className="flex items-center justify-between gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-neutral-800/60"
    >
      <div className="min-w-0">
        <p className="truncate text-sm font-medium">{meeting.title}</p>
        <p className="mt-0.5 text-xs text-neutral-500">{formatDateTime(meeting.started_at)}</p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <span className="text-sm text-neutral-400">{formatDuration(meeting.duration_seconds)}</span>
        <StatusPill status={meeting.status} />
      </div>
    </a>
  );
}

function RecentMeetings() {
  const { meetings, total, error } = useRecentMeetings(5);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MeetingRecord[] | null>(null);
  const [searching, setSearching] = useState(false);

  async function runSearch(q: string) {
    setQuery(q);
    if (!q.trim()) {
      setSearchResults(null);
      return;
    }
    setSearching(true);
    try {
      const data = await api.getMeetings({ q, limit: 20 });
      setSearchResults(data.meetings);
    } finally {
      setSearching(false);
    }
  }

  const list = searchResults ?? meetings;

  return (
    <Card>
      <div className="mb-3 flex items-center gap-2 rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2">
        <Search className="size-4 shrink-0 text-neutral-500" />
        <input
          value={query}
          onChange={(e) => runSearch(e.target.value)}
          placeholder="Pesquisar reuniões…"
          className="w-full bg-transparent text-sm outline-none placeholder:text-neutral-600"
        />
      </div>

      <div className="mb-2 flex items-center gap-2 text-xs font-medium tracking-wide text-neutral-500 uppercase">
        <History className="size-3.5" />
        {searchResults ? `Resultados (${searchResults.length})` : `Reuniões recentes (${total})`}
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}
      {searching && <p className="text-sm text-neutral-500">Buscando…</p>}
      {!searching && list && list.length === 0 && (
        <p className="text-sm text-neutral-500">
          {searchResults
            ? "Nenhuma reunião encontrada."
            : "Nenhuma reunião no histórico ainda — inicie uma gravação pelo painel ou importe reuniões existentes."}
        </p>
      )}
      {!searching && list && list.length > 0 && (
        <div className="-mx-1">
          {list.map((m) => (
            <MeetingRow key={m.id} meeting={m} />
          ))}
        </div>
      )}
    </Card>
  );
}

/**
 * Primeira tela de produto de verdade da Fase F (as demais -- Nova
 * Reunião, Gravação, Histórico completo, Agendamentos, Configurações --
 * seguem o mesmo padrão: hook dedicado em `hooks/`, consumindo
 * `services/api.ts`, sem nenhuma lógica de domínio no componente). Ainda
 * somente-leitura: iniciar/parar gravação, criar agendamento, e escolher
 * pasta continuam exigindo o painel real em `index.html` por enquanto.
 */
export function Dashboard() {
  const { status } = useBackendStatus();
  const { settings } = useSettingsInfo();
  const connected = status !== null;

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight">Meeting Intelligence</h1>
        <div className="flex items-center gap-1.5 text-xs text-neutral-500">
          <CircleDot className={`size-3 ${connected ? "text-emerald-400" : "text-neutral-600"}`} />
          {connected ? "Conectado" : "Sem conexão"}
        </div>
      </div>

      {status?.running && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-red-800/50 bg-red-950/30 px-4 py-2.5 text-sm text-red-300">
          <CircleDot className="size-3 animate-pulse fill-red-400 text-red-400" />
          Gravando agora — {status.output_path ?? "reunião em andamento"}
        </div>
      )}

      <div className="grid gap-4">
        <NextRecordingCard />
        <RecentMeetings />

        {settings && (
          <Card icon={<FolderOpen className="size-4 text-neutral-500" />} className="text-sm">
            <div className="flex items-center justify-between gap-3">
              <span className="truncate font-mono text-xs text-neutral-400">{settings.meetings_root}</span>
              <span className="flex shrink-0 items-center gap-1.5 text-neutral-500">
                <HardDrive className="size-3.5" />
                {formatBytes(settings.free_bytes)}
              </span>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}

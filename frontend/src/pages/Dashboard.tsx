import { Calendar, CircleDot, FolderOpen, HardDrive, History, Search, Settings as SettingsIcon } from "lucide-react";
import { useMemo, useState } from "react";
import { Card } from "../components/Card";
import { MeetingRow } from "../components/MeetingRow";
import { RecoveryBanner } from "../components/RecoveryBanner";
import { formatCountdown, useCountdown } from "../hooks/useCountdown";
import { useRecentMeetings } from "../hooks/useRecentMeetings";
import { useSchedules } from "../hooks/useSchedules";
import { useSettingsInfo } from "../hooks/useSettingsInfo";
import { api } from "../services/api";
import type { MeetingRecord, StatusResponse } from "../types/api";
import { formatDateTime } from "../utils/formatDate";
import { formatBytes } from "../utils/formatBytes";

function NextRecordingCard({ onOpenSchedules }: { onOpenSchedules: () => void }) {
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

  const header = (
    <div className="mb-3 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <Calendar className="size-4 text-neutral-400" />
        <span className="font-medium">Próxima gravação</span>
      </div>
      <button onClick={onOpenSchedules} className="text-xs text-neutral-500 hover:text-neutral-300">
        Ver agendamentos
      </button>
    </div>
  );

  if (schedules === null) {
    return (
      <Card>
        {header}
        <p className="text-sm text-neutral-500">Consultando agendamentos…</p>
      </Card>
    );
  }

  if (!next || remaining === null) {
    return (
      <Card>
        {header}
        <p className="text-sm text-neutral-500">Nenhuma gravação agendada.</p>
      </Card>
    );
  }

  const start = next.current_run ? formatDateTime(next.current_run.scheduled_start_at) : "—";

  return (
    <Card>
      {header}
      <p className="text-base font-medium">{next.title}</p>
      <p className="mt-1 text-sm text-neutral-400">{start}</p>
      <p className="mt-2 text-sm text-neutral-300">
        Começa em <span className="font-medium text-neutral-100">{formatCountdown(remaining)}</span>
      </p>
    </Card>
  );
}

function RecentMeetings({
  onSelectMeeting,
  onViewHistory,
}: {
  onSelectMeeting: (id: string) => void;
  onViewHistory: () => void;
}) {
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

      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-xs font-medium tracking-wide text-neutral-500 uppercase">
          <History className="size-3.5" />
          {searchResults ? `Resultados (${searchResults.length})` : `Reuniões recentes (${total})`}
        </div>
        <button onClick={onViewHistory} className="text-xs text-neutral-500 hover:text-neutral-300">
          Ver histórico completo
        </button>
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
            <MeetingRow key={m.id} meeting={m} onSelect={onSelectMeeting} />
          ))}
        </div>
      )}
    </Card>
  );
}

/**
 * Tela inicial: status de conexão, sessões interrompidas (recuperação),
 * próxima gravação agendada, reuniões recentes com busca rápida (o
 * histórico completo, paginado e filtrável, é a tela `History`) e a pasta
 * ativa. Cada bloco usa um hook dedicado em `hooks/` sobre
 * `services/api.ts`, sem lógica de domínio no componente.
 */
interface DashboardProps {
  status: StatusResponse | null;
  onSelectMeeting: (id: string) => void;
  onViewRecording: () => void;
  onViewSchedules: () => void;
  onViewHistory: () => void;
  onNewMeeting: () => void;
  onViewSettings: () => void;
}

export function Dashboard({
  status,
  onSelectMeeting,
  onViewRecording,
  onViewSchedules,
  onViewHistory,
  onNewMeeting,
  onViewSettings,
}: DashboardProps) {
  const { settings } = useSettingsInfo();
  const connected = status !== null;

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-xl font-semibold tracking-tight">Meeting Intelligence</h1>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 text-xs text-neutral-500">
            <CircleDot className={`size-3 ${connected ? "text-emerald-400" : "text-neutral-600"}`} />
            {connected ? "Conectado" : "Sem conexão"}
          </div>
          {!status?.running && (
            <button
              onClick={onNewMeeting}
              className="rounded-md border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 transition-colors hover:bg-neutral-800"
            >
              + Nova reunião
            </button>
          )}
          <button
            onClick={onViewSettings}
            aria-label="Configurações"
            className="text-neutral-500 transition-colors hover:text-neutral-300"
          >
            <SettingsIcon className="size-4" />
          </button>
        </div>
      </div>

      {status?.running && (
        <button
          onClick={onViewRecording}
          className="mb-4 flex w-full items-center gap-2 rounded-lg border border-red-800/50 bg-red-950/30 px-4 py-2.5 text-left text-sm text-red-300 transition-colors hover:bg-red-950/50"
        >
          <CircleDot className="size-3 animate-pulse fill-red-400 text-red-400" />
          {status.mode === "resume"
            ? status.stopping
              ? "Finalizando reprocessamento…"
              : "Reprocessando uma sessão interrompida…"
            : status.stopping
              ? "Finalizando gravação…"
              : `Gravando agora — ${status.output_path ?? "reunião em andamento"}`}
        </button>
      )}

      <RecoveryBanner running={Boolean(status?.running)} />

      <div className="grid gap-4">
        <NextRecordingCard onOpenSchedules={onViewSchedules} />
        <RecentMeetings onSelectMeeting={onSelectMeeting} onViewHistory={onViewHistory} />

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

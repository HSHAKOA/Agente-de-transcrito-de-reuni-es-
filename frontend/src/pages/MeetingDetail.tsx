import { ArrowLeft, Download, FileText, Sparkles } from "lucide-react";
import { useState } from "react";
import { Card } from "../components/Card";
import { useMeetingDetail } from "../hooks/useMeetingDetail";
import { api } from "../services/api";
import type { ExportFormat, MeetingSegmentRecord } from "../types/api";
import { formatDateTime } from "../utils/formatDate";
import { formatDuration } from "../utils/formatDuration";

const EXPORT_FORMATS: { format: ExportFormat; label: string }[] = [
  { format: "markdown", label: "Markdown" },
  { format: "txt", label: "TXT" },
  { format: "json", label: "JSON" },
  { format: "srt", label: "SRT" },
  { format: "vtt", label: "VTT" },
];

type Tab = "transcript" | "summary" | "tasks" | "decisions";

const TABS: { id: Tab; label: string }[] = [
  { id: "transcript", label: "Transcrição" },
  { id: "summary", label: "Resumo" },
  { id: "tasks", label: "Tarefas" },
  { id: "decisions", label: "Decisões" },
];

function NotProcessed() {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-dashed border-neutral-800 px-4 py-6 text-sm text-neutral-500">
      <Sparkles className="size-4 shrink-0" />
      Recurso ainda não processado — a geração automática de resumo, tarefas e
      decisões (Meeting Intelligence) não foi implementada nesta fase.
    </div>
  );
}

function SegmentRow({ segment }: { segment: MeetingSegmentRecord }) {
  const minutes = Math.floor(segment.start_seconds / 60);
  const seconds = Math.floor(segment.start_seconds % 60);
  const timestamp = `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  return (
    <div className="border-b border-neutral-800/60 py-2.5 last:border-0">
      <div className="flex items-baseline gap-2 text-xs text-neutral-500">
        <span className="font-mono">{timestamp}</span>
        {segment.speaker_label && <span className="font-medium text-neutral-400">{segment.speaker_label}</span>}
      </div>
      <p className="mt-1 text-sm text-neutral-200">{segment.text}</p>
    </div>
  );
}

interface MeetingDetailProps {
  meetingId: string;
  onBack: () => void;
}

export function MeetingDetail({ meetingId, onBack }: MeetingDetailProps) {
  const { detail, loading, error } = useMeetingDetail(meetingId);
  const [tab, setTab] = useState<Tab>("transcript");

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <button
        onClick={onBack}
        className="mb-4 flex items-center gap-1.5 text-sm text-neutral-400 transition-colors hover:text-neutral-100"
      >
        <ArrowLeft className="size-4" />
        Voltar
      </button>

      {loading && <p className="text-sm text-neutral-500">Carregando…</p>}
      {error && <p className="text-sm text-red-400">{error}</p>}

      {detail?.meeting && (
        <>
          <h1 className="text-xl font-semibold tracking-tight">{detail.meeting.title}</h1>
          <p className="mt-1 text-sm text-neutral-400">
            {formatDateTime(detail.meeting.started_at)} · {formatDuration(detail.meeting.duration_seconds)}
          </p>

          <div className="mt-4 flex flex-wrap gap-2">
            {EXPORT_FORMATS.map(({ format, label }) => (
              <a
                key={format}
                href={api.meetingExportUrl(meetingId, format)}
                className="flex items-center gap-1.5 rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-1.5 text-xs text-neutral-300 transition-colors hover:border-neutral-700 hover:bg-neutral-800"
              >
                <Download className="size-3.5" />
                {label}
              </a>
            ))}
          </div>

          <div className="mt-6 flex gap-1 border-b border-neutral-800">
            {TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={`border-b-2 px-3 py-2 text-sm transition-colors ${
                  tab === t.id
                    ? "border-neutral-100 text-neutral-100"
                    : "border-transparent text-neutral-500 hover:text-neutral-300"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="mt-4">
            {tab === "transcript" && (
              <Card icon={<FileText className="size-4 text-neutral-500" />}>
                {detail.segments && detail.segments.length > 0 ? (
                  <div>
                    {detail.segments.map((s) => (
                      <SegmentRow key={s.id} segment={s} />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-neutral-500">Nenhum segmento transcrito.</p>
                )}
              </Card>
            )}
            {tab !== "transcript" && <NotProcessed />}
          </div>
        </>
      )}
    </div>
  );
}

import { CircleDot, Square } from "lucide-react";
import { useState } from "react";
import { Card } from "../components/Card";
import { LevelBar } from "../components/LevelBar";
import { useAudioLevels } from "../hooks/useAudioLevels";
import { formatElapsed, useElapsedSeconds } from "../hooks/useElapsedSeconds";
import { useLiveTranscriptionStream } from "../hooks/useLiveTranscriptionStream";
import { api } from "../services/api";
import type { StatusResponse } from "../types/api";

const SOURCE_LABELS: Record<string, string> = {
  system: "Áudio do computador",
  microphone: "Microfone",
  mixed: "Reunião",
};

function meetingFolderName(meetingDir: string | null): string {
  if (!meetingDir) return "";
  const parts = meetingDir.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] ?? "";
}

interface RecordingProps {
  status: StatusResponse;
}

/**
 * Tela principal de apresentação (mockup da missão, F.6) -- somente
 * aparece enquanto `status.running` é verdadeiro (ver App.tsx). Todo o
 * conteúdo em tempo real vem de SSE (níveis de áudio + transcrição ao
 * vivo, Fases C/D), nunca de polling manual espalhado no componente.
 *
 * Não recebe `onStopped`: a navegação de volta pro Dashboard é decidida
 * SÓ por App.tsx observando `status.running` via polling (correção
 * pós-auditoria P1-5) -- chamar uma navegação local aqui, imediatamente
 * após POST /api/stop retornar 200, escondia o usuário do encerramento
 * gracioso real (que pode levar até ~35s) atrás de uma Dashboard que
 * ainda mostrava "Gravando agora".
 */
export function Recording({ status }: RecordingProps) {
  const elapsed = useElapsedSeconds(status.started_at);
  const { data: levels } = useAudioLevels(true);
  const { data: liveTranscription } = useLiveTranscriptionStream(true);
  const [stopRequested, setStopRequested] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);

  // otimista (setado no clique, antes do backend confirmar) OU refletindo
  // o `state["stopping"]` real do backend -- cobre tanto a janela entre o
  // clique e o próximo poll quanto o resto do encerramento gracioso.
  const stopping = stopRequested || status.stopping;

  async function handleStop() {
    if (stopping) return; // trava duplo clique: nunca manda um segundo /api/stop
    setStopRequested(true);
    setStopError(null);
    try {
      const result = await api.stopMeeting();
      if (!result.ok) {
        setStopError(result.message);
        setStopRequested(false);
      }
      // sucesso: nao navega daqui -- App.tsx volta pro Dashboard sozinho
      // quando status.running realmente virar false.
    } catch {
      setStopError("Não foi possível parar a gravação.");
      setStopRequested(false);
    }
  }

  const segments = liveTranscription?.segments ?? [];
  const backlog = liveTranscription?.backlog;

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <CircleDot className="size-4 animate-pulse fill-red-500 text-red-500" />
          <span className="font-medium tracking-wide text-red-400">GRAVANDO</span>
        </div>
        <span className="font-mono text-lg tabular-nums">
          {elapsed !== null ? formatElapsed(elapsed) : "--:--:--"}
        </span>
      </div>

      <h1 className="mt-3 text-lg font-medium">{meetingFolderName(status.meeting_dir) || "Reunião em andamento"}</h1>

      <div className="mt-4 grid gap-3">
        <LevelBar label={SOURCE_LABELS.system} level={levels?.system?.level} active={levels?.system?.active} />
        <LevelBar
          label={SOURCE_LABELS.microphone}
          level={levels?.microphone?.level}
          active={levels?.microphone?.active}
        />
      </div>

      <div className="mt-6">
        <p className="mb-2 text-xs font-medium tracking-wide text-neutral-500 uppercase">Transcrição ao vivo</p>
        <Card>
          {segments.length === 0 ? (
            <p className="text-sm text-neutral-500">Aguardando o primeiro trecho transcrito…</p>
          ) : (
            <div className="max-h-80 space-y-3 overflow-y-auto">
              {segments.map((seg, i) => {
                const minutes = Math.floor(seg.start_seconds / 60);
                const secs = Math.floor(seg.start_seconds % 60);
                return (
                  <div key={`${seg.start_seconds}-${i}`} className={seg.state === "provisional" ? "opacity-60" : ""}>
                    <div className="flex items-baseline gap-2 text-xs text-neutral-500">
                      <span className="font-mono">
                        {String(minutes).padStart(2, "0")}:{String(secs).padStart(2, "0")}
                      </span>
                      <span>{SOURCE_LABELS[seg.source] ?? seg.source}</span>
                    </div>
                    <p className="mt-0.5 text-sm text-neutral-200">{seg.text}</p>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>

      {backlog && (
        <div className="mt-4">
          <p className="mb-2 text-xs font-medium tracking-wide text-neutral-500 uppercase">Processamento</p>
          <Card>
            <dl className="grid grid-cols-3 gap-2 text-center text-sm">
              <div>
                <dt className="text-xs text-neutral-500">Gravado</dt>
                <dd className="mt-0.5 font-mono">{formatElapsed(backlog.recorded_seconds)}</dd>
              </div>
              <div>
                <dt className="text-xs text-neutral-500">Transcrito</dt>
                <dd className="mt-0.5 font-mono">{formatElapsed(backlog.transcribed_seconds)}</dd>
              </div>
              <div>
                <dt className="text-xs text-neutral-500">Pendente</dt>
                <dd
                  className={`mt-0.5 font-mono ${backlog.status === "BEHIND" ? "text-amber-400" : ""}`}
                >
                  {formatElapsed(backlog.pending_seconds)}
                </dd>
              </div>
            </dl>
          </Card>
        </div>
      )}

      {stopping && (
        <div className="mt-4 rounded-lg border border-amber-800/50 bg-amber-950/30 px-4 py-3 text-sm text-amber-200">
          Finalizando reunião... Salvando o último bloco e concluindo a transcrição.
        </div>
      )}

      {stopError && <p className="mt-4 text-sm text-red-400">{stopError}</p>}

      <button
        onClick={handleStop}
        disabled={stopping}
        className="mt-6 flex w-full items-center justify-center gap-2 rounded-lg border border-red-800/60 bg-red-950/40 px-4 py-2.5 text-sm font-medium text-red-300 transition-colors hover:bg-red-950/70 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Square className="size-3.5 fill-current" />
        {stopping ? "Finalizando…" : "Parar reunião"}
      </button>
    </div>
  );
}

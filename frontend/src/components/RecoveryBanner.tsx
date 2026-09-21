import { TriangleAlert } from "lucide-react";
import { useRecovery } from "../hooks/useRecovery";
import { formatDateTime } from "../utils/formatDate";

interface RecoveryBannerProps {
  /** Há uma gravação/reprocessamento rodando agora (o backend só aceita um
   * por vez e recusaria com 409 -- então o botão já vem desabilitado). */
  running: boolean;
}

/**
 * Sessões cujo processo terminou antes de finalizar a transcrição. O áudio
 * de cada bloco continua salvo em disco; "Reprocessar" transcreve só os
 * blocos pendentes, sem gravar nada novo. Some sozinho quando não há
 * nenhuma sessão interrompida.
 */
export function RecoveryBanner({ running }: RecoveryBannerProps) {
  const { sessions, busyId, message, resume } = useRecovery(running);

  if (sessions.length === 0) return null;

  return (
    <section
      aria-label="Sessões interrompidas"
      className="mb-4 rounded-xl border border-amber-800/50 bg-amber-950/20 p-5"
    >
      <div className="mb-1 flex items-center gap-2 font-medium text-amber-300">
        <TriangleAlert className="size-4" aria-hidden="true" />
        Sessões interrompidas encontradas
      </div>
      <p className="mb-3 text-xs text-neutral-400">
        O áudio continua salvo — clique em “Reprocessar” para completar a transcrição dos blocos pendentes.
      </p>

      <ul className="divide-y divide-neutral-800">
        {sessions.map((s) => (
          <li key={s.meeting_id} className="flex items-center justify-between gap-3 py-2.5">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium">{s.title}</p>
              <p className="mt-0.5 text-xs text-neutral-500">
                {formatDateTime(s.started_at ?? s.created_at)} · {s.chunks_transcribed}/{s.chunk_count} blocos
                transcritos
              </p>
            </div>
            <button
              onClick={() => resume(s.meeting_id)}
              disabled={running || busyId !== null}
              className="shrink-0 rounded-md border border-amber-700/60 px-3 py-1 text-xs text-amber-200 transition-colors hover:bg-amber-900/30 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busyId === s.meeting_id ? "Iniciando…" : "Reprocessar"}
            </button>
          </li>
        ))}
      </ul>

      {running && (
        <p className="mt-2 text-xs text-neutral-500">Há uma gravação ou reprocessamento em andamento — aguarde terminar.</p>
      )}
      {message && (
        <p role={message.ok ? "status" : "alert"} className={`mt-2 text-xs ${message.ok ? "text-emerald-400" : "text-red-400"}`}>
          {message.text}
        </p>
      )}
    </section>
  );
}

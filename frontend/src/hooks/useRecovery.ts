import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { MeetingSessionState } from "../types/api";

interface UseRecoveryResult {
  sessions: MeetingSessionState[];
  busyId: string | null;
  /** Resposta do backend ao último "Reprocessar" (sucesso ou recusa). */
  message: { ok: boolean; text: string } | null;
  resume: (meetingId: string) => Promise<void>;
}

/**
 * Sessões interrompidas (GET /api/recovery) e a ação "Reprocessar"
 * (POST /api/meetings/:id/resume). `running` vem do status do painel: a
 * lista é reconsultada quando uma gravação/reprocessamento começa ou
 * termina, porque é nesse momento que uma sessão acaba de virar
 * "interrompida" (ou de ser completada).
 *
 * Uma falha pontual de consulta mantém a última lista conhecida em vez de
 * virar erro na tela: a consulta se repete a cada `intervalMs`, e a perda de
 * conexão com o painel já é sinalizada pelo indicador "Sem conexão" do
 * Dashboard.
 */
export function useRecovery(running: boolean, intervalMs = 15000): UseRecoveryResult {
  const [sessions, setSessions] = useState<MeetingSessionState[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  async function refresh() {
    try {
      const data = await api.getRecovery();
      setSessions(data.sessions);
    } catch {
      // ver o comentário do hook: mantém a última lista conhecida
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, intervalMs]);

  async function resume(meetingId: string) {
    setBusyId(meetingId);
    setMessage(null);
    try {
      const result = await api.resumeMeeting(meetingId);
      setMessage({ ok: result.ok, text: result.message });
    } catch {
      setMessage({ ok: false, text: "Não foi possível falar com o painel." });
    } finally {
      setBusyId(null);
    }
  }

  return { sessions, busyId, message, resume };
}

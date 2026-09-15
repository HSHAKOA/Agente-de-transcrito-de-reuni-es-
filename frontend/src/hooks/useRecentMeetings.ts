import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { MeetingRecord } from "../types/api";

interface UseRecentMeetingsResult {
  meetings: MeetingRecord[] | null;
  total: number;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Consulta GET /api/meetings (as mais recentes) periodicamente -- o
 * histórico só muda quando uma reunião termina ou uma importação roda,
 * então um intervalo folgado é suficiente (evita reconsultar o SQLite
 * sem necessidade).
 */
export function useRecentMeetings(limit = 5, intervalMs = 20000): UseRecentMeetingsResult {
  const [meetings, setMeetings] = useState<MeetingRecord[] | null>(null);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const data = await api.getMeetings({ limit });
      setMeetings(data.meetings);
      setTotal(data.total);
      setError(null);
    } catch {
      setError("Não foi possível consultar o histórico de reuniões.");
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit, intervalMs]);

  return { meetings, total, error, refresh };
}

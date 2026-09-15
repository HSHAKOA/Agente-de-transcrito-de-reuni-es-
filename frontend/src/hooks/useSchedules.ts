import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { Schedule } from "../types/api";

interface UseSchedulesResult {
  schedules: Schedule[] | null;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Consulta GET /api/schedules periodicamente. Intervalo bem mais folgado
 * que useBackendStatus -- um agendamento não muda a cada 1.5s, só quando
 * o usuário cria/edita/cancela um, ou quando o motor do scheduler avança
 * de estado (a cada tick dele, ~20s no backend -- não faz sentido pedir
 * mais rápido que isso).
 */
export function useSchedules(intervalMs = 20000): UseSchedulesResult {
  const [schedules, setSchedules] = useState<Schedule[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const data = await api.getSchedules();
      setSchedules(data.schedules);
      setError(null);
    } catch {
      setError("Não foi possível consultar os agendamentos.");
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs]);

  return { schedules, error, refresh };
}

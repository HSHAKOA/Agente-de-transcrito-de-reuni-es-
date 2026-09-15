import { useState } from "react";
import { api } from "../services/api";

interface UseScheduleActionsResult {
  busyId: string | null;
  error: string | null;
  startNow: (id: string) => Promise<void>;
  cancel: (id: string) => Promise<void>;
  ignoreMissed: (id: string) => Promise<void>;
}

/** Ações mutáveis de agendamento (start-now/cancel/ignore-missed) --
 * centralizadas aqui pra não duplicar o padrão try/catch/loading em cada
 * botão da tela. `onDone` é chamado após qualquer ação bem-sucedida,
 * tipicamente pra disparar um `refresh()` de `useSchedules`. */
export function useScheduleActions(onDone: () => void): UseScheduleActionsResult {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(id: string, action: (id: string) => Promise<{ ok: boolean; message?: string }>) {
    setBusyId(id);
    setError(null);
    try {
      const result = await action(id);
      if (!result.ok) {
        setError(result.message ?? "A ação não pôde ser concluída.");
      } else {
        onDone();
      }
    } catch {
      setError("Não foi possível falar com o painel.");
    } finally {
      setBusyId(null);
    }
  }

  return {
    busyId,
    error,
    startNow: (id) => run(id, api.startScheduleNow),
    cancel: (id) => run(id, api.cancelSchedule),
    ignoreMissed: (id) => run(id, api.ignoreMissedSchedule),
  };
}

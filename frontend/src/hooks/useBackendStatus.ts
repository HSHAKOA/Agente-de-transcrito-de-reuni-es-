import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { StatusResponse } from "../types/api";

interface UseBackendStatusResult {
  status: StatusResponse | null;
  error: string | null;
}

/**
 * Consulta GET /api/status em intervalo fixo -- mesma cadencia de polling
 * que o painel HTML atual usa (1.5s por padrao), centralizada aqui em vez
 * de um setInterval solto espalhado pela pagina (ver missao, secao
 * "Estado da gravacao": nao depender de varios setInterval espalhados).
 */
export function useBackendStatus(intervalMs = 1500): UseBackendStatusResult {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function tick() {
      try {
        const data = await api.getStatus();
        if (!cancelled) {
          setStatus(data);
          setError(null);
        }
      } catch {
        if (!cancelled) setError("Sem conexão com o painel.");
      }
    }

    tick();
    const id = setInterval(tick, intervalMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [intervalMs]);

  return { status, error };
}

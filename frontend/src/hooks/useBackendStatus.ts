import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../services/api";
import type { StatusResponse } from "../types/api";

interface UseBackendStatusResult {
  status: StatusResponse | null;
  error: string | null;
  /** Forca uma leitura imediata de /api/status, fora do intervalo normal
   * de polling -- usado logo apos POST /api/start pra reduzir a janela
   * entre "backend confirmou" e "React sabe que confirmou" (ver App.tsx). */
  refresh: () => Promise<StatusResponse | null>;
}

/**
 * Consulta GET /api/status em intervalo fixo -- mesma cadencia de polling
 * que o painel HTML atual usa (1.5s por padrao), centralizada aqui em vez
 * de um setInterval solto espalhado pela pagina (ver missao, secao
 * "Estado da gravacao": nao depender de varios setInterval espalhados).
 *
 * `refresh()` e protegido por numero de sequencia: se duas chamadas
 * estiverem em voo ao mesmo tempo (uma do polling normal, outra forcada
 * por `refresh()`), so o resultado da MAIS RECENTE emitida e aplicado --
 * sem isso, uma resposta antiga (ex.: um poll que comecou ANTES de um
 * `POST /api/start`) podia chegar DEPOIS da confirmacao fresca e
 * sobrescrever `running: true` de volta pra `false` (a causa raiz do bug
 * de navegacao corrigido em App.tsx).
 */
export function useBackendStatus(intervalMs = 1500): UseBackendStatusResult {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cancelledRef = useRef(false);
  const seqRef = useRef(0);

  const refresh = useCallback(async () => {
    const mySeq = ++seqRef.current;
    try {
      const data = await api.getStatus();
      if (!cancelledRef.current && mySeq === seqRef.current) {
        setStatus(data);
        setError(null);
      }
      return data;
    } catch {
      if (!cancelledRef.current && mySeq === seqRef.current) setError("Sem conexão com o painel.");
      return null;
    }
  }, []);

  useEffect(() => {
    cancelledRef.current = false;
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => {
      cancelledRef.current = true;
      clearInterval(id);
    };
  }, [intervalMs, refresh]);

  return { status, error, refresh };
}

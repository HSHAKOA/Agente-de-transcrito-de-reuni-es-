import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { MeetingRecord } from "../types/api";

export interface HistoryFilters {
  q: string;
  status: string;
  dateFrom: string;
  dateTo: string;
}

type Loaded =
  | { key: string; meetings: MeetingRecord[]; total: number }
  | { key: string; error: string };

interface UseMeetingsHistoryResult {
  meetings: MeetingRecord[] | null;
  total: number;
  /** Há uma consulta em andamento (a lista anterior continua visível). */
  loading: boolean;
  error: string | null;
  reload: () => void;
}

/**
 * Consulta GET /api/meetings com filtros + paginação. Uma resposta só é
 * aplicada se ainda corresponder aos filtros atuais (uma consulta lenta
 * nunca sobrescreve uma mais nova), e enquanto a próxima carrega a lista
 * anterior continua na tela em vez de piscar vazia. `enabled=false` não
 * consulta (ex.: período invertido).
 */
export function useMeetingsHistory(
  filters: HistoryFilters,
  page: number,
  pageSize: number,
  enabled = true,
): UseMeetingsHistoryResult {
  const [reloadCount, setReloadCount] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);

  const key = JSON.stringify([filters, page, pageSize, reloadCount]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    api
      .getMeetings({
        q: filters.q,
        status: filters.status,
        dateFrom: filters.dateFrom,
        dateTo: filters.dateTo,
        limit: pageSize,
        offset: page * pageSize,
      })
      .then((data) => {
        if (!cancelled) setLoaded({ key, meetings: data.meetings, total: data.total });
      })
      .catch(() => {
        if (!cancelled) setLoaded({ key, error: "Não foi possível consultar o histórico de reuniões." });
      });
    return () => {
      cancelled = true;
    };
    // `key` já codifica filters/page/pageSize/reloadCount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled]);

  const fresh = loaded !== null && loaded.key === key;
  return {
    meetings: loaded && "meetings" in loaded ? loaded.meetings : null,
    total: loaded && "meetings" in loaded ? loaded.total : 0,
    loading: enabled && !fresh,
    error: fresh && "error" in loaded ? loaded.error : null,
    reload: () => setReloadCount((n) => n + 1),
  };
}

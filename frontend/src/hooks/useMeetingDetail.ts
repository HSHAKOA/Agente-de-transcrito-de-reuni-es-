import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { MeetingDetailResponse } from "../types/api";

interface UseMeetingDetailResult {
  detail: MeetingDetailResponse | null;
  loading: boolean;
  error: string | null;
}

/** Busca uma vez (sem polling -- uma reunião já encerrada não muda
 * sozinha) quando `meetingId` muda. */
export function useMeetingDetail(meetingId: string | null): UseMeetingDetailResult {
  const [detail, setDetail] = useState<MeetingDetailResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (meetingId === null) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .getMeetingDetail(meetingId)
      .then((data) => {
        if (cancelled) return;
        if (!data.ok) {
          setError(data.message ?? "Reunião não encontrada.");
        }
        setDetail(data);
      })
      .catch(() => {
        if (!cancelled) setError("Não foi possível consultar esta reunião.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [meetingId]);

  return { detail, loading, error };
}

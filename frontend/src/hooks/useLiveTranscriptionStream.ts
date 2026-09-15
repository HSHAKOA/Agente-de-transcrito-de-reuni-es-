import { api } from "../services/api";
import type { LiveTranscriptionSnapshot } from "../types/api";
import { useSSE } from "./useSSE";

/** `active`: só abre a conexão SSE enquanto uma gravação está de fato em
 * andamento (ver hooks/useSSE.ts). */
export function useLiveTranscriptionStream(active: boolean) {
  return useSSE<LiveTranscriptionSnapshot>(active ? api.transcriptionStreamUrl() : null);
}

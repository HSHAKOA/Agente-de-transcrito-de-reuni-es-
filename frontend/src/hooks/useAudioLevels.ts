import { api } from "../services/api";
import type { AudioLevelsSnapshot } from "../types/api";
import { useSSE } from "./useSSE";

/** `active`: só abre a conexão SSE enquanto uma gravação está de fato em
 * andamento (ver hooks/useSSE.ts). */
export function useAudioLevels(active: boolean) {
  return useSSE<AudioLevelsSnapshot>(active ? api.audioLevelsStreamUrl() : null);
}

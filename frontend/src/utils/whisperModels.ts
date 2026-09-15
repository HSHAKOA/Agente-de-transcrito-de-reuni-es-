import type { WhisperModel } from "../types/api";

/** Rótulos amigáveis pros presets de modelo Whisper -- compartilhado
 * entre `pages/NewMeeting.tsx` e `pages/ScheduleForm.tsx`. */
export const WHISPER_MODELS: { value: WhisperModel; label: string }[] = [
  { value: "tiny", label: "Rápido (tiny)" },
  { value: "base", label: "Base" },
  { value: "small", label: "Equilibrado (small)" },
  { value: "medium", label: "Preciso (medium)" },
  { value: "large-v3", label: "Máxima precisão (large-v3)" },
];

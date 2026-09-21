/** Rótulos em português dos status de uma reunião (`MeetingStatus` no
 * backend, ver `session.py`). Status desconhecido cai no valor cru. */
export const STATUS_LABELS: Record<string, string> = {
  created: "Criada",
  completed: "Concluída",
  recording: "Gravando",
  processing: "Processando",
  interrupted: "Interrompida",
  failed: "Falhou",
};

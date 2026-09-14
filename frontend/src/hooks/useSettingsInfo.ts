import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { SettingsInfo } from "../types/api";

interface UseSettingsInfoResult {
  settings: SettingsInfo | null;
  error: string | null;
  refresh: () => Promise<void>;
}

/**
 * Consulta GET /api/settings periodicamente -- espaço livre precisa ficar
 * atualizado durante uma reunião longa, não checado só uma vez no início
 * (mesma exigência já implementada no painel HTML atual).
 */
export function useSettingsInfo(intervalMs = 20000): UseSettingsInfoResult {
  const [settings, setSettings] = useState<SettingsInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const data = await api.getSettings();
      setSettings(data);
      setError(null);
    } catch {
      setError("Não foi possível consultar as configurações.");
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs]);

  return { settings, error, refresh };
}

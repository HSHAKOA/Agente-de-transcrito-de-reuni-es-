import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { AudioDevice } from "../types/api";
import { isAudioBackendError } from "../utils/isAudioBackendError";

interface UseAudioDevicesResult {
  inputs: AudioDevice[];
  outputs: AudioDevice[];
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

/** Busca uma vez (sem polling -- dispositivos não aparecem/somem tão
 * frequentemente a ponto de justificar consultar toda hora); `refresh` é
 * exposto pra um botão explícito de "atualizar lista". */
export function useAudioDevices(): UseAudioDevicesResult {
  const [inputs, setInputs] = useState<AudioDevice[]>([]);
  const [outputs, setOutputs] = useState<AudioDevice[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  async function refresh() {
    setLoading(true);
    try {
      const data = await api.getAudioDevices();
      if (isAudioBackendError(data)) {
        setError(data.error.message);
      } else {
        setInputs(data.inputs);
        setOutputs(data.outputs);
        setError(null);
      }
    } catch {
      setError("Não foi possível consultar os dispositivos de áudio.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { inputs, outputs, error, loading, refresh };
}

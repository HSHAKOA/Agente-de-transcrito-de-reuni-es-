import { useEffect, useState } from "react";

interface UseSSEResult<T> {
  data: T | null;
  connected: boolean;
}

/**
 * Consumo genérico de Server-Sent Events -- base de useAudioLevels e
 * useLiveTranscriptionStream (Fase F.11: hooks reutilizáveis, nunca um
 * `EventSource` solto espalhado pela página).
 *
 * `url === null` fecha/nunca abre a conexão (usado pelo chamador para só
 * escutar enquanto uma gravação está realmente ativa -- não faz sentido
 * manter uma conexão de vida longa aberta com nada acontecendo do outro
 * lado). Reconexão: o próprio `EventSource` do navegador já reconecta
 * sozinho por padrão após um erro; aqui só refletimos o status real da
 * conexão (`connected`), nunca fechamos manualmente fora do cleanup do
 * efeito (unmount ou troca de `url`).
 */
export function useSSE<T>(url: string | null): UseSSEResult<T> {
  const [data, setData] = useState<T | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    if (url === null) {
      setData(null);
      setConnected(false);
      return;
    }

    const source = new EventSource(url);
    source.onopen = () => setConnected(true);
    source.onmessage = (event) => {
      try {
        setData(JSON.parse(event.data) as T);
      } catch {
        // snapshot malformado nesse evento em particular -- mantém o
        // último snapshot válido em vez de quebrar a tela.
      }
    };
    source.onerror = () => setConnected(false);

    return () => {
      source.close();
      setConnected(false);
    };
  }, [url]);

  return { data, connected };
}

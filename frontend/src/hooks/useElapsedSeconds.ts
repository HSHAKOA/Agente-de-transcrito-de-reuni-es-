import { useEffect, useState } from "react";

/**
 * Segundos decorridos desde `startedAtEpoch` (epoch em segundos, como
 * `StatusResponse.started_at`), atualizado a cada segundo. Mesmo padrão
 * de `useCountdown`: o valor é sempre ancorado no timestamp que o
 * SERVIDOR gravou quando a gravação começou, nunca inventado -- só a
 * passagem de tempo local entre atualizações.
 */
export function useElapsedSeconds(startedAtEpoch: number | null): number | null {
  const [elapsed, setElapsed] = useState<number | null>(null);

  useEffect(() => {
    if (startedAtEpoch === null) {
      setElapsed(null);
      return;
    }
    const tick = () => setElapsed(Date.now() / 1000 - startedAtEpoch);
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startedAtEpoch]);

  return elapsed;
}

/** segundos -> "00:38:21" (HH:MM:SS), formato do cronômetro de gravação. */
export function formatElapsed(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

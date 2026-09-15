import { useEffect, useState } from "react";

/**
 * Contagem regressiva que tica localmente a cada segundo, mas nunca
 * "inventa" o valor: sempre ancorada no `seconds_until_next_run`
 * calculado pelo SERVIDOR (ver webui.py:_schedule_to_api_dict) no
 * momento em que ele chegou -- só a PASSAGEM DE TEMPO desde então é
 * local, nunca o valor em si.
 *
 * O efeito abaixo resincroniza o estado local sempre que `secondsAtFetch`
 * muda (um novo poll de useSchedules) -- um dos usos explicitamente
 * documentados pelo React para `useEffect` ("adjusting state when a prop
 * changes"); `Date.now()` só é lido dentro do efeito/callback do
 * `setInterval`, nunca durante o render em si.
 */
export function useCountdown(secondsAtFetch: number | null): number | null {
  const [remaining, setRemaining] = useState<number | null>(secondsAtFetch);

  useEffect(() => {
    if (secondsAtFetch === null) {
      setRemaining(null);
      return;
    }
    const startedAt = Date.now();
    setRemaining(secondsAtFetch);
    const id = setInterval(() => {
      setRemaining(Math.max(0, secondsAtFetch - (Date.now() - startedAt) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [secondsAtFetch]);

  return remaining;
}

export function formatCountdown(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours}h ${minutes}min`;
  if (minutes > 0) return `${minutes}min ${secs}s`;
  return `${secs}s`;
}

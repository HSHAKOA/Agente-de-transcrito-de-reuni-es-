import { useEffect, useState } from "react";

/** Devolve `value` só depois de `delayMs` sem mudar -- evita uma consulta ao
 * backend por tecla digitada na busca. Com `delayMs <= 0` acompanha `value`
 * no próximo tick (usado pelos testes). */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs]);

  return debounced;
}

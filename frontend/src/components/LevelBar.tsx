interface LevelBarProps {
  label: string;
  level: number | undefined;
  active: boolean | undefined;
}

/** Barra de nível RMS normalizado (0..1) -- mesmo valor já calculado pelo
 * backend (`audio/levels.py`), nunca um cálculo próprio no frontend nem
 * áudio bruto trafegando até aqui. */
export function LevelBar({ label, level, active }: LevelBarProps) {
  const pct = Math.round(Math.min(1, Math.max(0, level ?? 0)) * 100);
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs text-neutral-500">
        <span>{label}</span>
        {active === false && <span className="text-neutral-600">sem sinal</span>}
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-neutral-800">
        <div
          className={`h-full rounded-full transition-[width] duration-150 ${
            pct > 85 ? "bg-red-500" : "bg-emerald-500"
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

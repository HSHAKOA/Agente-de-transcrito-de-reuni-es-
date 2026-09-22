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
      {/* Sem transicao de proposito (ver MOTION.md, secao 5): este valor
          chega por SSE ~10x por segundo. Animar `width` forcaria um
          recalculo de layout por quadro numa maquina que ja divide a CPU
          com o Whisper, e a interpolacao faria a barra ATRASAR em relacao
          ao audio real -- um medidor atrasado e um medidor mentiroso.
          `aria-hidden`: o valor oscila rapido demais pra ser util num
          leitor de tela; quem precisa da informacao le "sem sinal" ao lado,
          que e texto de verdade. */}
      <div className="h-2 overflow-hidden rounded-full bg-neutral-800" aria-hidden="true">
        <div
          className={`h-full rounded-full ${pct > 85 ? "bg-red-500" : "bg-emerald-500"}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

/** segundos -> "1h12" / "38min", no mesmo estilo compacto do mockup da
 * missão (dashboard: "Projeto ERP 1h12"). */
export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "—";
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours > 0) return `${hours}h${String(minutes).padStart(2, "0")}`;
  return `${minutes}min`;
}

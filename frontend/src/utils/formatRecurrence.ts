import type { Recurrence } from "../types/api";

export const WEEKDAY_NAMES = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

/** Recurrence -> "Uma vez" / "Todo dia" / "Dias úteis" / "Toda Seg" /
 * "Seg, Qua, Sex" -- rótulo curto pra lista de agendamentos. */
export function formatRecurrence(recurrence: Recurrence): string {
  switch (recurrence.type) {
    case "once":
      return "Uma vez";
    case "daily":
      return "Todo dia";
    case "weekdays":
      return "Dias úteis";
    case "weekly":
      return recurrence.days[0] !== undefined ? `Toda ${WEEKDAY_NAMES[recurrence.days[0]]}` : "Semanal";
    case "custom_days":
      return recurrence.days.map((d) => WEEKDAY_NAMES[d]).join(", ");
    default:
      return recurrence.type;
  }
}

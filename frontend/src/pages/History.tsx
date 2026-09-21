import { ArrowLeft, Search } from "lucide-react";
import { useState } from "react";
import { Card } from "../components/Card";
import { MeetingRow } from "../components/MeetingRow";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { useMeetingsHistory } from "../hooks/useMeetingsHistory";
import { STATUS_LABELS } from "../utils/meetingStatus";

const PAGE_SIZE = 20;
const STATUS_OPTIONS = ["completed", "interrupted", "failed", "processing", "recording"] as const;

interface HistoryProps {
  onBack: () => void;
  onSelectMeeting: (id: string) => void;
  /** Espera (ms) entre a última tecla e a consulta. Só os testes mudam. */
  debounceMs?: number;
}

const fieldClass =
  "rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2 text-sm outline-none focus:border-neutral-600";

/**
 * Histórico completo: busca por título/transcrição, filtro por status e
 * por período, paginação. Todo o filtro é resolvido no backend
 * (`GET /api/meetings`) -- aqui só há estado de formulário. Mudar qualquer
 * filtro volta para a primeira página.
 */
export function History({ onBack, onSelectMeeting, debounceMs = 300 }: HistoryProps) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const debouncedQ = useDebouncedValue(q.trim(), debounceMs);

  const filters = { q: debouncedQ, status, dateFrom, dateTo };
  const filterKey = JSON.stringify(filters);

  // A página pertence aos filtros com que foi escolhida: ao mudar qualquer
  // filtro `filterKey` muda e a página volta a 0 sem um efeito de reset.
  const [pageState, setPageState] = useState({ filterKey, page: 0 });
  const page = pageState.filterKey === filterKey ? pageState.page : 0;

  const invertedRange = dateFrom !== "" && dateTo !== "" && dateFrom > dateTo;
  const { meetings, total, loading, error, reload } = useMeetingsHistory(filters, page, PAGE_SIZE, !invertedRange);

  const firstShown = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const lastShown = Math.min(total, (page + 1) * PAGE_SIZE);
  const hasFilters = debouncedQ !== "" || status !== "" || dateFrom !== "" || dateTo !== "";

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <button
        onClick={onBack}
        className="mb-4 flex items-center gap-1.5 text-sm text-neutral-500 transition-colors hover:text-neutral-300"
      >
        <ArrowLeft className="size-4" aria-hidden="true" />
        Voltar
      </button>
      <h1 className="mb-6 text-xl font-semibold tracking-tight">Histórico</h1>

      <Card>
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2">
          <Search className="size-4 shrink-0 text-neutral-500" aria-hidden="true" />
          <input
            type="search"
            aria-label="Pesquisar no histórico"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Pesquisar por título ou transcrição…"
            className="w-full bg-transparent text-sm outline-none placeholder:text-neutral-600"
          />
        </div>

        <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <label className="grid gap-1 text-xs text-neutral-500">
            Status
            <select value={status} onChange={(e) => setStatus(e.target.value)} className={fieldClass}>
              <option value="">Todos</option>
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABELS[s]}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs text-neutral-500">
            De
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} className={fieldClass} />
          </label>
          <label className="grid gap-1 text-xs text-neutral-500">
            Até
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} className={fieldClass} />
          </label>
        </div>

        {invertedRange && (
          <p role="alert" className="mb-3 text-sm text-amber-400">
            A data inicial é posterior à data final.
          </p>
        )}
        {error && (
          <div role="alert" className="mb-3 flex items-center justify-between gap-3 text-sm text-red-400">
            <span>{error}</span>
            <button onClick={reload} className="shrink-0 rounded-md border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 hover:bg-neutral-800">
              Tentar novamente
            </button>
          </div>
        )}

        <p aria-live="polite" className="mb-2 text-xs text-neutral-500">
          {meetings === null
            ? loading
              ? "Carregando…"
              : ""
            : total === 0
              ? ""
              : `Mostrando ${firstShown}–${lastShown} de ${total}`}
        </p>

        {meetings !== null && meetings.length === 0 && !loading && (
          <p className="text-sm text-neutral-500">
            {hasFilters ? "Nenhuma reunião encontrada com estes filtros." : "Nenhuma reunião no histórico ainda."}
          </p>
        )}

        {meetings !== null && meetings.length > 0 && (
          <ul aria-busy={loading} className={`-mx-1 ${loading ? "opacity-60" : ""}`}>
            {meetings.map((m) => (
              <li key={m.id}>
                <MeetingRow meeting={m} onSelect={onSelectMeeting} />
              </li>
            ))}
          </ul>
        )}

        {total > PAGE_SIZE && (
          <nav aria-label="Paginação do histórico" className="mt-4 flex items-center justify-between">
            <button
              onClick={() => setPageState({ filterKey, page: page - 1 })}
              disabled={page === 0}
              className="rounded-md border border-neutral-700 px-3 py-1 text-xs text-neutral-300 hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Anterior
            </button>
            <span className="text-xs text-neutral-500">
              Página {page + 1} de {Math.ceil(total / PAGE_SIZE)}
            </span>
            <button
              onClick={() => setPageState({ filterKey, page: page + 1 })}
              disabled={lastShown >= total}
              className="rounded-md border border-neutral-700 px-3 py-1 text-xs text-neutral-300 hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Próxima
            </button>
          </nav>
        )}
      </Card>
    </div>
  );
}

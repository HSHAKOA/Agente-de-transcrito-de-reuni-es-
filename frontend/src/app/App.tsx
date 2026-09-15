import { TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Dashboard } from "../pages/Dashboard";
import { MeetingDetail } from "../pages/MeetingDetail";

/**
 * A Fase F ganhou suas duas primeiras telas de produto de verdade
 * (Dashboard e Detalhe da Reunião -- ver `pages/`) -- não é mais só um
 * preview de conectividade. Navegação por `useState` simples de
 * propósito: só duas telas hoje, um router de verdade (`react-router`)
 * só se justifica quando Nova Reunião/Gravação/Agendamentos também
 * existirem (ver docs/PENDENCIAS.md).
 *
 * Ainda assim, esta interface é SOMENTE LEITURA (iniciar/parar gravação,
 * criar agendamento, escolher pasta) e não substitui o painel ativo
 * ainda: `index.html`/`webui.py` continuam sendo a interface real e
 * completa até a paridade funcional ser demonstrada (ver
 * docs/ROADMAP.md, Fase F).
 */
export function App() {
  const [selectedMeetingId, setSelectedMeetingId] = useState<string | null>(null);

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 antialiased">
      <div className="mx-auto max-w-2xl px-4 pt-4">
        <div className="flex items-center gap-2 rounded-lg border border-amber-800/60 bg-amber-950/40 px-4 py-3 text-sm text-amber-200">
          <TriangleAlert className="size-4 shrink-0" />
          <span>
            Prévia somente-leitura (Fase F) — para gravar/agendar, use{" "}
            <code className="rounded bg-black/30 px-1 py-0.5">http://127.0.0.1:8765</code>.
          </span>
        </div>
      </div>

      {selectedMeetingId ? (
        <MeetingDetail meetingId={selectedMeetingId} onBack={() => setSelectedMeetingId(null)} />
      ) : (
        <Dashboard onSelectMeeting={setSelectedMeetingId} />
      )}
    </div>
  );
}

import { CircleDot, FolderOpen, HardDrive, TriangleAlert } from "lucide-react";
import { useBackendStatus } from "../hooks/useBackendStatus";
import { useSettingsInfo } from "../hooks/useSettingsInfo";
import { formatBytes } from "../utils/formatBytes";

/**
 * Preview arquitetural da Fase F (migração para React) -- NÃO é a
 * interface ativa do produto. O painel real continua sendo `index.html` /
 * `webui.py`, servido em http://127.0.0.1:8765, até a migração completar
 * as etapas de paridade funcional descritas em docs/ARCHITECTURE.md.
 *
 * O que este componente prova de verdade, rodando contra o backend Python
 * real (não um mock): que o toolchain (Vite + React + TypeScript +
 * Tailwind), o proxy de desenvolvimento e o cliente HTTP tipado
 * (services/api.ts) conseguem ler o estado real do painel. Páginas de
 * produto de verdade (Dashboard, Nova reunião, Gravação, ...) só entram
 * quando a Fase F for alcançada na ordem do roadmap.
 */
export function App() {
  const { status, error: statusError } = useBackendStatus();
  const { settings, error: settingsError } = useSettingsInfo();

  const connected = status !== null && statusError === null;

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 antialiased">
      <div className="mx-auto max-w-2xl px-4 py-10">
        <div className="mb-6 flex items-center gap-2 rounded-lg border border-amber-800/60 bg-amber-950/40 px-4 py-3 text-sm text-amber-200">
          <TriangleAlert className="size-4 shrink-0" />
          <span>
            Preview arquitetural (Fase F) — a interface ativa continua em{" "}
            <code className="rounded bg-black/30 px-1 py-0.5">http://127.0.0.1:8765</code>.
          </span>
        </div>

        <h1 className="text-xl font-semibold tracking-tight">Meeting Transcriber</h1>
        <p className="mt-1 text-sm text-neutral-400">
          Conexão com o backend Python, lida em tempo real via a API existente.
        </p>

        <div className="mt-6 rounded-xl border border-neutral-800 bg-neutral-900 p-5">
          <div className="flex items-center gap-2">
            <CircleDot
              className={`size-4 ${connected ? "text-emerald-400" : "text-neutral-500"}`}
            />
            <span className="font-medium">{connected ? "Conectado ao painel" : "Sem conexão"}</span>
          </div>

          {statusError && <p className="mt-2 text-sm text-red-400">{statusError}</p>}

          {status && (
            <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <dt className="text-neutral-500">Gravando</dt>
              <dd>{status.running ? "Sim" : "Não"}</dd>
              {status.output_path && (
                <>
                  <dt className="text-neutral-500">Transcrição</dt>
                  <dd className="truncate font-mono text-xs">{status.output_path}</dd>
                </>
              )}
            </dl>
          )}
        </div>

        <div className="mt-4 rounded-xl border border-neutral-800 bg-neutral-900 p-5">
          <div className="flex items-center gap-2">
            <FolderOpen className="size-4 text-neutral-400" />
            <span className="font-medium">Local das reuniões</span>
          </div>
          {settingsError && <p className="mt-2 text-sm text-red-400">{settingsError}</p>}
          {settings && (
            <>
              <p className="mt-2 truncate font-mono text-xs text-neutral-300">
                {settings.meetings_root}
              </p>
              <div className="mt-2 flex items-center gap-2 text-sm text-neutral-400">
                <HardDrive className="size-4" />
                <span>Espaço livre: {formatBytes(settings.free_bytes)}</span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StatusResponse } from "../types/api";
import { App } from "./App";

vi.mock("../hooks/useAudioLevels", () => ({
  useAudioLevels: () => ({ data: null, connected: false }),
}));
vi.mock("../hooks/useLiveTranscriptionStream", () => ({
  useLiveTranscriptionStream: () => ({ data: null, connected: false }),
}));

const { api } = vi.hoisted(() => ({
  api: {
    getStatus: vi.fn(),
    getSettings: vi.fn(),
    getSchedules: vi.fn(),
    getMeetings: vi.fn(),
    getRecovery: vi.fn(),
    getAudioDevices: vi.fn(),
    getAudioConfig: vi.fn(),
    startMeeting: vi.fn(),
    stopMeeting: vi.fn(),
  },
}));
vi.mock("../services/api", () => ({ api }));

function baseStatus(overrides: Partial<StatusResponse> = {}): StatusResponse {
  return {
    running: false,
    stopping: false,
    output: null,
    chunk_seconds: null,
    meeting_dir: null,
    started_at: null,
    finished_at: null,
    exit_code: null,
    log: [],
    ...overrides,
  };
}

describe("App - ciclo de vida da gravacao (regressao P1-1/P1-5)", () => {
  let currentStatus: StatusResponse;

  beforeEach(() => {
    currentStatus = baseStatus();
    api.getStatus.mockImplementation(() => Promise.resolve(currentStatus));
    api.getSettings.mockResolvedValue({
      meetings_root: "C:\\Reunioes",
      folder_dialog_available: true,
      free_bytes: 10_000_000_000,
    });
    api.getSchedules.mockResolvedValue({ schedules: [] });
    api.getMeetings.mockResolvedValue({ meetings: [], total: 0, limit: 5, offset: 0 });
    api.getRecovery.mockResolvedValue({ sessions: [] });
    api.getAudioDevices.mockResolvedValue({
      inputs: [{ id: "mic-1", name: "Microfone", is_default: true }],
      outputs: [{ id: "spk-1", name: "Alto-falantes", is_default: true, loopback_supported: true }],
    });
    api.getAudioConfig.mockResolvedValue({
      capture_system: true,
      capture_microphone: false,
      system_device_id: null,
      microphone_device_id: null,
    });
  });

  it("idle -> new meeting -> starting -> recording -> stop -> stopping -> idle", async () => {
    const user = userEvent.setup();
    render(<App />);

    // idle: Dashboard visivel, sem gravacao ativa
    await waitFor(() => expect(screen.getByText("Meeting Intelligence")).toBeInTheDocument());
    expect(screen.queryByText(/Gravando agora/)).not.toBeInTheDocument();

    // -> new meeting
    await user.click(await screen.findByRole("button", { name: /Nova reunião/ }));
    expect(await screen.findByRole("heading", { name: "Nova reunião" })).toBeInTheDocument();

    // start: backend aceita, mas o PROXIMO poll de /api/status ainda nao
    // reflete running:true (currentStatus so muda DEPOIS do clique) --
    // exatamente a race condition que a auditoria encontrou.
    api.startMeeting.mockResolvedValue({ ok: true, message: "Gravacao iniciada." });
    await user.click(screen.getByRole("button", { name: "Iniciar reunião" }));

    // -> starting: nao pode voltar pro Dashboard so porque o status antigo
    // (running:false) ainda esta em memoria.
    expect(await screen.findByText("Iniciando gravação…")).toBeInTheDocument();
    expect(screen.queryByText("Meeting Intelligence")).not.toBeInTheDocument();

    // backend agora confirma -- App.tsx forcou um refresh() logo apos
    // onStarted(), entao isso deve chegar rapido, sem esperar o proximo
    // tick do polling de 1.5s.
    currentStatus = baseStatus({ running: true, started_at: Date.now() / 1000, meeting_dir: "C:\\Reunioes\\r1" });

    // -> recording (active): tela de Gravacao de verdade, com o botao de
    // parar. Sem uma segunda chamada forcada de refresh aqui, isso so
    // chega no proximo tick do polling normal (1.5s) -- timeout generoso
    // de proposito, nao um sinal de lentidao real do app.
    expect(await screen.findByText("GRAVANDO", {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Parar reunião" })).toBeInTheDocument();

    // -> stop: backend aceita o pedido, mas ainda esta finalizando
    api.stopMeeting.mockResolvedValue({ ok: true, message: "Parando..." });
    currentStatus = { ...currentStatus, stopping: true };
    await user.click(screen.getByRole("button", { name: "Parar reunião" }));

    // -> stopping: continua na tela de Gravacao, com feedback explicito --
    // nao pode voltar pro Dashboard so porque /api/stop respondeu 200.
    expect(await screen.findByText(/Finalizando reunião/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finalizando…" })).toBeDisabled();
    expect(screen.queryByText("Meeting Intelligence")).not.toBeInTheDocument();

    // backend termina de verdade o encerramento gracioso
    currentStatus = baseStatus({ running: false, stopping: false });

    // -> idle: de volta pro Dashboard sozinho, sem nenhuma navegacao manual
    await waitFor(() => expect(screen.getByText("Meeting Intelligence")).toBeInTheDocument(), { timeout: 4000 });
    expect(screen.queryByText("GRAVANDO")).not.toBeInTheDocument();
  }, 15000);
});

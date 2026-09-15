import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { NewMeeting } from "./NewMeeting";

const { api } = vi.hoisted(() => ({
  api: {
    getSettings: vi.fn(),
    getAudioDevices: vi.fn(),
    getAudioConfig: vi.fn(),
    startMeeting: vi.fn(),
    testAudio: vi.fn(),
    chooseFolder: vi.fn(),
    setMeetingsRootManually: vi.fn(),
  },
}));
vi.mock("../services/api", () => ({ api }));

function renderNewMeeting() {
  const onBack = vi.fn();
  const onStarted = vi.fn();
  render(<NewMeeting onBack={onBack} onStarted={onStarted} />);
  return { onBack, onStarted };
}

describe("NewMeeting", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getSettings.mockResolvedValue({
      meetings_root: "C:\\Reunioes",
      folder_dialog_available: true,
      free_bytes: 5_000_000_000,
    });
    api.getAudioDevices.mockResolvedValue({
      inputs: [{ id: "mic-1", name: "Microfone USB", is_default: true }],
      outputs: [{ id: "spk-1", name: "Alto-falantes", is_default: true, loopback_supported: true }],
    });
    api.getAudioConfig.mockResolvedValue({
      capture_system: true,
      capture_microphone: false,
      system_device_id: null,
      microphone_device_id: null,
    });
  });

  it("envia o payload correto (sistema ligado, microfone desligado por padrao)", async () => {
    api.startMeeting.mockResolvedValue({ ok: true, message: "Gravacao iniciada." });
    const { onStarted } = renderNewMeeting();

    await waitFor(() => expect(api.getAudioConfig).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: "Iniciar reunião" }));

    await waitFor(() => expect(api.startMeeting).toHaveBeenCalledTimes(1));
    const payload = api.startMeeting.mock.calls[0][0];
    expect(payload.capture_system).toBe(true);
    expect(payload.capture_microphone).toBe(false);
    expect(onStarted).toHaveBeenCalledTimes(1);
  });

  it("inclui o microfone no payload quando habilitado pelo usuario", async () => {
    api.startMeeting.mockResolvedValue({ ok: true, message: "Gravacao iniciada." });
    renderNewMeeting();

    await waitFor(() => expect(api.getAudioConfig).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("checkbox", { name: /Microfone/ }));
    await userEvent.click(screen.getByRole("button", { name: "Iniciar reunião" }));

    await waitFor(() => expect(api.startMeeting).toHaveBeenCalledTimes(1));
    const payload = api.startMeeting.mock.calls[0][0];
    expect(payload.capture_system).toBe(true);
    expect(payload.capture_microphone).toBe(true);
  });

  it("desabilita o botao de iniciar quando nenhuma fonte de audio esta selecionada", async () => {
    renderNewMeeting();
    await waitFor(() => expect(api.getAudioConfig).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("checkbox", { name: /Áudio do computador/ }));

    expect(screen.getByRole("button", { name: "Iniciar reunião" })).toBeDisabled();
    expect(api.startMeeting).not.toHaveBeenCalled();
  });

  it("mostra o erro do backend e nao navega quando o start falha", async () => {
    api.startMeeting.mockResolvedValue({ ok: false, message: "Selecione pelo menos uma fonte de áudio." });
    const { onStarted } = renderNewMeeting();

    await waitFor(() => expect(api.getAudioConfig).toHaveBeenCalled());
    await userEvent.click(screen.getByRole("button", { name: "Iniciar reunião" }));

    expect(await screen.findByText("Selecione pelo menos uma fonte de áudio.")).toBeInTheDocument();
    expect(onStarted).not.toHaveBeenCalled();
  });

  it("chama api.testAudio com as fontes atualmente selecionadas", async () => {
    api.testAudio.mockResolvedValue({
      ok: true,
      results: { system: { ok: true, code: null, message: "OK", level: 0.3 } },
    });
    renderNewMeeting();
    await waitFor(() => expect(api.getAudioConfig).toHaveBeenCalled());

    await userEvent.click(screen.getByRole("button", { name: "Testar áudio" }));

    await waitFor(() => expect(api.testAudio).toHaveBeenCalledTimes(1));
    expect(api.testAudio.mock.calls[0][0]).toMatchObject({ capture_system: true, capture_microphone: false });
    // resultado do teste renderiza um segundo "Áudio do computador" (o
    // rótulo do LevelBar, além do checkbox já existente) -- confirma que
    // o painel de resultado apareceu.
    await waitFor(() => expect(screen.getAllByText("Áudio do computador")).toHaveLength(2));
  });
});

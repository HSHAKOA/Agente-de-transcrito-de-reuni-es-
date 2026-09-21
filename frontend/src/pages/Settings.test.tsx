import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Settings } from "./Settings";

const { api } = vi.hoisted(() => ({
  api: {
    getSettings: vi.fn(),
    getAudioDevices: vi.fn(),
    getAudioConfig: vi.fn(),
    setAudioConfig: vi.fn(),
    chooseFolder: vi.fn(),
    setMeetingsRootManually: vi.fn(),
  },
}));
vi.mock("../services/api", () => ({ api }));

function settingsInfo(overrides = {}) {
  return { meetings_root: "C:\\Reunioes", folder_dialog_available: true, free_bytes: 5_000_000_000, ...overrides };
}

describe("Settings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getSettings.mockResolvedValue(settingsInfo());
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
    api.setAudioConfig.mockResolvedValue({});
  });

  it("mostra a pasta atual e o espaco livre", async () => {
    render(<Settings onBack={vi.fn()} />);

    expect(await screen.findByText("C:\\Reunioes")).toBeInTheDocument();
    expect(screen.getByText(/Espaço livre:/)).toBeInTheDocument();
  });

  it("Escolher pasta abre o dialogo nativo e recarrega a configuracao", async () => {
    api.chooseFolder.mockResolvedValue({ ...settingsInfo({ meetings_root: "D:\\Nova" }), ok: true, cancelled: false, message: "" });
    render(<Settings onBack={vi.fn()} />);
    await screen.findByText("C:\\Reunioes");
    api.getSettings.mockResolvedValue(settingsInfo({ meetings_root: "D:\\Nova" }));

    await userEvent.click(screen.getByRole("button", { name: "Escolher pasta" }));

    expect(api.chooseFolder).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("D:\\Nova")).toBeInTheDocument();
  });

  it("cancelar o dialogo nao mostra erro", async () => {
    api.chooseFolder.mockResolvedValue({ ...settingsInfo(), ok: false, cancelled: true, message: "Cancelado." });
    render(<Settings onBack={vi.fn()} />);
    await screen.findByText("C:\\Reunioes");

    await userEvent.click(screen.getByRole("button", { name: "Escolher pasta" }));

    await waitFor(() => expect(api.chooseFolder).toHaveBeenCalled());
    expect(screen.queryByText("Cancelado.")).not.toBeInTheDocument();
  });

  it("mostra a recusa do backend ao escolher uma pasta invalida", async () => {
    api.chooseFolder.mockResolvedValue({
      ...settingsInfo(),
      ok: false,
      cancelled: false,
      message: "A pasta escolhida nao e gravavel.",
    });
    render(<Settings onBack={vi.fn()} />);
    await screen.findByText("C:\\Reunioes");

    await userEvent.click(screen.getByRole("button", { name: "Escolher pasta" }));

    expect(await screen.findByText("A pasta escolhida nao e gravavel.")).toBeInTheDocument();
  });

  it("sem dialogo nativo, oferece o caminho manual e envia o texto sem espacos nas pontas", async () => {
    api.getSettings.mockResolvedValue(settingsInfo({ folder_dialog_available: false }));
    api.setMeetingsRootManually.mockResolvedValue({ ...settingsInfo({ folder_dialog_available: false }), ok: true, cancelled: false, message: "" });
    render(<Settings onBack={vi.fn()} />);

    expect(await screen.findByRole("button", { name: "Escolher pasta" })).toBeDisabled();
    await userEvent.type(screen.getByPlaceholderText("Caminho da pasta"), "  E:\\Aulas  ");
    await userEvent.click(screen.getByRole("button", { name: "Definir" }));

    expect(api.setMeetingsRootManually).toHaveBeenCalledWith("E:\\Aulas");
  });

  it("caminho manual vazio nunca chama o backend", async () => {
    api.getSettings.mockResolvedValue(settingsInfo({ folder_dialog_available: false }));
    render(<Settings onBack={vi.fn()} />);

    await userEvent.type(await screen.findByPlaceholderText("Caminho da pasta"), "   ");
    await userEvent.click(screen.getByRole("button", { name: "Definir" }));

    expect(api.setMeetingsRootManually).not.toHaveBeenCalled();
  });

  it("mostra a recusa do backend ao definir o caminho manual", async () => {
    api.getSettings.mockResolvedValue(settingsInfo({ folder_dialog_available: false }));
    api.setMeetingsRootManually.mockResolvedValue({
      ...settingsInfo(),
      ok: false,
      cancelled: false,
      message: "Caminho nao existe.",
    });
    render(<Settings onBack={vi.fn()} />);

    await userEvent.type(await screen.findByPlaceholderText("Caminho da pasta"), "Z:\\nada");
    await userEvent.click(screen.getByRole("button", { name: "Definir" }));

    expect(await screen.findByText("Caminho nao existe.")).toBeInTheDocument();
  });

  it("carrega as fontes padrao e salva as alteracoes como preferencia", async () => {
    render(<Settings onBack={vi.fn()} />);
    const system = await screen.findByRole("checkbox", { name: /Áudio do computador/ });
    const microphone = screen.getByRole("checkbox", { name: /Microfone/ });
    await waitFor(() => expect(system).toBeChecked());
    expect(microphone).not.toBeChecked();

    await userEvent.click(microphone);
    await userEvent.click(screen.getByRole("button", { name: "Salvar como padrão" }));

    expect(api.setAudioConfig).toHaveBeenCalledWith({
      capture_system: true,
      capture_microphone: true,
      system_device_id: null,
      microphone_device_id: null,
    });
    expect(await screen.findByText("Salvo.")).toBeInTheDocument();
  });

  it("mostra erro (e nao 'Salvo.') quando o painel nao responde ao salvar", async () => {
    api.setAudioConfig.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<Settings onBack={vi.fn()} />);
    await screen.findByRole("checkbox", { name: /Áudio do computador/ });

    await userEvent.click(screen.getByRole("button", { name: "Salvar como padrão" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível salvar as fontes de áudio padrão.");
    expect(screen.queryByText("Salvo.")).not.toBeInTheDocument();
  });

  it("mostra erro quando nao consegue carregar as fontes padrao", async () => {
    api.getAudioConfig.mockRejectedValue(new Error("HTTP 500"));
    render(<Settings onBack={vi.fn()} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível carregar as fontes de áudio padrão.");
  });

  it("Voltar chama o callback", async () => {
    const onBack = vi.fn();
    render(<Settings onBack={onBack} />);

    await userEvent.click(await screen.findByRole("button", { name: /Voltar/ }));

    expect(onBack).toHaveBeenCalled();
  });
});

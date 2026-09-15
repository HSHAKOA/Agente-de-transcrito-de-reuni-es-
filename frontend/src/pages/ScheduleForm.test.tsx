import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ScheduleForm } from "./ScheduleForm";

const { api } = vi.hoisted(() => ({
  api: {
    getSettings: vi.fn(),
    getAudioDevices: vi.fn(),
    createSchedule: vi.fn(),
    updateSchedule: vi.fn(),
    chooseFolder: vi.fn(),
  },
}));
vi.mock("../services/api", () => ({ api }));

function renderForm() {
  const onBack = vi.fn();
  const onSaved = vi.fn();
  render(<ScheduleForm onBack={onBack} onSaved={onSaved} />);
  return { onBack, onSaved };
}

describe("ScheduleForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getAudioDevices.mockResolvedValue({ inputs: [], outputs: [] });
    api.getSettings.mockResolvedValue({
      meetings_root: "C:\\Reunioes",
      folder_dialog_available: true,
      free_bytes: 5_000_000_000,
    });
  });

  async function fillMinimalValidForm() {
    await waitFor(() => expect(screen.getByPlaceholderText("Aula de Cálculo")).toBeInTheDocument());
    await userEvent.type(screen.getByPlaceholderText("Aula de Cálculo"), "Aula de Teste");
    await waitFor(() => expect(screen.getByText("C:\\Reunioes")).toBeInTheDocument());
  }

  it("recorrencia semanal com 1 dia selecionado envia type=weekly", async () => {
    api.createSchedule.mockResolvedValue({ ok: true, schedule: {} });
    renderForm();
    await fillMinimalValidForm();

    await userEvent.selectOptions(screen.getByDisplayValue("Não repetir"), "weekly");
    await userEvent.click(screen.getByRole("button", { name: "Seg" }));
    await userEvent.click(screen.getByRole("button", { name: "Agendar" }));

    await waitFor(() => expect(api.createSchedule).toHaveBeenCalledTimes(1));
    const payload = api.createSchedule.mock.calls[0][0];
    expect(payload.recurrence).toEqual({ type: "weekly", days: [0] });
  });

  it("selecionar um 2o dia enquanto 'Semanalmente' esta escolhido troca automaticamente pra custom_days", async () => {
    api.createSchedule.mockResolvedValue({ ok: true, schedule: {} });
    renderForm();
    await fillMinimalValidForm();

    await userEvent.selectOptions(screen.getByDisplayValue("Não repetir"), "weekly");
    await userEvent.click(screen.getByRole("button", { name: "Seg" }));
    await userEvent.click(screen.getByRole("button", { name: "Qua" }));

    // a propria UI ja reflete a troca (nao so o payload no submit)
    expect(screen.getByDisplayValue("Dias específicos")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Agendar" }));

    await waitFor(() => expect(api.createSchedule).toHaveBeenCalledTimes(1));
    const payload = api.createSchedule.mock.calls[0][0];
    expect(payload.recurrence.type).toBe("custom_days");
    expect(payload.recurrence.days).toEqual([0, 2]);
  });

  it("trocar manualmente de volta pra 'Semanalmente' com varios dias marcados mantem so o primeiro", async () => {
    api.createSchedule.mockResolvedValue({ ok: true, schedule: {} });
    renderForm();
    await fillMinimalValidForm();

    await userEvent.selectOptions(screen.getByDisplayValue("Não repetir"), "custom_days");
    await userEvent.click(screen.getByRole("button", { name: "Ter" }));
    await userEvent.click(screen.getByRole("button", { name: "Qui" }));
    await userEvent.selectOptions(screen.getByDisplayValue("Dias específicos"), "weekly");

    await userEvent.click(screen.getByRole("button", { name: "Agendar" }));

    await waitFor(() => expect(api.createSchedule).toHaveBeenCalledTimes(1));
    const payload = api.createSchedule.mock.calls[0][0];
    expect(payload.recurrence).toEqual({ type: "weekly", days: [1] });
  });

  it("recusa salvar sem titulo", async () => {
    renderForm();
    await waitFor(() => expect(screen.getByText("C:\\Reunioes")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: "Agendar" }));

    expect(await screen.findByText("Título é obrigatório.")).toBeInTheDocument();
    expect(api.createSchedule).not.toHaveBeenCalled();
  });

  it("recusa salvar sem pasta escolhida", async () => {
    api.getSettings.mockResolvedValue({ meetings_root: "", folder_dialog_available: true, free_bytes: null });
    renderForm();
    await waitFor(() => expect(screen.getByPlaceholderText("Aula de Cálculo")).toBeInTheDocument());
    await userEvent.type(screen.getByPlaceholderText("Aula de Cálculo"), "Aula de Teste");

    await userEvent.click(screen.getByRole("button", { name: "Agendar" }));

    expect(await screen.findByText("Escolha uma pasta para salvar a reunião.")).toBeInTheDocument();
    expect(api.createSchedule).not.toHaveBeenCalled();
  });
});

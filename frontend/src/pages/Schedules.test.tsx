import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Schedule, ScheduleStatus } from "../types/api";
import { Schedules } from "./Schedules";

const { api } = vi.hoisted(() => ({
  api: {
    getSchedules: vi.fn(),
    startScheduleNow: vi.fn(),
    cancelSchedule: vi.fn(),
    ignoreMissedSchedule: vi.fn(),
  },
}));
vi.mock("../services/api", () => ({ api }));

function schedule(id: string, title: string, status: ScheduleStatus, overrides: Partial<Schedule> = {}): Schedule {
  return {
    id,
    title,
    scheduled_date: "2026-09-21",
    start_time: "19:00",
    end_time: "20:40",
    timezone: "America/Sao_Paulo",
    meetings_root: "C:\\Reunioes",
    system_audio_enabled: true,
    system_device_id: null,
    microphone_enabled: false,
    microphone_device_id: null,
    transcription_model: "small",
    language: "pt",
    device: "cpu",
    chunk_seconds: 300,
    recurrence: { type: "weekly", days: [0] },
    status,
    created_at: "2026-09-14T10:00:00-03:00",
    updated_at: "2026-09-14T10:00:00-03:00",
    last_run_at: null,
    next_run_at: null,
    seconds_until_next_run: 3600,
    current_run: null,
    history: [],
    ...overrides,
  };
}

function renderSchedules(handlers = { onBack: vi.fn(), onNew: vi.fn(), onEdit: vi.fn() }) {
  render(<Schedules {...handlers} />);
  return handlers;
}

describe("Schedules", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getSchedules.mockResolvedValue({ schedules: [] });
  });

  it("mostra 'Carregando' e depois o estado vazio apontando o botao de criar", async () => {
    renderSchedules();

    expect(screen.getByText("Carregando…")).toBeInTheDocument();
    expect(await screen.findByText(/Nenhum agendamento ativo/)).toHaveTextContent("+ Novo agendamento");
  });

  it("lista titulo, status e recorrencia e esconde os cancelados", async () => {
    api.getSchedules.mockResolvedValue({
      schedules: [
        schedule("a", "Aula de Calculo", "scheduled"),
        schedule("b", "Reuniao antiga", "cancelled"),
      ],
    });
    renderSchedules();

    expect(await screen.findByText("Aula de Calculo")).toBeInTheDocument();
    expect(screen.getByText("Programada")).toBeInTheDocument();
    expect(screen.getByText("Toda Seg")).toBeInTheDocument();
    expect(screen.queryByText("Reuniao antiga")).not.toBeInTheDocument();
  });

  it("agendamento pendente oferece Iniciar agora, Editar e Cancelar", async () => {
    api.getSchedules.mockResolvedValue({ schedules: [schedule("a", "Aula", "scheduled")] });
    renderSchedules();

    await screen.findByText("Aula");
    expect(screen.getByRole("button", { name: "Iniciar agora" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Editar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ignorar" })).not.toBeInTheDocument();
  });

  it.each<ScheduleStatus>(["missed", "failed"])(
    "agendamento %s oferece Iniciar agora e Ignorar, nunca Editar/Cancelar",
    async (status) => {
      api.getSchedules.mockResolvedValue({
        schedules: [
          schedule("a", "Aula", status, {
            current_run: {
              occurrence_date: "2026-09-21",
              scheduled_start_at: "2026-09-21T22:00:00+00:00",
              scheduled_end_at: "2026-09-21T23:40:00+00:00",
              status,
              meeting_id: null,
              meeting_dir: null,
              actual_start_at: null,
              actual_end_at: null,
              ended_early: false,
              started_manually_early: false,
              error_message: "Esta gravacao estava programada para comecar as 19:00.",
              preflight: null,
            },
          }),
        ],
      });
      renderSchedules();

      await screen.findByText("Aula");
      expect(screen.getByText("Esta gravacao estava programada para comecar as 19:00.")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Iniciar agora" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Ignorar" })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Editar" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Cancelar" })).not.toBeInTheDocument();
    },
  );

  it("agendamento em andamento nao oferece nenhuma acao", async () => {
    api.getSchedules.mockResolvedValue({ schedules: [schedule("a", "Aula", "recording")] });
    renderSchedules();

    await screen.findByText("Aula");
    expect(screen.getByText("Gravando")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Iniciar agora|Editar|Cancelar|Ignorar/ })).not.toBeInTheDocument();
  });

  it("Cancelar chama o backend com o id e recarrega a lista", async () => {
    api.getSchedules.mockResolvedValue({ schedules: [schedule("sch_9", "Aula", "scheduled")] });
    api.cancelSchedule.mockResolvedValue({ ok: true, message: "Cancelado." });
    renderSchedules();

    await userEvent.click(await screen.findByRole("button", { name: "Cancelar" }));

    expect(api.cancelSchedule).toHaveBeenCalledWith("sch_9");
    await waitFor(() => expect(api.getSchedules).toHaveBeenCalledTimes(2)); // inicial + refresh apos a acao
  });

  it("Iniciar agora e Ignorar chamam o endpoint certo", async () => {
    api.getSchedules.mockResolvedValue({ schedules: [schedule("s1", "Pendente", "scheduled"), schedule("s2", "Perdida", "missed")] });
    api.startScheduleNow.mockResolvedValue({ ok: true, message: "ok" });
    api.ignoreMissedSchedule.mockResolvedValue({ ok: true, message: "ok" });
    renderSchedules();

    const startButtons = await screen.findAllByRole("button", { name: "Iniciar agora" });
    await userEvent.click(startButtons[0]);
    expect(api.startScheduleNow).toHaveBeenCalledWith("s1");

    await userEvent.click(screen.getByRole("button", { name: "Ignorar" }));
    expect(api.ignoreMissedSchedule).toHaveBeenCalledWith("s2");
  });

  it("mostra a recusa do backend em vez de recarregar como se tivesse dado certo", async () => {
    api.getSchedules.mockResolvedValue({ schedules: [schedule("a", "Aula", "scheduled")] });
    api.startScheduleNow.mockResolvedValue({ ok: false, message: "Ja existe uma gravacao em andamento." });
    renderSchedules();

    await userEvent.click(await screen.findByRole("button", { name: "Iniciar agora" }));

    expect(await screen.findByText("Ja existe uma gravacao em andamento.")).toBeInTheDocument();
    expect(api.getSchedules).toHaveBeenCalledTimes(1);
  });

  it("mostra erro quando nao consegue consultar os agendamentos", async () => {
    api.getSchedules.mockRejectedValue(new Error("HTTP 500"));
    renderSchedules();

    expect(await screen.findByText("Não foi possível consultar os agendamentos.")).toBeInTheDocument();
  });

  it("Voltar, Novo agendamento e Editar chamam os callbacks (Editar com o agendamento)", async () => {
    const target = schedule("a", "Aula", "scheduled");
    api.getSchedules.mockResolvedValue({ schedules: [target] });
    const handlers = renderSchedules();

    await userEvent.click(await screen.findByRole("button", { name: "Editar" }));
    expect(handlers.onEdit).toHaveBeenCalledWith(expect.objectContaining({ id: "a", title: "Aula" }));

    await userEvent.click(screen.getByRole("button", { name: "+ Novo agendamento" }));
    expect(handlers.onNew).toHaveBeenCalled();

    await userEvent.click(screen.getByRole("button", { name: /Voltar/ }));
    expect(handlers.onBack).toHaveBeenCalled();
  });
});

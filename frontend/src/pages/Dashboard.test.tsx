import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StatusResponse } from "../types/api";
import { Dashboard } from "./Dashboard";

const { api } = vi.hoisted(() => ({
  api: {
    getSettings: vi.fn(),
    getSchedules: vi.fn(),
    getMeetings: vi.fn(),
    getRecovery: vi.fn(),
    resumeMeeting: vi.fn(),
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

function renderDashboard(status: StatusResponse | null = baseStatus()) {
  return render(
    <Dashboard
      status={status}
      onSelectMeeting={vi.fn()}
      onViewRecording={vi.fn()}
      onViewSchedules={vi.fn()}
      onNewMeeting={vi.fn()}
      onViewSettings={vi.fn()}
    />,
  );
}

describe("Dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getSettings.mockResolvedValue({
      meetings_root: "C:\\Reunioes",
      folder_dialog_available: true,
      free_bytes: 5_000_000_000,
    });
    api.getRecovery.mockResolvedValue({ sessions: [] });
  });

  it("mostra estado vazio quando nao ha reunioes nem agendamentos", async () => {
    api.getSchedules.mockResolvedValue({ schedules: [] });
    api.getMeetings.mockResolvedValue({ meetings: [], total: 0, limit: 5, offset: 0 });
    renderDashboard();

    expect(await screen.findByText("Nenhuma gravação agendada.")).toBeInTheDocument();
    expect(
      await screen.findByText("Nenhuma reunião no histórico ainda — inicie uma gravação pelo painel ou importe reuniões existentes."),
    ).toBeInTheDocument();
  });

  it("lista as reunioes recentes retornadas pelo backend", async () => {
    api.getSchedules.mockResolvedValue({ schedules: [] });
    api.getMeetings.mockResolvedValue({
      meetings: [
        {
          id: "m1",
          title: "Reunião de Alinhamento",
          status: "completed",
          started_at: "2026-09-15T19:00:00+00:00",
          finished_at: "2026-09-15T20:00:00+00:00",
          duration_seconds: 3600,
          root_directory: null,
          meeting_directory: "C:\\Reunioes\\m1",
          language: "pt",
          model: "small",
          system_audio_enabled: true,
          system_device_id: null,
          system_device_name: null,
          microphone_enabled: false,
          microphone_device_id: null,
          microphone_device_name: null,
          deleted_at: null,
          created_at: "2026-09-15T19:00:00+00:00",
          updated_at: "2026-09-15T20:00:00+00:00",
        },
      ],
      total: 1,
      limit: 5,
      offset: 0,
    });
    renderDashboard();

    expect(await screen.findByText("Reunião de Alinhamento")).toBeInTheDocument();
    expect(screen.getByText("Concluída")).toBeInTheDocument();
    expect(screen.getByText("Reuniões recentes (1)")).toBeInTheDocument();
  });

  it("busca reunioes por texto via api.getMeetings", async () => {
    api.getSchedules.mockResolvedValue({ schedules: [] });
    api.getMeetings.mockResolvedValue({ meetings: [], total: 0, limit: 5, offset: 0 });
    renderDashboard();
    await screen.findByText("Nenhuma reunião no histórico ainda — inicie uma gravação pelo painel ou importe reuniões existentes.");

    api.getMeetings.mockResolvedValue({
      meetings: [
        {
          id: "m2",
          title: "Projeto ERP",
          status: "completed",
          started_at: "2026-09-14T19:00:00+00:00",
          finished_at: null,
          duration_seconds: 100,
          root_directory: null,
          meeting_directory: "C:\\Reunioes\\m2",
          language: "pt",
          model: "small",
          system_audio_enabled: true,
          system_device_id: null,
          system_device_name: null,
          microphone_enabled: false,
          microphone_device_id: null,
          microphone_device_name: null,
          deleted_at: null,
          created_at: "2026-09-14T19:00:00+00:00",
          updated_at: "2026-09-14T19:00:00+00:00",
        },
      ],
      total: 1,
      limit: 20,
      offset: 0,
    });

    await userEvent.type(screen.getByPlaceholderText("Pesquisar reuniões…"), "ERP");

    await waitFor(() => expect(api.getMeetings).toHaveBeenCalledWith({ q: "ERP", limit: 20 }));
    expect(await screen.findByText("Projeto ERP")).toBeInTheDocument();
    expect(screen.getByText("Resultados (1)")).toBeInTheDocument();
  });

  it("mostra o banner de gravacao ativa quando status.running e true", async () => {
    api.getSchedules.mockResolvedValue({ schedules: [] });
    api.getMeetings.mockResolvedValue({ meetings: [], total: 0, limit: 5, offset: 0 });
    renderDashboard(baseStatus({ running: true, output_path: "C:\\Reunioes\\r1\\transcript.md" }));

    expect(await screen.findByText(/Gravando agora/)).toBeInTheDocument();
  });

  it("mostra 'Finalizando' no banner quando a gravacao esta parando", async () => {
    api.getSchedules.mockResolvedValue({ schedules: [] });
    api.getMeetings.mockResolvedValue({ meetings: [], total: 0, limit: 5, offset: 0 });
    renderDashboard(baseStatus({ running: true, stopping: true }));

    expect(await screen.findByText("Finalizando gravação…")).toBeInTheDocument();
  });

  it("nao chama um reprocessamento de 'Gravando agora'", async () => {
    api.getSchedules.mockResolvedValue({ schedules: [] });
    api.getMeetings.mockResolvedValue({ meetings: [], total: 0, limit: 5, offset: 0 });
    renderDashboard(baseStatus({ running: true, mode: "resume" }));

    expect(await screen.findByText("Reprocessando uma sessão interrompida…")).toBeInTheDocument();
    expect(screen.queryByText(/Gravando agora/)).not.toBeInTheDocument();
  });

  it("mostra o banner de sessoes interrompidas quando o backend as lista", async () => {
    api.getSchedules.mockResolvedValue({ schedules: [] });
    api.getMeetings.mockResolvedValue({ meetings: [], total: 0, limit: 5, offset: 0 });
    api.getRecovery.mockResolvedValue({
      sessions: [
        {
          meeting_id: "aula-1",
          title: "Aula de Ingles",
          status: "interrupted",
          created_at: "2026-09-21T19:01:55-03:00",
          started_at: "2026-09-21T19:02:01-03:00",
          finished_at: null,
          chunk_count: 11,
          chunks_recorded: 11,
          chunks_transcribed: 9,
          duration: 0,
          model: "small",
          language: "pt",
          device: "cpu",
          error: null,
          chunks: [],
        },
      ],
    });
    renderDashboard();

    expect(await screen.findByText("Sessões interrompidas encontradas")).toBeInTheDocument();
    expect(screen.getByText("Aula de Ingles")).toBeInTheDocument();
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MeetingDetail } from "./MeetingDetail";

const { api } = vi.hoisted(() => ({
  api: {
    getMeetingDetail: vi.fn(),
    meetingExportUrl: vi.fn((id: string, format: string) => `/api/meetings/${id}/export?format=${format}`),
  },
}));
vi.mock("../services/api", () => ({ api }));

describe("MeetingDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.meetingExportUrl.mockImplementation((id: string, format: string) => `/api/meetings/${id}/export?format=${format}`);
  });

  it("mostra a transcricao completa com timecodes e rotulo de speaker", async () => {
    api.getMeetingDetail.mockResolvedValue({
      ok: true,
      meeting: {
        id: "m1",
        title: "Reunião Semanal",
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
        microphone_enabled: true,
        microphone_device_id: null,
        microphone_device_name: null,
        deleted_at: null,
        created_at: "2026-09-15T19:00:00+00:00",
        updated_at: "2026-09-15T20:00:00+00:00",
      },
      segments: [
        { id: 1, meeting_id: "m1", sequence: 0, start_seconds: 65, end_seconds: 70, speaker_label: "Você", text: "Bom dia a todos.", created_at: "" },
      ],
    });

    render(<MeetingDetail meetingId="m1" onBack={vi.fn()} />);

    expect(await screen.findByRole("heading", { name: "Reunião Semanal" })).toBeInTheDocument();
    expect(screen.getByText("Bom dia a todos.")).toBeInTheDocument();
    expect(screen.getByText("Você")).toBeInTheDocument();
    expect(screen.getByText("01:05")).toBeInTheDocument();
  });

  it("renderiza um link de download para cada um dos 5 formatos de exportacao", async () => {
    api.getMeetingDetail.mockResolvedValue({
      ok: true,
      meeting: {
        id: "m1", title: "Reunião", status: "completed", started_at: null, finished_at: null,
        duration_seconds: null, root_directory: null, meeting_directory: "x", language: null, model: null,
        system_audio_enabled: null, system_device_id: null, system_device_name: null,
        microphone_enabled: null, microphone_device_id: null, microphone_device_name: null,
        deleted_at: null, created_at: "", updated_at: "",
      },
      segments: [],
    });

    render(<MeetingDetail meetingId="m1" onBack={vi.fn()} />);
    await screen.findByRole("heading", { name: "Reunião" });

    for (const [label, format] of [
      ["Markdown", "markdown"],
      ["TXT", "txt"],
      ["JSON", "json"],
      ["SRT", "srt"],
      ["VTT", "vtt"],
    ]) {
      const link = screen.getByRole("link", { name: new RegExp(label) });
      expect(link).toHaveAttribute("href", `/api/meetings/m1/export?format=${format}`);
    }
  });

  it("mostra 'nao processado' para Resumo/Tarefas/Decisoes (Intelligence nao implementada)", async () => {
    api.getMeetingDetail.mockResolvedValue({
      ok: true,
      meeting: {
        id: "m1", title: "Reunião", status: "completed", started_at: null, finished_at: null,
        duration_seconds: null, root_directory: null, meeting_directory: "x", language: null, model: null,
        system_audio_enabled: null, system_device_id: null, system_device_name: null,
        microphone_enabled: null, microphone_device_id: null, microphone_device_name: null,
        deleted_at: null, created_at: "", updated_at: "",
      },
      segments: [],
    });

    render(<MeetingDetail meetingId="m1" onBack={vi.fn()} />);
    await screen.findByRole("heading", { name: "Reunião" });

    await userEvent.click(screen.getByRole("button", { name: "Resumo" }));
    expect(screen.getByText(/Recurso ainda não processado/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Tarefas" }));
    expect(screen.getByText(/Recurso ainda não processado/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Decisões" }));
    expect(screen.getByText(/Recurso ainda não processado/)).toBeInTheDocument();
  });

  it("mostra mensagem de erro quando a reuniao nao esta no indice", async () => {
    api.getMeetingDetail.mockResolvedValue({ ok: false, message: "Reuniao nao encontrada no indice. Rode a importacao primeiro." });

    render(<MeetingDetail meetingId="nao-existe" onBack={vi.fn()} />);

    expect(await screen.findByText("Reuniao nao encontrada no indice. Rode a importacao primeiro.")).toBeInTheDocument();
  });
});

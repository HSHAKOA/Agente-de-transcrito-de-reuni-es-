import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MeetingRecord } from "../types/api";
import { History } from "./History";

const { api } = vi.hoisted(() => ({ api: { getMeetings: vi.fn() } }));
vi.mock("../services/api", () => ({ api }));

function meeting(id: string, title: string, status: MeetingRecord["status"] = "completed"): MeetingRecord {
  return {
    id,
    title,
    status,
    started_at: "2026-09-15T19:00:00-03:00",
    finished_at: null,
    duration_seconds: 3600,
    root_directory: null,
    meeting_directory: `C:\\Reunioes\\${id}`,
    language: "pt",
    model: "small",
    system_audio_enabled: true,
    system_device_id: null,
    system_device_name: null,
    microphone_enabled: false,
    microphone_device_id: null,
    microphone_device_name: null,
    deleted_at: null,
    created_at: "2026-09-15T19:00:00-03:00",
    updated_at: "2026-09-15T19:00:00-03:00",
  };
}

function page(count: number, total: number, offset = 0) {
  return {
    meetings: Array.from({ length: count }, (_, i) => meeting(`m${offset + i}`, `Reunião ${offset + i}`)),
    total,
    limit: 20,
    offset,
  };
}

function renderHistory(onSelectMeeting = vi.fn(), onBack = vi.fn()) {
  render(<History onBack={onBack} onSelectMeeting={onSelectMeeting} debounceMs={0} />);
  return { onSelectMeeting, onBack };
}

const lastCall = () => api.getMeetings.mock.calls.at(-1)?.[0];

describe("History", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getMeetings.mockResolvedValue(page(20, 45));
  });

  it("carrega a primeira pagina e mostra o intervalo e o total", async () => {
    renderHistory();

    expect(await screen.findByText("Reunião 0")).toBeInTheDocument();
    expect(screen.getByText("Mostrando 1–20 de 45")).toBeInTheDocument();
    expect(screen.getByText("Página 1 de 3")).toBeInTheDocument();
    expect(lastCall()).toMatchObject({ limit: 20, offset: 0, q: "", status: "", dateFrom: "", dateTo: "" });
  });

  it("Proxima e Anterior pedem o offset certo e respeitam as bordas", async () => {
    renderHistory();
    await screen.findByText("Reunião 0");
    expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();

    api.getMeetings.mockResolvedValue(page(20, 45, 20));
    await userEvent.click(screen.getByRole("button", { name: "Próxima" }));
    expect(await screen.findByText("Reunião 20")).toBeInTheDocument();
    expect(lastCall()).toMatchObject({ offset: 20 });
    expect(screen.getByText("Mostrando 21–40 de 45")).toBeInTheDocument();

    api.getMeetings.mockResolvedValue(page(5, 45, 40));
    await userEvent.click(screen.getByRole("button", { name: "Próxima" }));
    expect(await screen.findByText("Mostrando 41–45 de 45")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Próxima" })).toBeDisabled();

    api.getMeetings.mockResolvedValue(page(20, 45, 20));
    await userEvent.click(screen.getByRole("button", { name: "Anterior" }));
    await waitFor(() => expect(lastCall()).toMatchObject({ offset: 20 }));
  });

  it("nao mostra paginacao quando cabe em uma pagina", async () => {
    api.getMeetings.mockResolvedValue(page(3, 3));
    renderHistory();

    await screen.findByText("Reunião 0");
    expect(screen.queryByRole("navigation", { name: "Paginação do histórico" })).not.toBeInTheDocument();
  });

  it("mudar um filtro volta para a primeira pagina e envia o filtro", async () => {
    renderHistory();
    await screen.findByText("Reunião 0");
    api.getMeetings.mockResolvedValue(page(20, 45, 20));
    await userEvent.click(screen.getByRole("button", { name: "Próxima" }));
    await screen.findByText("Reunião 20");

    api.getMeetings.mockResolvedValue(page(2, 2));
    await userEvent.selectOptions(screen.getByLabelText("Status"), "failed");

    await waitFor(() => expect(lastCall()).toMatchObject({ status: "failed", offset: 0 }));
    expect(await screen.findByText("Mostrando 1–2 de 2")).toBeInTheDocument();
  });

  it("envia a busca e o periodo nos parametros corretos", async () => {
    renderHistory();
    await screen.findByText("Reunião 0");

    await userEvent.type(screen.getByLabelText("Pesquisar no histórico"), "ERP");
    await waitFor(() => expect(lastCall()).toMatchObject({ q: "ERP", offset: 0 }));

    await userEvent.type(screen.getByLabelText("De"), "2026-09-01");
    await userEvent.type(screen.getByLabelText("Até"), "2026-09-30");
    await waitFor(() => expect(lastCall()).toMatchObject({ q: "ERP", dateFrom: "2026-09-01", dateTo: "2026-09-30" }));
  });

  it("periodo invertido avisa e nao consulta o backend", async () => {
    renderHistory();
    await screen.findByText("Reunião 0");
    const before = api.getMeetings.mock.calls.length;

    await userEvent.type(screen.getByLabelText("De"), "2026-09-30");
    await userEvent.type(screen.getByLabelText("Até"), "2026-09-01");

    expect(await screen.findByRole("alert")).toHaveTextContent("A data inicial é posterior à data final.");
    // digitar "De" sozinho ainda consultou; o par invertido nao
    const callsAfterFrom = api.getMeetings.mock.calls.filter((c) => c[0].dateFrom === "2026-09-30" && c[0].dateTo === "2026-09-01");
    expect(callsAfterFrom).toHaveLength(0);
    expect(api.getMeetings.mock.calls.length).toBeGreaterThanOrEqual(before);
  });

  it("estado vazio depende de haver filtros", async () => {
    api.getMeetings.mockResolvedValue({ meetings: [], total: 0, limit: 20, offset: 0 });
    renderHistory();
    expect(await screen.findByText("Nenhuma reunião no histórico ainda.")).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Status"), "failed");
    expect(await screen.findByText("Nenhuma reunião encontrada com estes filtros.")).toBeInTheDocument();
  });

  it("mostra o erro e Tentar novamente refaz a consulta", async () => {
    api.getMeetings.mockRejectedValueOnce(new Error("HTTP 500"));
    renderHistory();

    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível consultar o histórico de reuniões.");

    api.getMeetings.mockResolvedValue(page(2, 2));
    await userEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));

    expect(await screen.findByText("Reunião 0")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("uma resposta lenta e antiga nunca sobrescreve a mais nova", async () => {
    let resolveSlow: (value: unknown) => void = () => {};
    api.getMeetings.mockReturnValueOnce(new Promise((resolve) => (resolveSlow = resolve)));
    renderHistory();

    // segunda consulta (filtro novo) responde primeiro
    api.getMeetings.mockResolvedValue({ meetings: [meeting("novo", "Resposta nova")], total: 1, limit: 20, offset: 0 });
    await userEvent.selectOptions(screen.getByLabelText("Status"), "completed");
    expect(await screen.findByText("Resposta nova")).toBeInTheDocument();

    // a primeira chega atrasada -- precisa ser descartada
    resolveSlow({ meetings: [meeting("velho", "Resposta velha")], total: 1, limit: 20, offset: 0 });
    await new Promise((r) => setTimeout(r, 20));

    expect(screen.getByText("Resposta nova")).toBeInTheDocument();
    expect(screen.queryByText("Resposta velha")).not.toBeInTheDocument();
  });

  it("abrir uma reuniao e voltar chamam os callbacks certos", async () => {
    const { onSelectMeeting, onBack } = renderHistory();

    await userEvent.click(await screen.findByText("Reunião 3"));
    expect(onSelectMeeting).toHaveBeenCalledWith("m3");

    await userEvent.click(screen.getByRole("button", { name: /Voltar/ }));
    expect(onBack).toHaveBeenCalled();
  });
});

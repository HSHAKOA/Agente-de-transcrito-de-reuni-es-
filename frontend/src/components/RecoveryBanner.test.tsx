import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MeetingSessionState } from "../types/api";
import { RecoveryBanner } from "./RecoveryBanner";

const { api } = vi.hoisted(() => ({
  api: {
    getRecovery: vi.fn(),
    resumeMeeting: vi.fn(),
  },
}));
vi.mock("../services/api", () => ({ api }));

function session(overrides: Partial<MeetingSessionState> = {}): MeetingSessionState {
  return {
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
    ...overrides,
  };
}

describe("RecoveryBanner", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getRecovery.mockResolvedValue({ sessions: [] });
  });

  it("nao renderiza nada quando nao ha sessoes interrompidas", async () => {
    const { container } = render(<RecoveryBanner running={false} />);

    await waitFor(() => expect(api.getRecovery).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("lista cada sessao com o progresso de blocos transcritos", async () => {
    api.getRecovery.mockResolvedValue({ sessions: [session()] });
    render(<RecoveryBanner running={false} />);

    expect(await screen.findByText("Sessões interrompidas encontradas")).toBeInTheDocument();
    expect(screen.getByText("Aula de Ingles")).toBeInTheDocument();
    expect(screen.getByText(/9\/11 blocos transcritos/)).toBeInTheDocument();
  });

  it("Reprocessar chama o backend com o id da sessao e mostra a resposta", async () => {
    api.getRecovery.mockResolvedValue({ sessions: [session()] });
    api.resumeMeeting.mockResolvedValue({ ok: true, message: "Reprocessamento iniciado." });
    render(<RecoveryBanner running={false} />);

    await userEvent.click(await screen.findByRole("button", { name: "Reprocessar" }));

    expect(api.resumeMeeting).toHaveBeenCalledWith("aula-1");
    expect(await screen.findByRole("status")).toHaveTextContent("Reprocessamento iniciado.");
  });

  it("mostra como alerta a recusa do backend (ex.: PID ainda ativo)", async () => {
    api.getRecovery.mockResolvedValue({ sessions: [session()] });
    api.resumeMeeting.mockResolvedValue({ ok: false, message: "Um processo com PID 4242 ainda parece estar em execucao." });
    render(<RecoveryBanner running={false} />);

    await userEvent.click(await screen.findByRole("button", { name: "Reprocessar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("PID 4242");
  });

  it("mostra erro generico se o painel nao responde", async () => {
    api.getRecovery.mockResolvedValue({ sessions: [session()] });
    api.resumeMeeting.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<RecoveryBanner running={false} />);

    await userEvent.click(await screen.findByRole("button", { name: "Reprocessar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Não foi possível falar com o painel.");
  });

  it("desabilita Reprocessar enquanto ha uma gravacao ou reprocessamento rodando", async () => {
    api.getRecovery.mockResolvedValue({ sessions: [session()] });
    render(<RecoveryBanner running={true} />);

    expect(await screen.findByRole("button", { name: "Reprocessar" })).toBeDisabled();
    expect(screen.getByText(/aguarde terminar/)).toBeInTheDocument();
  });

  it("uma falha pontual da consulta nao derruba o banner nem levanta erro", async () => {
    api.getRecovery.mockRejectedValue(new TypeError("Failed to fetch"));
    const { container } = render(<RecoveryBanner running={false} />);

    await waitFor(() => expect(api.getRecovery).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});

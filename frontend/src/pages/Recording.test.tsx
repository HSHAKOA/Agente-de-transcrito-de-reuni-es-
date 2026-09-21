import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LiveTranscriptionSnapshot, StatusResponse } from "../types/api";
import { Recording } from "./Recording";

const { api, streams } = vi.hoisted(() => ({
  api: { stopMeeting: vi.fn() },
  streams: { levels: null as unknown, live: null as unknown },
}));
vi.mock("../services/api", () => ({ api }));
vi.mock("../hooks/useAudioLevels", () => ({
  useAudioLevels: () => ({ data: streams.levels, connected: true }),
}));
vi.mock("../hooks/useLiveTranscriptionStream", () => ({
  useLiveTranscriptionStream: () => ({ data: streams.live, connected: true }),
}));

function runningStatus(overrides: Partial<StatusResponse> = {}): StatusResponse {
  return {
    running: true,
    stopping: false,
    mode: "record",
    output: "C:\\Reunioes\\2026-09-21_1901_Aula\\transcript.md",
    chunk_seconds: 300,
    meeting_dir: "C:\\Reunioes\\2026-09-21_1901_Aula",
    started_at: Date.now() / 1000 - 3725, // ~01:02:05 atras
    finished_at: null,
    exit_code: null,
    log: [],
    ...overrides,
  };
}

function snapshot(overrides: Partial<LiveTranscriptionSnapshot> = {}): LiveTranscriptionSnapshot {
  return {
    segments: [],
    backlog: { recorded_seconds: 600, transcribed_seconds: 540, pending_seconds: 60, status: "PROCESSING" },
    avg_latency_seconds: 2.1,
    model_load_seconds: 3,
    ...overrides,
  };
}

describe("Recording", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    streams.levels = null;
    streams.live = null;
  });

  it("mostra o nome da pasta da reuniao e o cronometro ancorado no inicio do servidor", () => {
    render(<Recording status={runningStatus()} />);

    expect(screen.getByRole("heading", { name: "2026-09-21_1901_Aula" })).toBeInTheDocument();
    expect(screen.getByText(/^01:02:0\d$/)).toBeInTheDocument();
    expect(screen.getByText("GRAVANDO")).toBeInTheDocument();
  });

  it("usa um titulo generico e cronometro vazio quando o servidor ainda nao informou o inicio", () => {
    render(<Recording status={runningStatus({ meeting_dir: null, started_at: null })} />);

    expect(screen.getByRole("heading", { name: "Reunião em andamento" })).toBeInTheDocument();
    expect(screen.getByText("--:--:--")).toBeInTheDocument();
  });

  it("mostra 'sem sinal' na fonte de audio inativa", () => {
    streams.levels = {
      system: { level: 0.4, active: true, updated_at: 1 },
      microphone: { level: 0, active: false, updated_at: 1 },
    };
    render(<Recording status={runningStatus()} />);

    expect(screen.getByText("Áudio do computador")).toBeInTheDocument();
    expect(screen.getByText("Microfone")).toBeInTheDocument();
    expect(screen.getAllByText("sem sinal")).toHaveLength(1);
  });

  it("aguarda o primeiro trecho e depois lista os segmentos com o rotulo da fonte", () => {
    const { rerender } = render(<Recording status={runningStatus()} />);
    expect(screen.getByText("Aguardando o primeiro trecho transcrito…")).toBeInTheDocument();

    streams.live = snapshot({
      segments: [
        { start_seconds: 65, end_seconds: 70, text: "Bom dia, pessoal.", state: "committed", source: "mixed" },
        { start_seconds: 72, end_seconds: 75, text: "trecho ainda provisorio", state: "provisional", source: "system" },
      ],
    });
    rerender(<Recording status={runningStatus()} />);

    expect(screen.getByText("Bom dia, pessoal.")).toBeInTheDocument();
    expect(screen.getByText("01:05")).toBeInTheDocument();
    expect(screen.getByText("Reunião")).toBeInTheDocument();
    // provisorio fica esmaecido; o definitivo nao
    expect(screen.getByText("trecho ainda provisorio").parentElement).toHaveClass("opacity-60");
    expect(screen.getByText("Bom dia, pessoal.").parentElement).not.toHaveClass("opacity-60");
  });

  it("destaca o pendente quando a transcricao esta ATRASADA (BEHIND)", () => {
    streams.live = snapshot({
      backlog: { recorded_seconds: 1200, transcribed_seconds: 300, pending_seconds: 900, status: "BEHIND" },
    });
    render(<Recording status={runningStatus()} />);

    expect(screen.getByText("00:20:00")).toBeInTheDocument(); // gravado
    expect(screen.getByText("00:05:00")).toBeInTheDocument(); // transcrito
    expect(screen.getByText("00:15:00")).toHaveClass("text-amber-400"); // pendente
  });

  it("Parar chama o backend uma unica vez e trava o duplo clique", async () => {
    let finishStop: (value: unknown) => void = () => {};
    api.stopMeeting.mockReturnValue(new Promise((resolve) => (finishStop = resolve)));
    render(<Recording status={runningStatus()} />);

    const button = screen.getByRole("button", { name: "Parar reunião" });
    await userEvent.click(button);

    expect(await screen.findByRole("button", { name: "Finalizando…" })).toBeDisabled();
    expect(screen.getByText(/Finalizando reunião\.\.\./)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Finalizando…" }));
    expect(api.stopMeeting).toHaveBeenCalledTimes(1);

    finishStop({ ok: true, message: "Parando." });
  });

  it("se o backend recusar parar, mostra a mensagem e libera o botao de novo", async () => {
    api.stopMeeting.mockResolvedValue({ ok: false, message: "Ja estamos finalizando esta gravacao, aguarde." });
    render(<Recording status={runningStatus()} />);

    await userEvent.click(screen.getByRole("button", { name: "Parar reunião" }));

    expect(await screen.findByText("Ja estamos finalizando esta gravacao, aguarde.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Parar reunião" })).toBeEnabled();
  });

  it("se o painel nao responder, mostra erro generico e libera o botao", async () => {
    api.stopMeeting.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<Recording status={runningStatus()} />);

    await userEvent.click(screen.getByRole("button", { name: "Parar reunião" }));

    expect(await screen.findByText("Não foi possível parar a gravação.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Parar reunião" })).toBeEnabled();
  });

  it("um reprocessamento nao mostra 'GRAVANDO' nem medidores, so o cronometro e o botao de parar", () => {
    streams.levels = { system: { level: 0.4, active: true, updated_at: 1 } };
    streams.live = snapshot();
    render(<Recording status={runningStatus({ mode: "resume" })} />);

    expect(screen.getByText("REPROCESSANDO")).toBeInTheDocument();
    expect(screen.queryByText("GRAVANDO")).not.toBeInTheDocument();
    expect(screen.getByText(/Nenhum áudio novo está sendo gravado/)).toBeInTheDocument();
    expect(screen.queryByText("Áudio do computador")).not.toBeInTheDocument();
    expect(screen.queryByText("Transcrição ao vivo")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Parar reprocessamento" })).toBeEnabled();
  });

  it("parar um reprocessamento usa a mesma trava de duplo clique e mensagem propria", async () => {
    api.stopMeeting.mockResolvedValue({ ok: true, message: "Parando." });
    render(<Recording status={runningStatus({ mode: "resume" })} />);

    await userEvent.click(screen.getByRole("button", { name: "Parar reprocessamento" }));

    expect(await screen.findByText(/Finalizando reprocessamento/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finalizando…" })).toBeDisabled();
    expect(api.stopMeeting).toHaveBeenCalledTimes(1);
  });

  it("status.stopping do backend mostra 'Finalizando' e desabilita Parar sem nenhum clique", () => {
    render(<Recording status={runningStatus({ stopping: true })} />);

    expect(screen.getByText(/Finalizando reunião\.\.\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Finalizando…" })).toBeDisabled();
    expect(api.stopMeeting).not.toHaveBeenCalled();
  });
});

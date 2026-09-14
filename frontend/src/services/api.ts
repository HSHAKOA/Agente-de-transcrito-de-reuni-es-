/**
 * Cliente HTTP tipado para o painel Python (webui.py). Toda chamada usa
 * caminho relativo ("/api/...") de proposito: em desenvolvimento o Vite
 * (ver vite.config.ts) faz proxy dessas chamadas pro backend real em
 * 127.0.0.1:8765; em producao, o proprio Python serve o build do React a
 * partir da mesma origem, entao "/api/..." continua correto sem mudar
 * nada aqui.
 *
 * Regra da migracao: este arquivo so busca dados e envia intencao do
 * usuario. Nenhuma decisao de dominio (pasta e segura? CUDA existe?
 * sessao pode ser recuperada?) acontece aqui -- isso e sempre resposta do
 * backend.
 */

import type {
  ActionResult,
  FolderActionResult,
  RecoveryResponse,
  SettingsInfo,
  StartMeetingRequest,
  StatusResponse,
} from "../types/api";

class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) {
    throw new ApiError(`Falha ao consultar ${path} (HTTP ${res.status}).`, res.status);
  }
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = (await res.json()) as T;
  // O backend usa 200/409/413/etc. de forma consistente com {ok, message}
  // no corpo -- nao tratamos !res.ok como excecao aqui, o chamador decide
  // com base em `data.ok` (ver ActionResult/FolderActionResult).
  return data;
}

export const api = {
  getStatus: () => getJson<StatusResponse>("/api/status"),
  getSettings: () => getJson<SettingsInfo>("/api/settings"),
  getRecovery: () => getJson<RecoveryResponse>("/api/recovery"),

  startMeeting: (body: StartMeetingRequest) => postJson<ActionResult>("/api/start", body),
  stopMeeting: () => postJson<ActionResult>("/api/stop"),
  resumeMeeting: (meetingId: string) =>
    postJson<ActionResult>(`/api/meetings/${encodeURIComponent(meetingId)}/resume`),

  chooseFolder: () => postJson<FolderActionResult>("/api/choose-folder"),
  setMeetingsRootManually: (path: string) =>
    postJson<FolderActionResult>("/api/settings/meetings-root", { path }),
  openFolder: (path: string) => postJson<ActionResult>("/api/open-folder", { path }),
};

export { ApiError };

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
  AudioConfig,
  AudioDevicesResponse,
  AudioTestResult,
  CreateScheduleRequest,
  ExportFormat,
  FolderActionResult,
  ImportMeetingsResult,
  LiveTranscriptionSnapshot,
  MeetingDetailResponse,
  MeetingsListResponse,
  RecoveryResponse,
  ScheduleActionResult,
  SchedulesResponse,
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

  // Fase C: dispositivos de audio
  getAudioDevices: () => getJson<AudioDevicesResponse>("/api/audio/devices"),
  getAudioConfig: () => getJson<AudioConfig>("/api/audio/config"),
  setAudioConfig: (body: Partial<AudioConfig>) => postJson<AudioConfig>("/api/audio/config", body),
  testAudio: (body?: Partial<AudioConfig>) => postJson<AudioTestResult>("/api/audio/test", body),
  getAudioLevels: () => getJson<Record<string, unknown>>("/api/audio/levels"),
  /** URL pronta pra abrir com `new EventSource(...)` -- nunca chamada via fetch. */
  audioLevelsStreamUrl: () => "/api/audio/levels/stream",

  // Fase D: transcricao ao vivo
  getLiveTranscription: () => getJson<LiveTranscriptionSnapshot>("/api/transcription/live"),
  transcriptionStreamUrl: () => "/api/transcription/stream",

  // Fase C.1: agendamento de gravacoes
  getSchedules: () => getJson<SchedulesResponse>("/api/schedules"),
  createSchedule: (body: CreateScheduleRequest) => postJson<ScheduleActionResult>("/api/schedules", body),
  updateSchedule: (id: string, body: CreateScheduleRequest) =>
    postJson<ScheduleActionResult>(`/api/schedules/${encodeURIComponent(id)}`, body),
  cancelSchedule: (id: string) => postJson<ScheduleActionResult>(`/api/schedules/${encodeURIComponent(id)}/cancel`),
  startScheduleNow: (id: string) =>
    postJson<ActionResult>(`/api/schedules/${encodeURIComponent(id)}/start-now`),
  ignoreMissedSchedule: (id: string) =>
    postJson<ActionResult>(`/api/schedules/${encodeURIComponent(id)}/ignore-missed`),

  // Fase E: historico e busca
  /** `dateFrom`/`dateTo`: dias `AAAA-MM-DD`, inclusivos (o backend responde 400 se malformados). */
  getMeetings: (params?: {
    limit?: number;
    offset?: number;
    status?: string;
    q?: string;
    dateFrom?: string;
    dateTo?: string;
  }) => {
    const search = new URLSearchParams();
    if (params?.limit !== undefined) search.set("limit", String(params.limit));
    if (params?.offset !== undefined) search.set("offset", String(params.offset));
    if (params?.status) search.set("status", params.status);
    if (params?.q) search.set("q", params.q);
    if (params?.dateFrom) search.set("date_from", params.dateFrom);
    if (params?.dateTo) search.set("date_to", params.dateTo);
    const query = search.toString();
    return getJson<MeetingsListResponse>(`/api/meetings${query ? `?${query}` : ""}`);
  },
  getMeetingDetail: (id: string) => getJson<MeetingDetailResponse>(`/api/meetings/${encodeURIComponent(id)}`),
  importMeetings: () => postJson<ImportMeetingsResult>("/api/meetings/import"),
  deleteMeeting: (id: string) => postJson<ActionResult>(`/api/meetings/${encodeURIComponent(id)}/delete`),
  /** URL pronta pra abrir/baixar diretamente (ex.: `window.open(...)`) -- gera o arquivo na hora, nunca fica salvo. */
  meetingExportUrl: (id: string, format: ExportFormat) =>
    `/api/meetings/${encodeURIComponent(id)}/export?format=${format}`,
};

export { ApiError };

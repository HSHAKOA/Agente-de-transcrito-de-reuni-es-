/**
 * Tipos do contrato real da API do painel (webui.py), nao da lista
 * ilustrativa de endpoints hipoteticos -- espelham exatamente o que
 * `get_status`/`get_settings_info`/`get_recovery`/`start_transcriber`/etc.
 * devolvem hoje. Ainda nao ha SQLite/historico (Fase E) nem dispositivos de
 * audio (Fase C): esses tipos crescem quando essas fases realmente
 * existirem no backend, nao antes.
 */

export type WhisperModel = "tiny" | "base" | "small" | "medium" | "large-v3";
export type Device = "cpu" | "cuda";

export type MeetingStatus =
  | "created"
  | "recording"
  | "processing"
  | "completed"
  | "interrupted"
  | "failed";

export type ChunkStatus = "recorded" | "transcribed" | "failed";

export interface ChunkRecord {
  index: number;
  path: string;
  start_offset_seconds: number;
  duration_seconds: number;
  status: ChunkStatus;
  retry_count: number;
  error: string | null;
}

/** Espelha o dict devolvido por MeetingSession.state (session.py). */
export interface MeetingSessionState {
  meeting_id: string;
  title: string;
  status: MeetingStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  chunk_count: number;
  chunks_recorded: number;
  chunks_transcribed: number;
  duration: number;
  model: string;
  language: string | null;
  device: string;
  error: string | null;
  chunks: ChunkRecord[];
}

/** GET /api/status */
export interface StatusResponse {
  running: boolean;
  output: string | null;
  chunk_seconds: number | null;
  meeting_dir: string | null;
  started_at: number | null;
  finished_at: number | null;
  exit_code: number | null;
  log: string[];
  block_elapsed?: number;
  block_index?: number;
  output_path?: string;
  output_exists?: boolean;
  output_saved_at?: number;
  output_size?: number;
}

/** GET /api/settings */
export interface SettingsInfo {
  meetings_root: string;
  folder_dialog_available: boolean;
  free_bytes: number | null;
}

/** Resultado de POST /api/choose-folder e /api/settings/meetings-root. */
export interface FolderActionResult extends SettingsInfo {
  ok: boolean;
  cancelled: boolean;
  message: string;
}

/** GET /api/recovery */
export interface RecoveryResponse {
  sessions: MeetingSessionState[];
}

/** Corpo de POST /api/start -- todos os campos sao opcionais no backend
 * (cada um tem um default validado em meeting_transcriber.validation). */
export interface StartMeetingRequest {
  title?: string;
  model?: WhisperModel;
  device?: Device;
  language?: string;
  chunk_seconds?: number;
  keep_audio?: boolean;
}

/** Resposta comum de /api/start, /api/stop, /api/open-folder e
 * /api/meetings/:id/resume -- so {ok, message}, sem dados extras. */
export interface ActionResult {
  ok: boolean;
  message: string;
}

/**
 * Tipos do contrato real da API do painel (webui.py), nao da lista
 * ilustrativa de endpoints hipoteticos -- espelham exatamente o que cada
 * funcao de webui.py devolve hoje (ver docs/API.md). Atualizado
 * conforme as Fases C/C.1/D/E realmente ganharam endpoints reais --
 * cada bloco abaixo cita a fase e a funcao Python que ele espelha.
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

// ---------------------------------------------------------------------
// Fase C: dispositivos de audio (audio/models.py:AudioDevice/AudioHealthResult)
// ---------------------------------------------------------------------

export interface AudioDevice {
  id: string;
  name: string;
  is_default: boolean;
  loopback_supported?: boolean;
}

/** GET /api/audio/devices */
export interface AudioDevicesResponse {
  inputs: AudioDevice[];
  outputs: AudioDevice[];
}

export type AudioErrorCode =
  | "AUDIO_DEVICE_NOT_FOUND"
  | "AUDIO_DEVICE_BUSY"
  | "AUDIO_STREAM_FAILED"
  | "AUDIO_BACKEND_UNAVAILABLE"
  | "AUDIO_NO_SOURCE_ENABLED";

export interface AudioHealthResult {
  ok: boolean;
  code: AudioErrorCode | null;
  message: string;
  device_id?: string;
  device_name?: string;
  level?: number;
}

/** GET/POST /api/audio/config */
export interface AudioConfig {
  capture_system: boolean;
  capture_microphone: boolean;
  system_device_id: string | null;
  microphone_device_id: string | null;
}

/** POST /api/audio/test */
export interface AudioTestResult {
  ok: boolean;
  message?: string;
  results?: {
    system?: AudioHealthResult;
    microphone?: AudioHealthResult;
  };
}

/** GET /api/audio/levels (snapshot) e cada evento de /api/audio/levels/stream (SSE) */
export interface AudioLevelsSnapshot {
  system?: { level: number; active: boolean; updated_at: number };
  microphone?: { level: number; active: boolean; updated_at: number };
}

// ---------------------------------------------------------------------
// Fase D: transcricao ao vivo (live/segments.py, live/transcript.py)
// ---------------------------------------------------------------------

export type SegmentState = "provisional" | "committed";
export type AudioSourceLabel = "system" | "microphone" | "mixed";

export interface LiveSegment {
  start_seconds: number;
  end_seconds: number;
  text: string;
  state: SegmentState;
  source: AudioSourceLabel;
  confidence?: number;
}

export type BacklogStatus = "LIVE" | "PROCESSING" | "BEHIND";

export interface TranscriptionBacklog {
  recorded_seconds: number;
  transcribed_seconds: number;
  pending_seconds: number;
  status: BacklogStatus;
}

/** GET /api/transcription/live (snapshot) e cada evento de /api/transcription/stream (SSE) */
export interface LiveTranscriptionSnapshot {
  segments: LiveSegment[];
  backlog: TranscriptionBacklog;
  avg_latency_seconds: number | null;
  model_load_seconds: number | null;
}

// ---------------------------------------------------------------------
// Fase C.1: agendamento de gravacoes (scheduling/models.py)
// ---------------------------------------------------------------------

export type RecurrenceType = "once" | "daily" | "weekdays" | "weekly" | "custom_days";

export interface Recurrence {
  type: RecurrenceType;
  /** 0=segunda .. 6=domingo (date.weekday()), so usado por weekly/custom_days */
  days: number[];
}

export type ScheduleStatus =
  | "scheduled"
  | "preparing"
  | "recording"
  | "finishing"
  | "completed"
  | "missed"
  | "failed"
  | "cancelled";

export interface ScheduleRun {
  occurrence_date: string;
  scheduled_start_at: string;
  scheduled_end_at: string;
  status: ScheduleStatus;
  meeting_id: string | null;
  meeting_dir: string | null;
  actual_start_at: string | null;
  actual_end_at: string | null;
  ended_early: boolean;
  started_manually_early: boolean;
  error_message: string | null;
  preflight: { ok: boolean; message: string } | null;
}

export interface Schedule {
  id: string;
  title: string;
  scheduled_date: string;
  start_time: string;
  end_time: string;
  timezone: string;
  meetings_root: string;
  system_audio_enabled: boolean;
  system_device_id: string | null;
  microphone_enabled: boolean;
  microphone_device_id: string | null;
  transcription_model: string;
  language: string;
  device: Device;
  chunk_seconds: number;
  recurrence: Recurrence;
  status: ScheduleStatus;
  created_at: string;
  updated_at: string;
  last_run_at: string | null;
  next_run_at: string | null;
  /** calculado pelo servidor -- nunca derive isso do relogio do navegador */
  seconds_until_next_run: number | null;
  current_run: ScheduleRun | null;
  history: ScheduleRun[];
}

/** GET /api/schedules */
export interface SchedulesResponse {
  schedules: Schedule[];
}

export interface CreateScheduleRequest {
  title: string;
  scheduled_date: string;
  start_time: string;
  end_time: string;
  timezone?: string;
  meetings_root: string;
  system_audio_enabled?: boolean;
  system_device_id?: string | null;
  microphone_enabled?: boolean;
  microphone_device_id?: string | null;
  transcription_model?: WhisperModel;
  language?: string;
  device?: Device;
  chunk_seconds?: number;
  recurrence?: Recurrence;
}

export interface ScheduleActionResult {
  ok: boolean;
  message?: string;
  schedule?: Schedule;
}

// ---------------------------------------------------------------------
// Fase E: historico e busca (storage/repository.py)
// ---------------------------------------------------------------------

export interface MeetingRecord {
  id: string;
  title: string;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
  root_directory: string | null;
  meeting_directory: string;
  language: string | null;
  model: string | null;
  system_audio_enabled: boolean | null;
  system_device_id: string | null;
  system_device_name: string | null;
  microphone_enabled: boolean | null;
  microphone_device_id: string | null;
  microphone_device_name: string | null;
  deleted_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MeetingSegmentRecord {
  id: number;
  meeting_id: string;
  sequence: number;
  start_seconds: number;
  end_seconds: number;
  speaker_label: string | null;
  text: string;
  created_at: string;
}

/** GET /api/meetings */
export interface MeetingsListResponse {
  meetings: MeetingRecord[];
  total: number;
  limit: number;
  offset: number;
}

/** GET /api/meetings/:id */
export interface MeetingDetailResponse {
  ok: boolean;
  message?: string;
  meeting?: MeetingRecord;
  segments?: MeetingSegmentRecord[];
}

export interface ImportMeetingsResult {
  ok: boolean;
  imported: number;
  failed: { meeting_id: string; message: string }[];
  total_scanned: number;
}

export type ExportFormat = "markdown" | "txt" | "json" | "srt" | "vtt";

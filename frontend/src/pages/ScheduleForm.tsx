import { ArrowLeft, FolderOpen } from "lucide-react";
import { useEffect, useState } from "react";
import { AudioSourcePicker } from "../components/AudioSourcePicker";
import { useAudioDevices } from "../hooks/useAudioDevices";
import { useSettingsInfo } from "../hooks/useSettingsInfo";
import { api } from "../services/api";
import type { CreateScheduleRequest, Device, RecurrenceType, Schedule, WhisperModel } from "../types/api";
import { WEEKDAY_NAMES } from "../utils/formatRecurrence";
import { WHISPER_MODELS } from "../utils/whisperModels";

const RECURRENCE_OPTIONS: { value: RecurrenceType; label: string }[] = [
  { value: "once", label: "Não repetir" },
  { value: "daily", label: "Todos os dias" },
  { value: "weekdays", label: "Dias úteis" },
  { value: "weekly", label: "Semanalmente" },
  { value: "custom_days", label: "Dias específicos" },
];

function todayISODate(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

function detectBrowserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone;
  } catch {
    return "UTC";
  }
}

interface ScheduleFormProps {
  /** presente = editando um agendamento existente; ausente = criando um novo. */
  existing?: Schedule;
  onBack: () => void;
  onSaved: () => void;
}

/**
 * Formulário de criar/editar agendamento (F.17). Mesmo componente para
 * os dois casos -- só muda se chama `api.createSchedule` ou
 * `api.updateSchedule(existing.id, ...)`. Reaproveita `AudioSourcePicker`
 * (mesmo seletor de fonte de áudio de `pages/NewMeeting.tsx`) em vez de
 * duplicar a marcação.
 */
export function ScheduleForm({ existing, onBack, onSaved }: ScheduleFormProps) {
  const { settings } = useSettingsInfo();
  const { inputs, outputs, error: devicesError } = useAudioDevices();

  const [title, setTitle] = useState(existing?.title ?? "");
  const [scheduledDate, setScheduledDate] = useState(existing?.scheduled_date ?? todayISODate());
  const [startTime, setStartTime] = useState(existing?.start_time ?? "19:00");
  const [endTime, setEndTime] = useState(existing?.end_time ?? "20:00");
  // timezone nunca é editado nesta tela (mission: "usar timezone local
  // detectado do computador como padrão", sem exigir um seletor) -- so
  // valor inicial: o do agendamento existente, editando, ou o detectado
  // do navegador, criando.
  const [timezone] = useState(existing?.timezone ?? detectBrowserTimezone());
  const [meetingsRoot, setMeetingsRoot] = useState(existing?.meetings_root ?? "");

  const [recurrenceType, setRecurrenceType] = useState<RecurrenceType>(existing?.recurrence.type ?? "once");
  const [recurrenceDays, setRecurrenceDays] = useState<number[]>(existing?.recurrence.days ?? []);

  const [model, setModel] = useState<WhisperModel>((existing?.transcription_model as WhisperModel) ?? "small");
  const [language, setLanguage] = useState(existing?.language ?? "pt");
  const [device, setDevice] = useState<Device>(existing?.device ?? "cpu");

  const [captureSystem, setCaptureSystem] = useState(existing?.system_audio_enabled ?? true);
  const [captureMicrophone, setCaptureMicrophone] = useState(existing?.microphone_enabled ?? false);
  const [systemDeviceId, setSystemDeviceId] = useState(existing?.system_device_id ?? "");
  const [microphoneDeviceId, setMicrophoneDeviceId] = useState(existing?.microphone_device_id ?? "");

  const [folderBusy, setFolderBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // pré-preenche a pasta com a raiz global só na criação (editando, já
  // veio de `existing.meetings_root`).
  useEffect(() => {
    if (!existing && settings?.meetings_root && !meetingsRoot) {
      setMeetingsRoot(settings.meetings_root);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings?.meetings_root]);

  async function handleChooseFolder() {
    setFolderBusy(true);
    try {
      const result = await api.chooseFolder();
      if (!result.cancelled && result.ok) {
        setMeetingsRoot(result.meetings_root);
      }
    } finally {
      setFolderBusy(false);
    }
  }

  function toggleDay(day: number) {
    setRecurrenceDays((prev) => (prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day].sort()));
  }

  async function handleSave() {
    setError(null);
    if (!title.trim()) {
      setError("Título é obrigatório.");
      return;
    }
    if (!meetingsRoot.trim()) {
      setError("Escolha uma pasta para salvar a reunião.");
      return;
    }
    if (!captureSystem && !captureMicrophone) {
      setError("Selecione pelo menos uma fonte de áudio.");
      return;
    }
    if ((recurrenceType === "weekly" || recurrenceType === "custom_days") && recurrenceDays.length === 0) {
      setError("Selecione ao menos um dia da semana.");
      return;
    }

    const payload: CreateScheduleRequest = {
      title: title.trim(),
      scheduled_date: scheduledDate,
      start_time: startTime,
      end_time: endTime,
      timezone,
      meetings_root: meetingsRoot,
      system_audio_enabled: captureSystem,
      system_device_id: systemDeviceId || null,
      microphone_enabled: captureMicrophone,
      microphone_device_id: microphoneDeviceId || null,
      transcription_model: model,
      language,
      device,
      recurrence: { type: recurrenceType, days: recurrenceType === "weekly" ? recurrenceDays.slice(0, 1) : recurrenceDays },
    };

    setSaving(true);
    try {
      const result = existing ? await api.updateSchedule(existing.id, payload) : await api.createSchedule(payload);
      if (!result.ok) {
        setError(result.message ?? "Não foi possível salvar o agendamento.");
        setSaving(false);
        return;
      }
      onSaved();
    } catch {
      setError("Não foi possível falar com o painel.");
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <button
        onClick={onBack}
        className="mb-4 flex items-center gap-1.5 text-sm text-neutral-400 transition-colors hover:text-neutral-100"
      >
        <ArrowLeft className="size-4" />
        Voltar
      </button>

      <h1 className="text-xl font-semibold tracking-tight">{existing ? "Editar agendamento" : "Agendar gravação"}</h1>

      <div className="mt-5">
        <label className="mb-1.5 block text-xs font-medium text-neutral-500">Título</label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Aula de Cálculo"
          className="w-full rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none placeholder:text-neutral-600 focus:border-neutral-600"
        />
      </div>

      <div className="mt-4 grid grid-cols-3 gap-3">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-neutral-500">Data</label>
          <input
            type="date"
            value={scheduledDate}
            onChange={(e) => setScheduledDate(e.target.value)}
            className="w-full rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-neutral-600"
          />
        </div>
        <div>
          <label className="mb-1.5 block text-xs font-medium text-neutral-500">Começa</label>
          <input
            type="time"
            value={startTime}
            onChange={(e) => setStartTime(e.target.value)}
            className="w-full rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-neutral-600"
          />
        </div>
        <div>
          <label className="mb-1.5 block text-xs font-medium text-neutral-500">Termina</label>
          <input
            type="time"
            value={endTime}
            onChange={(e) => setEndTime(e.target.value)}
            className="w-full rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-neutral-600"
          />
        </div>
      </div>
      <p className="mt-1 text-xs text-neutral-600">
        Fuso: {timezone} — se o fim for antes do início, é interpretado como virada de meia-noite.
      </p>

      <div className="mt-4">
        <label className="mb-1.5 block text-xs font-medium text-neutral-500">Repetição</label>
        <select
          value={recurrenceType}
          onChange={(e) => setRecurrenceType(e.target.value as RecurrenceType)}
          className="w-full rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-neutral-600"
        >
          {RECURRENCE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
        {(recurrenceType === "weekly" || recurrenceType === "custom_days") && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {WEEKDAY_NAMES.map((name, i) => (
              <button
                key={name}
                type="button"
                onClick={() => toggleDay(i)}
                className={`rounded-md border px-2.5 py-1 text-xs transition-colors ${
                  recurrenceDays.includes(i)
                    ? "border-neutral-500 bg-neutral-800 text-neutral-100"
                    : "border-neutral-800 text-neutral-400 hover:bg-neutral-900"
                }`}
              >
                {name}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="mt-4">
        <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-neutral-500">
          <FolderOpen className="size-3.5" />
          Salvar em
        </label>
        <div className="flex items-center gap-2 rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2">
          <span className="flex-1 truncate font-mono text-xs text-neutral-300">{meetingsRoot || "…"}</span>
          <button
            onClick={handleChooseFolder}
            disabled={folderBusy || settings?.folder_dialog_available === false}
            className="shrink-0 rounded-md border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 transition-colors hover:bg-neutral-800 disabled:opacity-50"
          >
            Escolher pasta
          </button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-neutral-500">Modelo</label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value as WhisperModel)}
            className="w-full rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-neutral-600"
          >
            {WHISPER_MODELS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1.5 block text-xs font-medium text-neutral-500">Idioma</label>
          <input
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
            className="w-full rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-neutral-600"
          />
        </div>
      </div>

      <div className="mt-2">
        <label className="mb-1.5 block text-xs font-medium text-neutral-500">Dispositivo de inferência</label>
        <div className="flex gap-2">
          {(["cpu", "cuda"] as Device[]).map((d) => (
            <button
              key={d}
              type="button"
              onClick={() => setDevice(d)}
              className={`rounded-md border px-3 py-1 text-xs transition-colors ${
                device === d
                  ? "border-neutral-500 bg-neutral-800 text-neutral-100"
                  : "border-neutral-800 text-neutral-400 hover:bg-neutral-900"
              }`}
            >
              {d.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-6 rounded-xl border border-neutral-800 bg-neutral-900 p-5">
        <p className="mb-3 font-medium">Fontes de áudio</p>
        {devicesError && <p className="mb-2 text-sm text-red-400">{devicesError}</p>}
        <AudioSourcePicker
          inputs={inputs}
          outputs={outputs}
          captureSystem={captureSystem}
          setCaptureSystem={setCaptureSystem}
          captureMicrophone={captureMicrophone}
          setCaptureMicrophone={setCaptureMicrophone}
          systemDeviceId={systemDeviceId}
          setSystemDeviceId={setSystemDeviceId}
          microphoneDeviceId={microphoneDeviceId}
          setMicrophoneDeviceId={setMicrophoneDeviceId}
        />
      </div>

      {error && <p className="mt-4 text-sm text-red-400">{error}</p>}

      <button
        onClick={handleSave}
        disabled={saving}
        className="mt-6 w-full rounded-lg border border-emerald-800/60 bg-emerald-950/40 px-4 py-2.5 text-sm font-medium text-emerald-300 transition-colors hover:bg-emerald-950/70 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {saving ? "Salvando…" : existing ? "Salvar alterações" : "Agendar"}
      </button>
    </div>
  );
}

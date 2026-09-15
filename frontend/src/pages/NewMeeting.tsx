import { ArrowLeft, FolderOpen } from "lucide-react";
import { useEffect, useState } from "react";
import { AudioSourcePicker } from "../components/AudioSourcePicker";
import { LevelBar } from "../components/LevelBar";
import { useAudioDevices } from "../hooks/useAudioDevices";
import { useSettingsInfo } from "../hooks/useSettingsInfo";
import { api } from "../services/api";
import type { AudioTestResult, Device, WhisperModel } from "../types/api";
import { WHISPER_MODELS } from "../utils/whisperModels";

interface NewMeetingProps {
  onBack: () => void;
  onStarted: () => void;
}

/**
 * Formulário de nova reunião (F.5). Última peça que faltava pra fechar o
 * ciclo criar -> gravar -> ver no React: escolhe pasta (mesmo diálogo
 * nativo do painel real, via POST /api/choose-folder), fontes de áudio
 * (com "Testar áudio" de verdade antes de começar) e inicia
 * POST /api/start -- a mesma rota, mesma validação, mesmo preflight que
 * index.html sempre usou, sem nenhuma lógica de domínio duplicada aqui.
 */
export function NewMeeting({ onBack, onStarted }: NewMeetingProps) {
  const { settings, refresh: refreshSettings } = useSettingsInfo();
  const { inputs, outputs, error: devicesError } = useAudioDevices();

  const [title, setTitle] = useState("");
  const [model, setModel] = useState<WhisperModel>("small");
  const [device, setDevice] = useState<Device>("cpu");
  const [language, setLanguage] = useState("pt");
  const [captureSystem, setCaptureSystem] = useState(true);
  const [captureMicrophone, setCaptureMicrophone] = useState(false);
  const [systemDeviceId, setSystemDeviceId] = useState<string>("");
  const [microphoneDeviceId, setMicrophoneDeviceId] = useState<string>("");

  const [manualPath, setManualPath] = useState("");
  const [folderBusy, setFolderBusy] = useState(false);
  const [folderMessage, setFolderMessage] = useState<string | null>(null);

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<AudioTestResult | null>(null);

  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    api.getAudioConfig().then((cfg) => {
      setCaptureSystem(cfg.capture_system);
      setCaptureMicrophone(cfg.capture_microphone);
      setSystemDeviceId(cfg.system_device_id ?? "");
      setMicrophoneDeviceId(cfg.microphone_device_id ?? "");
    });
  }, []);

  async function handleChooseFolder() {
    setFolderBusy(true);
    setFolderMessage(null);
    try {
      const result = await api.chooseFolder();
      if (result.cancelled) {
        setFolderBusy(false);
        return;
      }
      if (!result.ok) {
        setFolderMessage(result.message);
      } else {
        await refreshSettings();
      }
    } catch {
      setFolderMessage("Não foi possível abrir o seletor de pasta.");
    } finally {
      setFolderBusy(false);
    }
  }

  async function handleSetManualPath() {
    if (!manualPath.trim()) return;
    setFolderBusy(true);
    setFolderMessage(null);
    try {
      const result = await api.setMeetingsRootManually(manualPath.trim());
      if (!result.ok) {
        setFolderMessage(result.message);
      } else {
        await refreshSettings();
        setManualPath("");
      }
    } catch {
      setFolderMessage("Não foi possível definir a pasta.");
    } finally {
      setFolderBusy(false);
    }
  }

  async function handleTestAudio() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await api.testAudio({
        capture_system: captureSystem,
        capture_microphone: captureMicrophone,
        system_device_id: systemDeviceId || null,
        microphone_device_id: microphoneDeviceId || null,
      });
      setTestResult(result);
    } catch {
      setTestResult({ ok: false, message: "Não foi possível testar o áudio." });
    } finally {
      setTesting(false);
    }
  }

  async function handleStart() {
    setStarting(true);
    setStartError(null);
    try {
      const result = await api.startMeeting({
        title: title.trim() || undefined,
        model,
        device,
        language,
        capture_system: captureSystem,
        capture_microphone: captureMicrophone,
        system_device_id: systemDeviceId || undefined,
        microphone_device_id: microphoneDeviceId || undefined,
      });
      if (!result.ok) {
        setStartError(result.message);
        setStarting(false);
        return;
      }
      onStarted();
    } catch {
      setStartError("Não foi possível iniciar a gravação.");
      setStarting(false);
    }
  }

  const noSourceSelected = !captureSystem && !captureMicrophone;

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <button
        onClick={onBack}
        className="mb-4 flex items-center gap-1.5 text-sm text-neutral-400 transition-colors hover:text-neutral-100"
      >
        <ArrowLeft className="size-4" />
        Voltar
      </button>

      <h1 className="text-xl font-semibold tracking-tight">Nova reunião</h1>

      <div className="mt-5">
        <label className="mb-1.5 block text-xs font-medium text-neutral-500">Título</label>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Reunião de hoje"
          className="w-full rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none placeholder:text-neutral-600 focus:border-neutral-600"
        />
      </div>

      <div className="mt-4">
        <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-neutral-500">
          <FolderOpen className="size-3.5" />
          Salvar em
        </label>
        <div className="flex items-center gap-2 rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2">
          <span className="flex-1 truncate font-mono text-xs text-neutral-300">
            {settings?.meetings_root ?? "…"}
          </span>
          <button
            onClick={handleChooseFolder}
            disabled={folderBusy || settings?.folder_dialog_available === false}
            className="shrink-0 rounded-md border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 transition-colors hover:bg-neutral-800 disabled:opacity-50"
          >
            Escolher pasta
          </button>
        </div>
        {settings?.folder_dialog_available === false && (
          <div className="mt-2 flex gap-2">
            <input
              value={manualPath}
              onChange={(e) => setManualPath(e.target.value)}
              placeholder="Caminho da pasta"
              className="flex-1 rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-1.5 text-xs outline-none placeholder:text-neutral-600"
            />
            <button
              onClick={handleSetManualPath}
              disabled={folderBusy}
              className="rounded-md border border-neutral-700 px-2.5 py-1 text-xs text-neutral-300 hover:bg-neutral-800 disabled:opacity-50"
            >
              Definir
            </button>
          </div>
        )}
        {folderMessage && <p className="mt-1.5 text-xs text-red-400">{folderMessage}</p>}
      </div>

      <div className="mt-5 grid grid-cols-2 gap-3">
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
            placeholder="pt, en, auto…"
            className="w-full rounded-lg border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm outline-none placeholder:text-neutral-600 focus:border-neutral-600"
          />
        </div>
      </div>

      <div className="mt-2">
        <label className="mb-1.5 block text-xs font-medium text-neutral-500">Dispositivo de inferência</label>
        <div className="flex gap-2">
          {(["cpu", "cuda"] as Device[]).map((d) => (
            <button
              key={d}
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

        <button
          onClick={handleTestAudio}
          disabled={testing || noSourceSelected}
          className="mt-4 rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 transition-colors hover:bg-neutral-800 disabled:opacity-50"
        >
          {testing ? "Testando…" : "Testar áudio"}
        </button>

        {testResult && (
          <div className="mt-3 space-y-2">
            {testResult.message && !testResult.ok && <p className="text-xs text-red-400">{testResult.message}</p>}
            {testResult.results?.system && (
              <LevelBar
                label={`Áudio do computador${testResult.results.system.ok ? "" : ` — ${testResult.results.system.message}`}`}
                level={testResult.results.system.level}
                active={testResult.results.system.ok}
              />
            )}
            {testResult.results?.microphone && (
              <LevelBar
                label={`Microfone${testResult.results.microphone.ok ? "" : ` — ${testResult.results.microphone.message}`}`}
                level={testResult.results.microphone.level}
                active={testResult.results.microphone.ok}
              />
            )}
          </div>
        )}
      </div>

      {startError && <p className="mt-4 text-sm text-red-400">{startError}</p>}

      <button
        onClick={handleStart}
        disabled={starting || noSourceSelected}
        className="mt-6 w-full rounded-lg border border-emerald-800/60 bg-emerald-950/40 px-4 py-2.5 text-sm font-medium text-emerald-300 transition-colors hover:bg-emerald-950/70 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {starting ? "Iniciando…" : "Iniciar reunião"}
      </button>
    </div>
  );
}

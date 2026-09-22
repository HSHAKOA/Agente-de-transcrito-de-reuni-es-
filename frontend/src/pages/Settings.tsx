import { ArrowLeft, FolderOpen, HardDrive } from "lucide-react";
import { useEffect, useState } from "react";
import { AudioSourcePicker } from "../components/AudioSourcePicker";
import { Card } from "../components/Card";
import { useAudioDevices } from "../hooks/useAudioDevices";
import { useSettingsInfo } from "../hooks/useSettingsInfo";
import { api } from "../services/api";
import { formatBytes } from "../utils/formatBytes";

interface SettingsProps {
  onBack: () => void;
}

/**
 * Configurações (F.3): hoje só a pasta de reuniões e a preferência
 * padrão de fontes de áudio (o que `POST /api/audio/config` já
 * persiste) -- o restante das opções do painel (modelo/idioma/etc.) é
 * escolhido por reunião em `pages/NewMeeting.tsx`, não é uma preferência
 * global no backend hoje.
 */
export function Settings({ onBack }: SettingsProps) {
  const { settings, error: settingsError, refresh } = useSettingsInfo();
  const { inputs, outputs, error: devicesError } = useAudioDevices();

  const [captureSystem, setCaptureSystem] = useState(true);
  const [captureMicrophone, setCaptureMicrophone] = useState(false);
  const [systemDeviceId, setSystemDeviceId] = useState("");
  const [microphoneDeviceId, setMicrophoneDeviceId] = useState("");
  const [saved, setSaved] = useState(false);
  const [audioConfigError, setAudioConfigError] = useState<string | null>(null);

  const [manualPath, setManualPath] = useState("");
  const [folderBusy, setFolderBusy] = useState(false);
  const [folderMessage, setFolderMessage] = useState<string | null>(null);

  useEffect(() => {
    api
      .getAudioConfig()
      .then((cfg) => {
        setCaptureSystem(cfg.capture_system);
        setCaptureMicrophone(cfg.capture_microphone);
        setSystemDeviceId(cfg.system_device_id ?? "");
        setMicrophoneDeviceId(cfg.microphone_device_id ?? "");
      })
      .catch(() => setAudioConfigError("Não foi possível carregar as fontes de áudio padrão."));
  }, []);

  async function handleChooseFolder() {
    setFolderBusy(true);
    setFolderMessage(null);
    try {
      const result = await api.chooseFolder();
      if (!result.cancelled && !result.ok) setFolderMessage(result.message);
      await refresh();
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
        setManualPath("");
        await refresh();
      }
    } finally {
      setFolderBusy(false);
    }
  }

  async function handleSaveAudioDefaults() {
    setSaved(false);
    setAudioConfigError(null);
    try {
      await api.setAudioConfig({
        capture_system: captureSystem,
        capture_microphone: captureMicrophone,
        system_device_id: systemDeviceId || null,
        microphone_device_id: microphoneDeviceId || null,
      });
      setSaved(true);
    } catch {
      setAudioConfigError("Não foi possível salvar as fontes de áudio padrão.");
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

      <h1 className="text-xl font-semibold tracking-tight">Configurações</h1>

      <Card icon={<FolderOpen className="size-4 text-neutral-500" />} title="Pasta das reuniões" className="mt-5">
        {settingsError && <p className="mb-2 text-sm text-red-400">{settingsError}</p>}
        <div className="flex items-center gap-2 rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-2">
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
              // Unico campo da tela e nao tinha rotulo nenhum -- so
              // `placeholder`, que desaparece ao digitar e nao e nome
              // acessivel.
              aria-label="Caminho da pasta de reuniões"
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
        {settings && (
          <p className="mt-2 flex items-center gap-1.5 text-xs text-neutral-500">
            <HardDrive className="size-3.5" />
            Espaço livre: {formatBytes(settings.free_bytes)}
          </p>
        )}
      </Card>

      <Card title="Fontes de áudio padrão" className="mt-4">
        {devicesError && <p className="mb-2 text-sm text-red-400">{devicesError}</p>}
        {audioConfigError && (
          <p role="alert" className="mb-2 text-sm text-red-400">
            {audioConfigError}
          </p>
        )}
        <p className="mb-3 text-xs text-neutral-500">
          Usado quando uma nova reunião não especifica fontes explicitamente.
        </p>
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
          onClick={handleSaveAudioDefaults}
          className="mt-4 rounded-md border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 transition-colors hover:bg-neutral-800"
        >
          Salvar como padrão
        </button>
        {saved && <span className="ml-2 text-xs text-emerald-400">Salvo.</span>}
      </Card>
    </div>
  );
}

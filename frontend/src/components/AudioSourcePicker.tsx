import { Mic, Volume2 } from "lucide-react";
import type { AudioDevice } from "../types/api";

interface AudioSourcePickerProps {
  inputs: AudioDevice[];
  outputs: AudioDevice[];
  captureSystem: boolean;
  setCaptureSystem: (v: boolean) => void;
  captureMicrophone: boolean;
  setCaptureMicrophone: (v: boolean) => void;
  systemDeviceId: string;
  setSystemDeviceId: (v: string) => void;
  microphoneDeviceId: string;
  setMicrophoneDeviceId: (v: string) => void;
}

/** Checkbox + select de dispositivo para cada fonte de áudio -- usado por
 * `pages/NewMeeting.tsx` e `pages/ScheduleForm.tsx` (extraído daqui pra
 * não duplicar a mesma marcação nos dois formulários). */
export function AudioSourcePicker({
  inputs,
  outputs,
  captureSystem,
  setCaptureSystem,
  captureMicrophone,
  setCaptureMicrophone,
  systemDeviceId,
  setSystemDeviceId,
  microphoneDeviceId,
  setMicrophoneDeviceId,
}: AudioSourcePickerProps) {
  return (
    <div className="space-y-3">
      <div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={captureSystem} onChange={(e) => setCaptureSystem(e.target.checked)} />
          <Volume2 className="size-4 text-neutral-400" />
          Áudio do computador
        </label>
        {captureSystem && (
          <select
            // O checkbox acima tem nome (esta dentro do <label>), mas este
            // select nao -- um leitor de tela anunciaria so "caixa de
            // combinacao". Nome explicito porque o rotulo visivel pertence
            // ao checkbox, nao a ele.
            aria-label="Dispositivo de áudio do computador"
            value={systemDeviceId}
            onChange={(e) => setSystemDeviceId(e.target.value)}
            className="mt-1.5 ml-6 w-[calc(100%-1.5rem)] rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-1.5 text-xs outline-none"
          >
            <option value="">Padrão do sistema</option>
            {outputs.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
                {d.is_default ? " (padrão)" : ""}
              </option>
            ))}
          </select>
        )}
      </div>

      <div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={captureMicrophone}
            onChange={(e) => setCaptureMicrophone(e.target.checked)}
          />
          <Mic className="size-4 text-neutral-400" />
          Microfone
        </label>
        {captureMicrophone && (
          <select
            aria-label="Dispositivo de microfone"
            value={microphoneDeviceId}
            onChange={(e) => setMicrophoneDeviceId(e.target.value)}
            className="mt-1.5 ml-6 w-[calc(100%-1.5rem)] rounded-lg border border-neutral-800 bg-neutral-950 px-3 py-1.5 text-xs outline-none"
          >
            <option value="">Padrão do sistema</option>
            {inputs.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
                {d.is_default ? " (padrão)" : ""}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}

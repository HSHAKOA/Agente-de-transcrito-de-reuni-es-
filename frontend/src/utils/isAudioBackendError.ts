import type { AudioBackendError, AudioDevicesResponse } from "../types/api";

/** Type guard para a resposta de erro estruturado de GET /api/audio/devices
 * (ver types/api.ts:AudioDevicesResponse). */
export function isAudioBackendError(value: AudioDevicesResponse): value is AudioBackendError {
  return "error" in value;
}

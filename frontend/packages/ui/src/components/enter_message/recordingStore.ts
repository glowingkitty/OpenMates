// frontend/packages/ui/src/components/enter_message/recordingStore.ts
//
// Stores reactive state for the audio recording UI.
// micPermissionState tracks what the browser Permissions API reports:
//   'unknown'  — not yet queried (SSR / Permissions API unavailable)
//   'granted'  — user has previously allowed; recording can start immediately on hold
//   'prompt'   — browser will show a permission popup on first getUserMedia call
//   'denied'   — user has blocked the mic; show settings-redirect hint
import { writable } from "svelte/store";

export type MicPermissionState = "unknown" | "granted" | "prompt" | "denied";

interface RecordingState {
  isRecordButtonPressed: boolean;
  showRecordAudioUI: boolean;
  showRecordHint: boolean;
  /** Tri-state mic permission derived from navigator.permissions — replaces the old boolean. */
  micPermissionState: MicPermissionState;
  isRecordingActive: boolean;
  recordStartPosition: { x: number; y: number };
}

const initialState: RecordingState = {
  isRecordButtonPressed: false,
  showRecordAudioUI: false,
  showRecordHint: false,
  micPermissionState: "unknown",
  isRecordingActive: false,
  recordStartPosition: { x: 0, y: 0 },
};

export const recordingState = writable<RecordingState>(initialState);

export function updateRecordingState(updates: Partial<RecordingState>) {
  recordingState.update((current) => ({ ...current, ...updates }));
}

// Query the Permissions API on module load (client-side only).
// This lets the mic button show the correct hint without any user interaction.
// The onchange handler keeps the state in sync if the user later grants/revokes
// permission in browser settings without reloading the page.
if (typeof navigator !== "undefined" && navigator.permissions) {
  navigator.permissions
    .query({ name: "microphone" as PermissionName })
    .then((status) => {
      updateRecordingState({
        micPermissionState: status.state as MicPermissionState,
      });
      // React to runtime permission changes (e.g. user revokes in settings)
      status.onchange = () => {
        updateRecordingState({
          micPermissionState: status.state as MicPermissionState,
        });
      };
    })
    .catch(() => {
      // Permissions API unsupported or blocked — leave as 'unknown'.
      // Recording will attempt getUserMedia directly and surface errors then.
      console.warn(
        "[RecordingStore] Could not query microphone permission status.",
      );
    });
}

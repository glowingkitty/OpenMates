// frontend/packages/ui/src/components/enter_message/handlers/recordingHandlers.ts
//
// Handles audio recording start and microphone permission logic.
//
// Permission flow (two-phase, matches how WhatsApp/Telegram handle this):
//
//   Phase 1 — first press when permission is 'prompt':
//     Calls getUserMedia() to surface the browser popup. If the user grants
//     access, recording starts immediately.
//
//   Phase 2 — subsequent press when permission is 'granted':
//     Recording starts immediately, no popup.
//
//   'denied' state:
//     mousedown/touchstart is a no-op; the hint in the UI already explains
//     the user must enable the mic in browser settings.
//
// No alert() calls — all feedback is through the store's showRecordHint /
// micPermissionState fields which drive reactive UI in MessageInput.

import { get } from "svelte/store";
import { recordingState, updateRecordingState } from "../recordingStore";

// --- Module-level timers ---
let recordHintTimeout: ReturnType<typeof setTimeout> | null = null;

// --- Helpers ---

/**
 * Show a hint below the action buttons for `durationMs`, then hide it.
 * Cancels any previously scheduled hint dismissal.
 */
function showHintFor(durationMs = 2500) {
  updateRecordingState({ showRecordHint: true });
  clearTimeout(recordHintTimeout ?? undefined);
  recordHintTimeout = setTimeout(() => {
    updateRecordingState({ showRecordHint: false });
    recordHintTimeout = null;
  }, durationMs);
}

// --- Permission ---

/**
 * Request microphone access and update the permission state in the store.
 * Returns true if access is now granted, false otherwise.
 *
 * Calling getUserMedia() is the only cross-browser way to actually trigger
 * the permission popup — navigator.permissions.query() is read-only.
 * We stop the tracks immediately after so we don't hold the mic open;
 * RecordAudio.svelte will acquire its own stream when recording starts.
 */
async function requestMicPermission(): Promise<boolean> {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    stream.getTracks().forEach((t) => t.stop());
    updateRecordingState({ micPermissionState: "granted" });
    return true;
  } catch (err) {
    // NotAllowedError → user denied; other errors (NotFoundError etc.) treated as blocked
    console.warn("[RecordingHandlers] Microphone access denied:", err);
    updateRecordingState({ micPermissionState: "denied" });
    return false;
  }
}

// --- Recording Attempt Logic ---

export function startRecording(x: number, y: number) {
  if (get(recordingState).showRecordAudioUI) return;

  updateRecordingState({
    recordStartPosition: { x, y },
    isRecordButtonPressed: true,
    showRecordAudioUI: true,
    showRecordHint: false,
  });
  clearTimeout(recordHintTimeout ?? undefined);
}

export function stopRecordAttempt(
  _potentiallyComplete: boolean,
  _recordAudioComponent?: { stop: () => void; cancel: () => void },
) {
  // Release/leave no longer completes or cancels recording. RecordAudio owns
  // completion via Finish/Enter and cancellation via Cancel/Escape.
}

// --- Cleanup ---

export function handleStopRecordingCleanup(): void {
  updateRecordingState({
    showRecordAudioUI: false,
    isRecordButtonPressed: false,
    isRecordingActive: false,
  });
  clearTimeout(recordHintTimeout ?? undefined);
  recordHintTimeout = null;
}

// --- Event Handlers ---

export async function handleRecordMouseDown(event: MouseEvent) {
  if (event.button !== 0) return;

  const { micPermissionState } = get(recordingState);

  if (micPermissionState === "denied") {
    // Permission permanently blocked — hint is already shown by the UI reactively.
    // No-op: user must go to browser settings.
    return;
  }

  if (micPermissionState === "granted") {
    startRecording(event.clientX, event.clientY);
    return;
  }

  // 'prompt' or 'unknown' — trigger browser permission popup on this tap.
  updateRecordingState({ isRecordButtonPressed: true });
  const granted = await requestMicPermission();

  if (granted) {
    startRecording(event.clientX, event.clientY);
  } else {
    updateRecordingState({ isRecordButtonPressed: false });
    showHintFor(2500);
  }
}

export function handleRecordMouseUp(recordAudioComponent?: {
  stop: () => void;
  cancel: () => void;
}) {
  stopRecordAttempt(true, recordAudioComponent);
}

export function handleRecordMouseLeave(recordAudioComponent?: {
  stop: () => void;
  cancel: () => void;
}) {
  if (get(recordingState).isRecordButtonPressed) {
    stopRecordAttempt(false, recordAudioComponent);
  }
}

export async function handleRecordTouchStart(event: TouchEvent) {
  // NOTE: Do NOT call event.preventDefault() here.
  // On Firefox iOS (and some other mobile browsers), calling preventDefault() on
  // touchstart consumes the user gesture token. getUserMedia() requires an active
  // user gesture — if the token is consumed before the async call, the browser
  // silently refuses to show the permission popup and the stream is never returned.
  // Scroll prevention is handled at the CSS level (touch-action: none on the button).

  const { micPermissionState } = get(recordingState);

  if (micPermissionState === "denied") return;

  if (micPermissionState === "granted") {
    if (event.touches.length > 0) {
      startRecording(event.touches[0].clientX, event.touches[0].clientY);
    }
    return;
  }

  // 'prompt' or 'unknown'
  updateRecordingState({ isRecordButtonPressed: true });
  const granted = await requestMicPermission();

  if (granted && event.touches.length > 0) {
    startRecording(event.touches[0].clientX, event.touches[0].clientY);
  } else {
    updateRecordingState({ isRecordButtonPressed: false });
    showHintFor(2500);
  }
}

export function handleRecordTouchEnd(recordAudioComponent?: {
  stop: () => void;
  cancel: () => void;
}) {
  stopRecordAttempt(true, recordAudioComponent);
}

// Keep the old export name for any callers that still reference preRequestMicAccess
export { requestMicPermission as preRequestMicAccess };

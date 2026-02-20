// frontend/packages/ui/src/components/enter_message/handlers/recordingHandlers.ts
//
// Handles all press-and-hold recording interaction logic.
//
// Permission flow (two-phase, matches how WhatsApp/Telegram handle this):
//
//   Phase 1 — first tap when permission is 'prompt':
//     Calls getUserMedia() to surface the browser popup.
//     Does NOT start recording — the user releases the button before they can
//     hold, so we just show "Hold to record" once permission is granted.
//     If denied, shows 'microphone_blocked' hint; the store reflects 'denied'
//     so the button tooltip also updates.
//
//   Phase 2 — subsequent press-and-hold when permission is 'granted':
//     Recording starts immediately after the 200 ms hold threshold, no popup.
//
//   'denied' state:
//     mousedown/touchstart is a no-op; the hint in the UI already explains
//     the user must enable the mic in browser settings.
//
// No alert() calls — all feedback is through the store's showRecordHint /
// micPermissionState fields which drive reactive UI in ActionButtons.

import { get } from "svelte/store";
import { recordingState, updateRecordingState } from "../recordingStore";

// --- Module-level timers ---
let recordStartTimeout: ReturnType<typeof setTimeout> | null = null;
let recordHintTimeout: ReturnType<typeof setTimeout> | null = null;
let hasRecordingStarted = false;

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

export function startRecordAttempt(x: number, y: number) {
  hasRecordingStarted = false;
  clearTimeout(recordStartTimeout ?? undefined);

  recordStartTimeout = setTimeout(() => {
    updateRecordingState({
      recordStartPosition: { x, y },
      isRecordButtonPressed: true,
      showRecordAudioUI: true,
      showRecordHint: false,
    });
    hasRecordingStarted = true;
    clearTimeout(recordHintTimeout ?? undefined);
  }, 200);
}

export function stopRecordAttempt(
  potentiallyComplete: boolean,
  recordAudioComponent?: { stop: () => void; cancel: () => void },
) {
  clearTimeout(recordStartTimeout ?? undefined);

  if (hasRecordingStarted) {
    if (recordAudioComponent) {
      if (potentiallyComplete) {
        recordAudioComponent.stop();
      } else {
        recordAudioComponent.cancel();
      }
    } else {
      console.warn(
        "[RecordingHandlers] stopRecordAttempt: no component ref, cleaning up directly.",
      );
      handleStopRecordingCleanup();
    }
  } else {
    // Short tap — not long enough to start recording
    updateRecordingState({
      isRecordButtonPressed: false,
      showRecordAudioUI: false,
    });
    showHintFor(2500);
  }
  hasRecordingStarted = false;
}

// --- Cleanup ---

export function handleStopRecordingCleanup(): void {
  updateRecordingState({
    showRecordAudioUI: false,
    isRecordButtonPressed: false,
    isRecordingActive: false,
  });
  hasRecordingStarted = false;
  clearTimeout(recordStartTimeout ?? undefined);
  clearTimeout(recordHintTimeout ?? undefined);
  recordStartTimeout = null;
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
    // Permission already granted — start recording on hold immediately.
    updateRecordingState({ isRecordButtonPressed: true });
    startRecordAttempt(event.clientX, event.clientY);
    return;
  }

  // 'prompt' or 'unknown' — trigger browser permission popup on this tap.
  // Do NOT start recording yet; user will need to hold after granting.
  updateRecordingState({ isRecordButtonPressed: true });
  const granted = await requestMicPermission();
  updateRecordingState({ isRecordButtonPressed: false });

  if (granted) {
    // Show "Hold to record" hint so user knows what to do next.
    showHintFor(2500);
  }
  // If denied, micPermissionState is now 'denied' → UI reactively shows blocked hint.
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
  event.preventDefault();

  const { micPermissionState } = get(recordingState);

  if (micPermissionState === "denied") return;

  if (micPermissionState === "granted") {
    if (event.touches.length > 0) {
      updateRecordingState({ isRecordButtonPressed: true });
      startRecordAttempt(event.touches[0].clientX, event.touches[0].clientY);
    }
    return;
  }

  // 'prompt' or 'unknown'
  updateRecordingState({ isRecordButtonPressed: true });
  const granted = await requestMicPermission();
  updateRecordingState({ isRecordButtonPressed: false });

  if (granted) {
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

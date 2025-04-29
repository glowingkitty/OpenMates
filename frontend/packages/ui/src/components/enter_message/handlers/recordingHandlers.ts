// frontend/packages/ui/src/components/enter_message/handlers/recordingHandlers.ts
import { get } from 'svelte/store';
import { recordingState, updateRecordingState } from '../recordingStore';
import { text } from '@repo/ui'; // Import the text store

// --- State ---
let recordStartTimeout: ReturnType<typeof setTimeout> | null = null;
let recordHintTimeout: ReturnType<typeof setTimeout> | null = null;
// Remove recordStartPosition from here, it's in the store now
let hasRecordingStarted = false;

// --- Permission ---
export async function preRequestMicAccess(): Promise<boolean> {
    const currentState = get(recordingState);
    if (currentState.micPermissionGranted) {
        return true;
    }
    try {
        console.debug("Requesting microphone access...");
        const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
        stream.getTracks().forEach(track => track.stop());
        console.info("Microphone permission granted.");
        updateRecordingState({ micPermissionGranted: true });
        return true;
    } catch (err) {
        console.error('Error requesting microphone access:', err);
        updateRecordingState({ micPermissionGranted: false });
        // Use $text store for translation
        alert(get(text)('enter_message.attachments.record_audio.permission_denied') || 'Microphone access denied.');
        return false;
    }
}

// --- Recording Attempt Logic ---

export function startRecordAttempt(x: number, y: number) {
    hasRecordingStarted = false;
    clearTimeout(recordStartTimeout ?? undefined);

    recordStartTimeout = setTimeout(() => {
        // Store position in the store
        updateRecordingState({
            recordStartPosition: { x, y },
            isRecordButtonPressed: true,
            showRecordAudioUI: true,
            showRecordHint: false
        });
        hasRecordingStarted = true;
        clearTimeout(recordHintTimeout ?? undefined);
        console.debug("Recording started via timeout");
    }, 200);
}

// stopRecordAttempt remains the same

export function stopRecordAttempt(potentiallyComplete: boolean, recordAudioComponent?: { stop: () => void; cancel: () => void }) {
    clearTimeout(recordStartTimeout ?? undefined); // Clear the start timeout

    if (hasRecordingStarted) {
        // If recording actually started, let the RecordAudio component handle stop/cancel
        if (recordAudioComponent) {
            if (potentiallyComplete) {
                console.debug("Stopping recording via component");
                recordAudioComponent.stop(); // Tell component to finalize
            } else {
                console.debug("Cancelling recording via component");
                recordAudioComponent.cancel(); // Tell component to cancel
            }
        } else {
             console.warn("stopRecordAttempt called but recordAudioComponent is not available.");
             // Fallback: Reset state directly if component ref is missing
             handleStopRecordingCleanup();
        }
        // Reset button state etc. will be handled by RecordAudio's events calling handleStopRecordingCleanup
    } else {
        // If timeout didn't finish (i.e., it was a short click/tap)
        console.debug("Recording attempt was a short tap/click");
        updateRecordingState({ isRecordButtonPressed: false, showRecordAudioUI: false, showRecordHint: true });
        clearTimeout(recordHintTimeout ?? undefined); // Clear previous hint timeout
        recordHintTimeout = setTimeout(() => {
            updateRecordingState({ showRecordHint: false });
        }, 2000);
    }
    hasRecordingStarted = false; // Reset flag regardless
}


// --- Cleanup ---
// handleStopRecordingCleanup remains the same
export function handleStopRecordingCleanup(): void {
    console.debug("Cleaning up recording state");
    updateRecordingState({ showRecordAudioUI: false, isRecordButtonPressed: false, isRecordingActive: false });
    hasRecordingStarted = false;
    clearTimeout(recordStartTimeout ?? undefined);
    clearTimeout(recordHintTimeout ?? undefined);
    recordStartTimeout = null;
    recordHintTimeout = null;
}


// --- Event Handlers (Accept original DOM events) ---

export async function handleRecordMouseDown(event: MouseEvent) { // Expect MouseEvent
    if (event.button !== 0) return;
    const permissionGranted = await preRequestMicAccess();
    if (!permissionGranted) return;
    startRecordAttempt(event.clientX, event.clientY);
}

// Pass the component instance directly
export function handleRecordMouseUp(recordAudioComponent?: { stop: () => void; cancel: () => void }) {
    stopRecordAttempt(true, recordAudioComponent);
}

export function handleRecordMouseLeave(recordAudioComponent?: { stop: () => void; cancel: () => void }) {
    if (get(recordingState).isRecordButtonPressed) {
        stopRecordAttempt(false, recordAudioComponent);
    }
}

export async function handleRecordTouchStart(event: TouchEvent) { // Expect TouchEvent
    event.preventDefault();
    const permissionGranted = await preRequestMicAccess();
    if (!permissionGranted) return;

    if (event.touches.length > 0) {
        startRecordAttempt(event.touches[0].clientX, event.touches[0].clientY);
    }
}

// Pass the component instance directly
export function handleRecordTouchEnd(recordAudioComponent?: { stop: () => void; cancel: () => void }) {
    stopRecordAttempt(true, recordAudioComponent);
}
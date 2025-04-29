// frontend/packages/ui/src/components/enter_message/recordingStore.ts
import { writable } from 'svelte/store';

interface RecordingState {
    isRecordButtonPressed: boolean;
    showRecordAudioUI: boolean;
    showRecordHint: boolean;
    micPermissionGranted: boolean;
    isRecordingActive: boolean;
    recordStartPosition: { x: number; y: number }; // Add position
}

const initialState: RecordingState = {
    isRecordButtonPressed: false,
    showRecordAudioUI: false,
    showRecordHint: false,
    micPermissionGranted: false,
    isRecordingActive: false,
    recordStartPosition: { x: 0, y: 0 }, // Initialize position
};

export const recordingState = writable<RecordingState>(initialState);

export function updateRecordingState(updates: Partial<RecordingState>) {
    recordingState.update(current => ({ ...current, ...updates }));
}

// Permission check logic remains the same
if (typeof navigator !== 'undefined' && navigator.permissions) {
    navigator.permissions.query({ name: 'microphone' as PermissionName }).then((permissionStatus) => {
        updateRecordingState({ micPermissionGranted: permissionStatus.state === 'granted' });
        permissionStatus.onchange = () => {
            updateRecordingState({ micPermissionGranted: permissionStatus.state === 'granted' });
        };
    }).catch(err => console.warn("Could not query microphone permission:", err));
} else if (typeof navigator !== 'undefined' && !navigator.permissions) {
     console.warn("Browser does not support Permissions API for microphone check.");
}
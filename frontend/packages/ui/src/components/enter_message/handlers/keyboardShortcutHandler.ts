// frontend/packages/ui/src/components/enter_message/handlers/keyboardShortcutHandler.ts
import type { Editor } from '@tiptap/core';
import { get } from 'svelte/store';
import { recordingState } from '../recordingStore';
import {
    handleRecordMouseDown,
    handleRecordMouseUp,
    handleRecordMouseLeave
} from './recordingHandlers';

// Define the expected interface for the component ref
interface RecordAudioControls {
    stop: () => void;
    cancel: () => void;
}

/**
 * Handles keyboard shortcuts dispatched from the KeyboardShortcuts component.
 */
export function handleKeyboardShortcut(
    type: 'startRecording' | 'stopRecording' | 'cancelRecording',
    editor: Editor | null,
    isMessageFieldFocused: boolean,
    recordAudioComponent?: RecordAudioControls
) {
    const currentState = get(recordingState);

    switch (type) {
        case 'startRecording':
            // For now, we just log to the console as requested.
            // The actual recording logic is commented out.
            console.log('Spacebar held: Audio recording feature would start here.');

            // if (currentState.micPermissionGranted && !currentState.isRecordButtonPressed) {
            //     console.debug('Handling startRecording shortcut');
            //     // Simulate mouse down - permission check happens inside
            //     handleRecordMouseDown(new MouseEvent('mousedown'));
            // } else if (!currentState.micPermissionGranted) {
            //      console.debug('Mic permission needed for startRecording shortcut');
            // }
            break;

        case 'stopRecording':
             if (currentState.isRecordButtonPressed) {
                console.debug('Handling stopRecording shortcut');
                // Pass the component controls directly
                handleRecordMouseUp(recordAudioComponent);
             }
            break;

        case 'cancelRecording':
            if (currentState.isRecordButtonPressed) {
                console.debug('Handling cancelRecording shortcut');
                // Pass the component controls directly
                handleRecordMouseLeave(recordAudioComponent);
            }
            break;
    }
}

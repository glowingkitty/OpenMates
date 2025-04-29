// frontend/packages/ui/src/components/enter_message/handlers/keyboardShortcutHandler.ts
import type { Editor } from '@tiptap/core';
// No longer need CustomEvent from svelte
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
    // Use the built-in DOM CustomEvent type
    event: CustomEvent<{ type: string; originalEvent?: KeyboardEvent }>,
    editor: Editor | null,
    isMessageFieldFocused: boolean,
    // Use the interface for the component
    recordAudioComponent?: RecordAudioControls
) {
    // Add null check for event.detail
    if (!event.detail) {
        console.warn('[KeyboardShortcutHandler] Received event without detail:', event);
        return;
    }
    const { type, originalEvent } = event.detail;
    const currentState = get(recordingState);

    switch (type) {
        case 'startRecording':
            if (currentState.micPermissionGranted && !currentState.isRecordButtonPressed) {
                console.debug('Handling startRecording shortcut');
                // Simulate mouse down - permission check happens inside
                handleRecordMouseDown(new MouseEvent('mousedown'));
            } else if (!currentState.micPermissionGranted) {
                 console.debug('Mic permission needed for startRecording shortcut');
            }
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

        case 'insertSpace':
            if (editor && isMessageFieldFocused) {
                console.debug('Handling insertSpace shortcut');
                originalEvent?.preventDefault();
                editor.commands.insertContent(' ');
            }
            break;
    }
}
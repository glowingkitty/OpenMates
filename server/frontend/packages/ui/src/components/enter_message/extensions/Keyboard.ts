// src/components/MessageInput/extensions/Keyboard.ts
import { Extension } from '@tiptap/core';
import { hasActualContent } from '../utils';  // Updated import path
import { vibrateMessageField } from '../utils'; // Updated import path

export interface KeyboardOptions {}

export const CustomKeyboardHandling = Extension.create<KeyboardOptions>({
    name: 'customKeyboardHandling',
    priority: 1000,

    addKeyboardShortcuts() {
        return {
            Enter: ({ editor }) => {
                // Don't handle Enter if Shift is pressed
                if (this.editor.view.state.selection.$anchor.pos !== this.editor.view.state.selection.$head.pos) {
                    return false; // Let default behavior handle text selection
                }
                
                if (hasActualContent(editor)) {
                    // Create and dispatch a native Event instead of CustomEvent
                    const sendEvent = new Event('custom-send-message', {
                        bubbles: true,    // Allow event to bubble up
                        cancelable: true   // Allow event to be cancelled
                    });
                    
                    // Dispatch the event directly on the editor's DOM element
                    editor.view.dom.dispatchEvent(sendEvent);
                    return true;
                } else {
                    vibrateMessageField();
                    return true;
                }
            },
            'Shift-Enter': ({ editor }) => {
                return editor.commands.enter(); // Use native enter command for line breaks
            },
        };
    },
});

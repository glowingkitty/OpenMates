// src/components/MessageInput/extensions/Keyboard.ts
import { Extension } from '@tiptap/core';
import { hasActualContent } from '../utils/editorHelpers';
import { vibrateMessageField } from '../utils/vibrationHelpers'; // Corrected import

export interface KeyboardOptions {}

export const CustomKeyboardHandling = Extension.create<KeyboardOptions>({
    name: 'customKeyboardHandling',
    priority: 1000,

    addKeyboardShortcuts() {
        return {
            Enter: ({ editor }) => {
                if (hasActualContent(editor)) {
                    const sendEvent = new CustomEvent('custom-send-message');
                    editor.view.dom.dispatchEvent(sendEvent);
                } else {
                    vibrateMessageField();
                }
                return true;
            },
            'Shift-Enter': ({ editor }) => {
                return editor.commands.insertContent('<br>'); // alternative to hard break via editor.chain().focus().enter().run();
            },
        };
    },
});

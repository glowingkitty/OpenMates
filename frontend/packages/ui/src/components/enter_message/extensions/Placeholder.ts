// src/components/MessageInput/extensions/Placeholder.ts
import Placeholder from '@tiptap/extension-placeholder';
import { isContentEmptyExceptMention } from '../utils/editorHelpers';
import type { Editor } from '@tiptap/core';
import type { PlaceholderOptions } from '@tiptap/extension-placeholder';
import { get } from 'svelte/store';
import { writable } from 'svelte/store';
import { text } from '@repo/ui'; // Use text store from @repo/ui for reactive translations

export const messageInputPlaceholderOverride = writable<string | null>(null);

// Helper function to detect touch device
const isTouchDevice = () => {
    return (('ontouchstart' in window) ||
            (navigator.maxTouchPoints > 0) ||
            // @ts-expect-error -- msMaxTouchPoints is a non-standard MS property
            (navigator.msMaxTouchPoints > 0));
};

export const CustomPlaceholder = Placeholder.extend<PlaceholderOptions>({
    addOptions() {
        return {
            ...this.parent?.(),
            placeholder: ({ editor }: { editor: Editor }) => {
                // Only show placeholder when empty or just has mention and not focused
                if ((editor.isEmpty || isContentEmptyExceptMention(editor)) && !editor.isFocused) {
                    const override = get(messageInputPlaceholderOverride);
                    if (override) {
                        return override;
                    }

                    // Get appropriate translation based on device type
                    // Use text store from @repo/ui which is reactive to language changes
                    const key = isTouchDevice() ? 
                        'enter_message.placeholder.touch' : 
                        'enter_message.placeholder.desktop';
                    // Get the current value from the text store (reactive to language changes)
                    const translateFn = get(text);
                    return translateFn(key);
                }
                return '';
            },
            emptyEditorClass: 'is-editor-empty',
            showOnlyWhenEditable: false,
        } as PlaceholderOptions;
    },
});

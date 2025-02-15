// src/components/MessageInput/extensions/Placeholder.ts
import Placeholder from '@tiptap/extension-placeholder';
import { isContentEmptyExceptMention } from '../utils/editorHelpers';
import type { Editor } from '@tiptap/core';
import type { PlaceholderOptions } from '@tiptap/extension-placeholder';
import { get } from 'svelte/store';
import { _ } from 'svelte-i18n';

// Helper function to detect touch device
const isTouchDevice = () => {
    return (('ontouchstart' in window) ||
            (navigator.maxTouchPoints > 0) ||
            // @ts-ignore - MS specific property
            (navigator.msMaxTouchPoints > 0));
};

export const CustomPlaceholder = Placeholder.extend<PlaceholderOptions>({
    addOptions() {
        return {
            ...this.parent?.(),
            placeholder: ({ editor }: { editor: Editor }) => {
                // Only show placeholder when empty or just has mention and not focused
                if ((editor.isEmpty || isContentEmptyExceptMention(editor)) && !editor.isFocused) {
                    // Get appropriate translation based on device type
                    const key = isTouchDevice() ? 
                        'enter_message.placeholder.touch.text' : 
                        'enter_message.placeholder.desktop.text';
                    return get(_)(key);
                }
                return '';
            },
            emptyEditorClass: 'is-editor-empty',
            showOnlyWhenEditable: true,
        };
    },
});
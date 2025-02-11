// src/components/MessageInput/extensions/Placeholder.ts
import Placeholder from '@tiptap/extension-placeholder';
import { isContentEmptyExceptMention } from '../utils/editorHelpers';
import type { Editor } from '@tiptap/core';
import type { PlaceholderOptions } from '@tiptap/extension-placeholder';

export const CustomPlaceholder = Placeholder.extend<PlaceholderOptions>({
    addOptions() {
        return {
            ...this.parent?.(),
            placeholder: ({ editor }: { editor: Editor }) => {
                return (editor.isEmpty || isContentEmptyExceptMention(editor)) && !editor.isFocused
                    ? 'Click to enter message...' // Replace with your i18n
                    : '';
            },
            emptyEditorClass: 'is-editor-empty',
            showOnlyWhenEditable: true,
        };
    },
});
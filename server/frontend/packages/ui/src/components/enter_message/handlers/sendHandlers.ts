import type { Editor } from '@tiptap/core';
import { hasActualContent, vibrateMessageField } from '../utils';
import { createMessagePayload, resetEditorContent } from '../utils/messageHelpers';

/**
 * Handles sending a message via the message input
 * @param editor The TipTap editor instance
 * @param defaultMention Default mention to add after sending
 * @param dispatch Svelte dispatch function for events
 * @param setHasContent Function to update hasContent state
 */
export function handleSend(
    editor: Editor | null,
    defaultMention: string,
    dispatch: (type: string, detail?: any) => void,
    setHasContent: (value: boolean) => void
) {
    if (!editor || !hasActualContent(editor)) {
        vibrateMessageField();
        return;
    }
    
    const messagePayload = createMessagePayload(editor);
    dispatch("sendMessage", messagePayload);
    setHasContent(false);

    // Reset content and add mate node
    resetEditorContent(editor, defaultMention);
}

/**
 * Clears the message field and resets it to initial state
 * @param editor The TipTap editor instance
 * @param defaultMention Default mention to add after clearing
 */
export function clearMessageField(editor: Editor | null, defaultMention: string) {
    if (!editor) return;
    resetEditorContent(editor, defaultMention);
}

/**
 * Sets draft content in the message field
 * @param editor The TipTap editor instance
 * @param content Content to set as draft
 */
export function setDraftContent(editor: Editor | null, content: string) {
    if (!editor) return;
    editor.commands.setContent({
        type: 'doc',
        content: [{
            type: 'paragraph',
            content: [
                { type: 'text', text: content }
            ]
        }]
    });
    editor.commands.focus('end');
} 
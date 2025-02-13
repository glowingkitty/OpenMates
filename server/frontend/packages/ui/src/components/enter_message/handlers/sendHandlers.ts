import type { Editor } from '@tiptap/core';
import { hasActualContent, vibrateMessageField } from '../utils';
import { convertToMarkdown } from '../utils/editorHelpers';

/**
 * Creates a message payload from the editor content
 * @param editor The TipTap editor instance
 * @returns Message payload object with all message parts
 */
function createMessagePayload(editor: Editor) {
    const messagePayload = {
        id: crypto.randomUUID(),
        role: "user",
        messageParts: [] as { 
            type: string; 
            content?: string; 
            url?: string; 
            filename?: string; 
            id?: string; 
            duration?: string; 
            latitude?: number; 
            longitude?: number; 
            address?: string; 
            language?: string; 
            bookname?: string; 
            author?: string; 
        }[]
    };

    editor.state.doc.content.forEach(node => {
        if (node.type.name === 'paragraph') {
            const textContent = node.textContent;
            const markdownContent = convertToMarkdown(textContent);
            messagePayload.messageParts.push({
                type: 'text',
                content: markdownContent
            });
        } else if (node.type.name === 'webPreview') {
            messagePayload.messageParts.push({
                type: 'web',
                url: node.attrs.url,
                id: node.attrs.id
            });
        } else if (node.type.name === 'imageEmbed') {
            messagePayload.messageParts.push({
                type: 'image',
                filename: node.attrs.filename,
                id: node.attrs.id
            });
        } else if (node.type.name === 'videoEmbed') {
            messagePayload.messageParts.push({
                type: 'video',
                filename: node.attrs.filename,
                id: node.attrs.id,
                duration: node.attrs.duration
            });
        } else if (node.type.name === 'mate') {
            const textContent = `@${node.attrs.name} `;
            messagePayload.messageParts.push({
                type: 'text',
                content: textContent
            });
        } else if (node.type.name === 'codeEmbed') {
            messagePayload.messageParts.push({
                type: 'code',
                filename: node.attrs.filename,
                language: node.attrs.language,
                id: node.attrs.id,
                content: node.attrs.content
            });
        } else if (node.type.name === 'audioEmbed') {
            messagePayload.messageParts.push({
                type: 'audio',
                filename: node.attrs.filename,
                duration: node.attrs.duration,
                id: node.attrs.id
            });
        } else if (node.type.name === 'recordingEmbed') {
            messagePayload.messageParts.push({
                type: 'audio',
                filename: node.attrs.filename,
                duration: node.attrs.duration,
                id: node.attrs.id
            });
        } else if (node.type.name === 'fileEmbed') {
            messagePayload.messageParts.push({
                type: 'file',
                filename: node.attrs.filename,
                id: node.attrs.id
            });
        } else if (node.type.name === 'pdfEmbed') {
            messagePayload.messageParts.push({
                type: 'pdf',
                filename: node.attrs.filename,
                id: node.attrs.id
            });
        } else if (node.type.name === 'bookEmbed') {
            messagePayload.messageParts.push({
                type: 'book',
                filename: node.attrs.filename,
                id: node.attrs.id,
                bookname: node.attrs.bookname,
                author: node.attrs.author
            });
        } else if(node.type.name === 'textEmbed'){
            const textContent = node.attrs.content;
            const markdownContent = convertToMarkdown(textContent);
            messagePayload.messageParts.push({
                type: 'text',
                content: markdownContent
            });
        }
    });

    return messagePayload;
}

/**
 * Resets the editor content with a default mate mention
 * @param editor The TipTap editor instance
 * @param defaultMention The default mention to add
 */
function resetEditorContent(editor: Editor, defaultMention: string = 'sophia') {
    editor.commands.clearContent();

    // Add mate node and space after clearing
    setTimeout(() => {
        editor.commands.setContent({
            type: 'doc',
            content: [{
                type: 'paragraph',
                content: [
                    {
                        type: 'mate',
                        attrs: {
                            name: defaultMention,
                            id: crypto.randomUUID()
                        }
                    },
                    {
                        type: 'text',
                        text: ' '
                    }
                ]
            }]
        });
        editor.commands.focus('end');
    }, 0);
}

/**
 * Handles sending a message via the message input
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
import type { Editor } from '@tiptap/core';
import { hasActualContent, vibrateMessageField } from '../utils';
import { convertToMarkdown } from '../utils/editorHelpers';
import { Extension } from '@tiptap/core';

/**
 * Creates a message payload from the editor content
 * @param editor The TipTap editor instance
 * @returns Message payload object with message content
 */
function createMessagePayload(editor: Editor) {
    const content = editor.getJSON();
    
    // Validate content structure
    if (!content || !content.type || content.type !== 'doc' || !content.content) {
        console.error('Invalid editor content structure:', content);
        throw new Error('Invalid editor content');
    }

    const messagePayload = {
        id: crypto.randomUUID(),
        role: "user",
        content
    };

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
    console.debug('Sending message with content:', messagePayload);
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
 * Creates a custom keyboard extension for handling Enter key events in the editor
 * @returns TipTap extension for custom keyboard handling
 */
export function createKeyboardHandlingExtension() {
    return Extension.create({
        name: 'customKeyboardHandling',
        priority: 1000,

        addKeyboardShortcuts() {
            return {
                // Handle regular Enter press
                Enter: ({ editor }) => {
                    // Don't handle Enter if Shift is pressed
                    if (this.editor.view.state.selection.$anchor.pos !== 
                        this.editor.view.state.selection.$head.pos) {
                        return false; // Let default behavior handle text selection
                    }

                    if (hasActualContent(editor)) {
                        // Create and dispatch a native Event for sending message
                        const sendEvent = new Event('custom-send-message', {
                            bubbles: true,    // Allow event to bubble up
                            cancelable: true   // Allow event to be cancelled
                        });

                        // Dispatch the event on the editor's DOM element
                        editor.view.dom.dispatchEvent(sendEvent);
                        return true;
                    } else {
                        vibrateMessageField();
                        return true;
                    }
                },

                // Handle Shift+Enter for line breaks
                'Shift-Enter': () => {
                    // Return false to let TipTap handle the default line break behavior
                    return false;
                },
            };
        },
    });
} 
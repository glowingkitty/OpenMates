import type { Editor } from '@tiptap/core';
import { hasActualContent, vibrateMessageField } from '../utils';
import { convertToMarkdown } from '../utils/editorHelpers';
import { Extension } from '@tiptap/core';
import { chatDB } from '../../../services/db';
import { getApiEndpoint, apiEndpoints } from '../../../config/api';

async function sendMessageToAPI(chatId: string, content: any): Promise<Response> {
    const response = await fetch(getApiEndpoint(apiEndpoints.chat.sendMessage), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            chatId,
            content
        })
    });

    if (!response.ok) {
        throw new Error('Failed to send message');
    }

    return response;
}

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

    return {
        id: crypto.randomUUID(),
        role: "user",
        content,
        status: 'pending' as const,
        timestamp: Date.now()
    };
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
export async function handleSend(
    editor: Editor | null,
    defaultMention: string,
    dispatch: (type: string, detail?: any) => void,
    setHasContent: (value: boolean) => void,
    currentChatId?: string
) {
    if (!editor || !hasActualContent(editor) || !currentChatId) {
        vibrateMessageField();
        return;
    }

    const messagePayload = createMessagePayload(editor);

    try {
        // Save to database with pending status
        const updatedChat = await chatDB.addMessage(currentChatId, messagePayload);
        
        // Reset editor immediately
        resetEditorContent(editor, defaultMention);
        setHasContent(false);
        
        // First dispatch to update UI
        dispatch("sendMessage", messagePayload);
        dispatch("chatUpdated", { chat: updatedChat });

        // Send to API asynchronously
        sendMessageToAPI(currentChatId, messagePayload.content)
            .then(async () => {
                const chatWithUpdatedStatus = await chatDB.updateMessageStatus(currentChatId, messagePayload.id, 'sent');
                
                // Create a global event that any component can listen to
                const event = new CustomEvent('messageStatusChanged', {
                    detail: { chatId: currentChatId, messageId: messagePayload.id, status: 'sent', chat: chatWithUpdatedStatus },
                    bubbles: true,
                });
                window.dispatchEvent(event);
            })
            .catch(async (error) => {
                console.error('Failed to send message to API:', error);
                console.log('Message content that failed to send:', {
                    chatId: currentChatId,
                    content: messagePayload.content
                });
                
                const chatWithUpdatedStatus = await chatDB.updateMessageStatus(currentChatId, messagePayload.id, 'waiting_for_internet');
                
                // Create a global event for the status change
                const event = new CustomEvent('messageStatusChanged', {
                    detail: { chatId: currentChatId, messageId: messagePayload.id, status: 'waiting_for_internet', chat: chatWithUpdatedStatus },
                    bubbles: true,
                });
                window.dispatchEvent(event);
            });
    } catch (error) {
        console.error('Failed to save message to local database:', error);
        vibrateMessageField();
    }
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
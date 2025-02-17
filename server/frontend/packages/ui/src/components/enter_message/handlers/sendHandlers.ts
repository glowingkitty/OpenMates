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
        timestamp: new Date() // Change to Date object
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
 * Combines new content with existing message content
 */
function combineMessageContent(existingContent: any, newContent: any): any {
    // Ensure both contents have the expected structure
    if (!existingContent?.content || !newContent?.content) {
        throw new Error('Invalid content structure');
    }

    // Create a deep copy of existing content
    const combinedContent = JSON.parse(JSON.stringify(existingContent));

    // Simply concatenate the new content's paragraphs
    combinedContent.content = combinedContent.content.concat(newContent.content);

    return combinedContent;
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

    try {
        const chat = await chatDB.getChat(currentChatId);
        if (!chat) throw new Error('Chat not found');

        const pendingMessage = chat.messages.find(m => 
            m.status === 'pending' || m.status === 'waiting_for_internet'
        );

        const newContent = editor.getJSON();
        let messagePayload;

        // Clear draft status when sending a message
        if (chat.isDraft) {
            await chatDB.removeDraft(currentChatId);
        }

        if (pendingMessage) {
            // Combine the new content with the pending message
            const combinedContent = combineMessageContent(pendingMessage.content, newContent);
            messagePayload = {
                ...pendingMessage,
                content: combinedContent,
                status: 'pending' as const,
                timestamp: new Date()
            };

            // Reset editor before database update
            resetEditorContent(editor, defaultMention);
            setHasContent(false);

            // Update existing message in database
            const updatedChat = await chatDB.updateMessage(currentChatId, messagePayload);
            
            // Force immediate UI update
            dispatch("chatUpdated", { chat: updatedChat });
            
            // Notify all components of the update
            window.dispatchEvent(new CustomEvent('chatUpdated', {
                detail: { chat: updatedChat },
                bubbles: true
            }));

            // Attempt to send to API
            try {
                await sendMessageToAPI(currentChatId, messagePayload.content);
                const chatWithUpdatedStatus = await chatDB.updateMessageStatus(currentChatId, messagePayload.id, 'sent');
                
                window.dispatchEvent(new CustomEvent('messageStatusChanged', {
                    detail: { 
                        chatId: currentChatId, 
                        messageId: messagePayload.id, 
                        status: 'sent', 
                        chat: chatWithUpdatedStatus 
                    },
                    bubbles: true
                }));
            } catch (error) {
                console.error('Failed to send message to API:', error);
                const chatWithUpdatedStatus = await chatDB.updateMessageStatus(
                    currentChatId, 
                    messagePayload.id, 
                    'waiting_for_internet'
                );
                
                window.dispatchEvent(new CustomEvent('messageStatusChanged', {
                    detail: { 
                        chatId: currentChatId, 
                        messageId: messagePayload.id, 
                        status: 'waiting_for_internet', 
                        chat: chatWithUpdatedStatus 
                    },
                    bubbles: true
                }));
            }
        } else {
            // Create new message
            messagePayload = createMessagePayload(editor);
            
            // Add to database and get updated chat
            const updatedChat = await chatDB.addMessage(currentChatId, messagePayload);
            
            // Reset editor
            resetEditorContent(editor, defaultMention);
            setHasContent(false);

            // Update UI with both message and chat
            dispatch("sendMessage", messagePayload);
            dispatch("chatUpdated", { chat: updatedChat });
        }

    } catch (error) {
        console.error('Failed to handle message:', error);
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
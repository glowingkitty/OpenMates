import type { Editor } from '@tiptap/core';
import { hasActualContent, vibrateMessageField } from '../utils';
import { convertToMarkdown } from '../utils/editorHelpers';
import { Extension } from '@tiptap/core';
import { chatDB } from '../../../services/db';
import { chatSyncService } from '../../../services/chatSyncService'; // Import chatSyncService
import type { Message } from '../../../types/chat'; // Import Message type
import { draftEditorUIState } from '../../../services/drafts/draftState';

// Removed sendMessageToAPI as it will be handled by chatSyncService

/**
 * Creates a message payload from the editor content
 * @param editor The TipTap editor instance
 * @param chatId The ID of the current chat
 * @returns Message payload object with message content
 */
function createMessagePayload(editor: Editor, chatId: string): Message {
    const content = editor.getJSON();
    
    // Validate content structure
    if (!content || !content.type || content.type !== 'doc' || !content.content) {
        console.error('Invalid editor content structure:', content);
        throw new Error('Invalid editor content');
    }

    const message_id = `${chatId.slice(-10)}-${crypto.randomUUID()}`;

    return {
        message_id,
        chat_id: chatId,
        sender: "user", // 'sender' instead of 'role'
        content,
        status: 'sending', // Initial status
        timestamp: Math.floor(Date.now() / 1000) // Unix timestamp in seconds
    };
}

/**
 * Resets the editor content with a default mate mention
 * @param editor The TipTap editor instance
 * @param defaultMention The default mention to add
 */
function resetEditorContent(editor: Editor, defaultMention?: string) { // defaultMention is effectively unused now
    // Clear the content. The `false` argument prevents triggering an 'update' event from this specific command.
    // Tiptap's Placeholder extension should handle showing placeholder text if the editor is empty.
    editor.commands.clearContent(false);
    editor.commands.focus('end');
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
    if (!editor || !hasActualContent(editor)) {
        vibrateMessageField();
        return;
    }

    let chatIdToUse = currentChatId;
    let chatToUpdate: import('../../../types/chat').Chat | null = null;

    try {
        // If no chatId, create a new chat
        if (!chatIdToUse) {
            const newChatId = crypto.randomUUID();
            const now = new Date();
            const nowTimestamp = Math.floor(now.getTime() / 1000);
            const contentJSON = editor.getJSON();
            
            const newChat: import('../../../types/chat').Chat = {
                chat_id: newChatId,
                title: null, // New chats start without a title; it's set by the server or later by user
                messages_v: 0,
                title_v: 0,
                draft_v: 0,
                draft_json: null,
                last_edited_overall_timestamp: nowTimestamp,
                unread_count: 0,
                messages: [],
                createdAt: now,
                updatedAt: now,
            };
            await chatDB.addChat(newChat);
            chatIdToUse = newChat.chat_id;
            chatToUpdate = newChat;
            draftEditorUIState.update(s => ({ ...s, newlyCreatedChatIdToSelect: chatIdToUse }));
            console.info(`[handleSend] Created new local chat ${chatIdToUse} for sending message, flagged for selection.`);
        } else {
            chatToUpdate = await chatDB.getChat(chatIdToUse);
        }

        if (!chatIdToUse) {
            console.error('[handleSend] Critical: chatIdToUse is still undefined after attempting to create/get chat.');
            vibrateMessageField();
            return;
        }

        // Create new message
        const messagePayload = createMessagePayload(editor, chatIdToUse);
        
        // Add to local IndexedDB first
        const updatedChatWithNewMessage = await chatDB.addMessageToChat(chatIdToUse, messagePayload);
        
        // Set hasContent to false first to prevent race conditions with editor updates
        setHasContent(false);
        // Reset editor
        resetEditorContent(editor, defaultMention);

        // Dispatch for UI update (ActiveChat will pick this up)
        dispatch("sendMessage", messagePayload);

        if (updatedChatWithNewMessage) {
            // Dispatch chatUpdated so other parts of the UI (like chat list) can update if needed
             dispatch("chatUpdated", { chat: updatedChatWithNewMessage });
             // Also dispatch a window event for global listeners
            window.dispatchEvent(new CustomEvent('chatUpdated', {
                detail: { chat: updatedChatWithNewMessage },
                bubbles: true,
                composed: true
            }));
        }


        // Send message to backend via chatSyncService
        await chatSyncService.sendNewMessage(messagePayload);
        console.debug('[handleSend] Message sent to chatSyncService:', messagePayload);


    } catch (error) {
        console.error('Failed to handle message send:', error);
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
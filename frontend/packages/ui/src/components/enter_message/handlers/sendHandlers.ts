import type { Editor } from '@tiptap/core';
import { get } from 'svelte/store'; // Import get
import { hasActualContent, vibrateMessageField } from '../utils';
import { convertToMarkdown } from '../utils/editorHelpers';
import { Extension } from '@tiptap/core';
import { chatDB } from '../../../services/db';
import { chatSyncService } from '../../../services/chatSyncService'; // Import chatSyncService
import type { Message } from '../../../types/chat'; // Import Message type
import { draftEditorUIState } from '../../../services/drafts/draftState';
import { clearCurrentDraft } from '../../../services/drafts/draftSave'; // Import clearCurrentDraft

// Removed sendMessageToAPI as it will be handled by chatSyncService

/**
 * Creates a message payload from the editor content
 * @param editor The TipTap editor instance
 * @param chatId The ID of the current chat
 * @param currentChatTitle Optional: The current title of the chat
 * @returns Message payload object with message content
 */
function createMessagePayload(editor: Editor, chatId: string, currentChatTitle?: string | null): Message {
    const content = editor.getJSON();
    
    // Validate content structure
    if (!content || !content.type || content.type !== 'doc' || !content.content) {
        console.error('Invalid editor content structure:', content);
        throw new Error('Invalid editor content');
    }

    const message_id = `${chatId.slice(-10)}-${crypto.randomUUID()}`;

    const message: Message = {
        message_id,
        chat_id: chatId,
        role: "user", // Changed from sender to role
        content,
        status: 'sending', // Initial status
        timestamp: Math.floor(Date.now() / 1000) // Unix timestamp in seconds
    };

    if (currentChatTitle) {
        message.current_chat_title = currentChatTitle;
    }

    return message;
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
    let isNewChatCreation = false;
    let messagePayload: Message; // Defined here to be accessible for sendNewMessage

    try {
        if (!chatIdToUse) {
            chatIdToUse = crypto.randomUUID();
            isNewChatCreation = true;
        }

        // Fetch current chat title if chatIdToUse is available (for existing chats)
        let currentTitle: string | null = null;
        if (chatIdToUse && !isNewChatCreation) {
            const chatDetails = await chatDB.getChat(chatIdToUse);
            if (chatDetails) {
                currentTitle = chatDetails.title;
            }
        }

        // Create new message payload using the determined chatIdToUse and currentTitle
        messagePayload = createMessagePayload(editor, chatIdToUse, currentTitle);
        
        if (isNewChatCreation) {
            const now = new Date();
            const newChatData: import('../../../types/chat').Chat = {
                chat_id: chatIdToUse,
                title: null, // New chats start without a title
                messages_v: 1, // A new chat with its first message starts at version 1
                title_v: 0,
                draft_v: 0,
                draft_json: null,
                last_edited_overall_timestamp: messagePayload.timestamp, // Use message timestamp
                unread_count: 0,
                // messages: [messagePayload], // REMOVED: Chat type doesn't store messages directly
                createdAt: now,
                updatedAt: now,
            };
            await chatDB.addChat(newChatData); // Save new chat metadata
            await chatDB.saveMessage(messagePayload); // Save the first message separately
            
            // Fetch the chat again to ensure we have the consistent DB version for chatToUpdate
            // This also ensures chatToUpdate has the correct messages_v (which is 1)
            chatToUpdate = await chatDB.getChat(chatIdToUse); 
            if (!chatToUpdate) {
                 console.error(`[handleSend] CRITICAL: Newly created chat ${chatIdToUse} not found in DB immediately after addChat and saveMessage.`);
                 vibrateMessageField();
                 return;
            }
            // No need to update messages_v again here as it's set to 1 during newChatData creation

            console.info(`[handleSend] Created new local chat ${chatIdToUse} and saved its first message (messages_v should be 1).`);
        } else {
            // Existing chat: Save the new message and update chat metadata
            await chatDB.saveMessage(messagePayload);
            const existingChat = await chatDB.getChat(chatIdToUse);
            if (existingChat) {
                existingChat.messages_v = (existingChat.messages_v || 0) + 1;
                existingChat.last_edited_overall_timestamp = messagePayload.timestamp;
                existingChat.updatedAt = new Date();
                await chatDB.updateChat(existingChat);
                chatToUpdate = existingChat;
            } else {
                console.error(`[handleSend] Existing chat ${chatIdToUse} not found when trying to add a message.`);
                vibrateMessageField();
                return; // Early exit if chat doesn't exist
            }
        }

        // If chatToUpdate is null at this point, the local DB operation failed.
        if (!chatToUpdate) {
            console.error(`[handleSend] Failed to update local chat ${chatIdToUse} with new message. Aborting send.`);
            vibrateMessageField();
            return;
        }
        
        // Set hasContent to false first to prevent race conditions with editor updates
        setHasContent(false);
        // Reset editor
        resetEditorContent(editor, defaultMention);

        // Dispatch for UI update (ActiveChat will pick this up)
        // The messagePayload is already defined and includes the correct chat_id
        // If it's a new chat (isNewChatCreation is true), chatToUpdate will hold the new Chat object.
        dispatch("sendMessage", { message: messagePayload, newChat: isNewChatCreation ? chatToUpdate : undefined });

        // chatToUpdate should be the definitive version of the chat from the DB
        // The 'chatUpdated' event is still useful for other components like the chat list.
        if (chatToUpdate) {
            // Dispatch chatUpdated so other parts of the UI (like chat list) can update if needed
            // This local dispatch is for MessageInput's parent (ActiveChat)
            dispatch("chatUpdated", { chat: chatToUpdate }); 

            // If a new chat was created, signal it through draftEditorUIState
            // This is what Chats.svelte listens to for selecting new chats.
            if (isNewChatCreation) {
                draftEditorUIState.update(state => ({ ...state, newlyCreatedChatIdToSelect: chatIdToUse }));
                console.info(`[handleSend] Signaled new chat ${chatIdToUse} for selection via draftEditorUIState.`);
            } else {
                // For existing chats, ensure chatSyncService knows about the local update
                // so it can propagate to Chats.svelte if necessary, or handle consistency.
                // A more direct way for Chats.svelte to react to local DB changes might be needed
                // if chatSyncService events are strictly for server-originated changes.
                // For now, we rely on draftEditorUIState for new chats, and existing chat updates
                // should be picked up by Chats.svelte if it re-queries DB on 'chatUpdated' from ActiveChat.
                 window.dispatchEvent(new CustomEvent('chatUpdated', { // This helps Chats.svelte if it listens globally or via ActiveChat relay
                    detail: { chat_id: chatToUpdate.chat_id, chat: chatToUpdate }, // Ensure chat_id is at top level for some handlers
                    bubbles: true,
                    composed: true
                }));
            }
        }


        // Send message to backend via chatSyncService
        await chatSyncService.sendNewMessage(messagePayload);
        console.debug('[handleSend] Message sent to chatSyncService:', messagePayload);

        // After successfully sending the message, clear the draft for this chat
        // Ensure we only clear if the message was for the chat currently in the draft editor's context
        const currentDraftState = get(draftEditorUIState);
        if (chatIdToUse && currentDraftState.currentChatId === chatIdToUse) {
            console.info(`[handleSend] Message sent for chat ${chatIdToUse}, clearing its draft.`);
            await clearCurrentDraft();
        } else {
            // This case might happen if a message is sent for a chat that isn't the one
            // currently active in the MessageInput's draft context (e.g., programmatic send).
            // Or if a new chat was just created, the draft context might not be set yet,
            // but clearCurrentDraft relies on draftEditorUIState.currentChatId.
            // If it's a new chat, there shouldn't be a draft to clear anyway.
            // If it's an existing chat but not the one in draft context, we might not want to clear its draft.
            // The current logic of clearCurrentDraft uses draftEditorUIState.currentChatId,
            // so if chatIdToUse is different, it won't clear the draft of chatIdToUse unless
            // draftEditorUIState.currentChatId happens to be chatIdToUse.
            // This seems fine for now, as sending a message typically implies the chat is active.
            console.debug(`[handleSend] Message sent for chat ${chatIdToUse}, but draft context is ${currentDraftState.currentChatId}. Draft clear skipped or handled by clearCurrentDraft's internal logic.`);
        }

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

import { debounce, isEqual } from 'lodash-es'; // Import isEqual
import { get } from 'svelte/store';
import { chatDB } from '../db';
import { webSocketService } from '../websocketService';
import { websocketStatus, type WebSocketStatus } from '../../stores/websocketStatusStore';
import type { Chat, TiptapJSON, OfflineChange } from '../../types/chat';
import { isContentEmptyExceptMention } from '../../components/enter_message/utils';
import { draftEditorUIState, initialDraftEditorState } from './draftState'; // Renamed import
import { LOCAL_CHAT_LIST_CHANGED_EVENT } from './draftConstants';
import { getEditorInstance, clearEditorAndResetDraftState } from './draftCore';
import { chatSyncService } from '../chatSyncService'; // Import the new service
import { tipTapToCanonicalMarkdown } from '../../message_parsing/serializers'; // Import markdown converter
import { encryptWithMasterKey, decryptWithMasterKey } from '../cryptoService'; // Import encryption functions

/**
 * Deletes the draft for the current chat and, if the chat becomes empty (no messages),
 * deletes the chat as well. Handles local DB operations and server communication.
 */
export async function clearCurrentDraft() { // Export this function
    const editor = getEditorInstance(); // Keep reference to editor for the finally block
    if (!getEditorInstance()) { // Check against the live getter in case it's cleared elsewhere
        console.error('[DraftService] Cannot clear/delete draft, editor instance not available at start.');
        // If no editor, can't do much with it, but might still proceed with DB ops if chatId is known
    }

    const currentState = get(draftEditorUIState);
    const currentChatId = currentState.currentChatId;

    if (!currentChatId) {
        console.info('[DraftService] No current chat ID to clear/delete draft for.');
        if (editor) clearEditorAndResetDraftState(false); // Reset editor if it exists
        else draftEditorUIState.set(initialDraftEditorState); // Else, just reset state
        return;
    }

    console.info(`[DraftService] Attempting to delete draft for chat ID: ${currentChatId}`);

    try {
        // 1. Check if a draft actually exists before attempting to delete.
        const chatBeforeDraftDeletion = await chatDB.getChat(currentChatId);

        if (chatBeforeDraftDeletion && (chatBeforeDraftDeletion.encrypted_draft_md || (chatBeforeDraftDeletion.draft_v && chatBeforeDraftDeletion.draft_v > 0))) {
            console.info(`[DraftService] Draft found for chat ${currentChatId}. Requesting deletion via chatSyncService.`);
            // Inform the server to delete the draft
            // chatSyncService.sendDeleteDraft handles online/offline queuing internally
            await chatSyncService.sendDeleteDraft(currentChatId); // This will also dispatch 'chatUpdated' with 'draft_deleted'
        } else {
            console.info(`[DraftService] No draft found locally for chat ${currentChatId}. Skipping server deletion call. Will clear local draft state if any.`);
            // Even if no draft to delete on server, ensure local state is clean.
            // chatDB.clearCurrentUserChatDraft will ensure draft_json is null and draft_v is 0 or handled appropriately.
            // This is important if there was a local draft that wasn't synced or if state is inconsistent.
            const clearedChat = await chatDB.clearCurrentUserChatDraft(currentChatId);
            if (clearedChat) {
                 console.debug(`[DraftService] Optimistically cleared local draft remnants for chat ${currentChatId}`);
                 // Dispatch an event similar to what sendDeleteDraft would do for UI consistency
                 window.dispatchEvent(new CustomEvent('chatUpdated', { detail: { chat_id: currentChatId, type: 'draft_deleted' } }));
            }
        }
        
        // Update UI state for the draft (version, unsaved changes)
        // No need to update currentUserDraftVersion here if the chat context might change or be cleared.
        // If chat remains, its draft is gone. If chat is deleted, context is cleared.
        // hasUnsavedChanges should be false.
        draftEditorUIState.update(s => {
            if (s.currentChatId === currentChatId) {
                // If the current chat context is still the one whose draft was deleted
                return {
                    ...s,
                    currentUserDraftVersion: 0,
                    hasUnsavedChanges: false,
                    lastSavedContentMarkdown: null, // Reset last saved content
                };
            }
            return s; // Otherwise, no change to this specific part of the state
        });
        
        // Dispatch event for UI lists to update (e.g., remove draft indicator)
        // The 'chatUpdated' event from sendDeleteDraft might cover this, or a more specific one here.
        window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { detail: { chat_id: currentChatId, draftDeleted: true } }));

        // 2. Check if the chat itself should be deleted
        const chat = await chatDB.getChat(currentChatId); // Re-fetch chat state
        // Check if the chat has any messages by fetching them
        const messages = await chatDB.getMessagesForChat(currentChatId);
        if (chat && (!messages || messages.length === 0)) {
            console.info(`[DraftService] Chat ${currentChatId} has no messages after draft deletion. Attempting to delete chat.`);
            
            // chatSyncService.sendDeleteChat handles optimistic local DB deletion and server notification.
            await chatSyncService.sendDeleteChat(currentChatId); // This dispatches 'chatDeleted'
            console.info(`[DraftService] Initiated deletion of empty chat ${currentChatId}.`);
            
            // When chat is deleted, draft state (including currentChatId) should be fully reset.
            // The 'chatDeleted' event handler in UI (e.g., Chats.svelte) should manage selecting a new chat.
            // clearEditorAndResetDraftState will set currentChatId to null.
            clearEditorAndResetDraftState(false); 
        } else if (!chat) {
            console.warn(`[DraftService] Chat ${currentChatId} was not found after deleting its draft. Ensuring UI is reset.`);
            clearEditorAndResetDraftState(false); // Reset editor and draft UI state
        }
        // If chat exists and has messages, do nothing further to the chat itself.
        // The editor content for this chat should be cleared in the finally block.

    } catch (error) {
        console.error(`[DraftService] Error deleting draft or chat for ${currentChatId}:`, error);
        draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true })); 
    } finally {
        // This block ensures the editor UI is in a consistent state.
        const finalEditorState = get(draftEditorUIState);
        const liveEditorInstance = getEditorInstance(); // Get current editor instance

        if (finalEditorState.currentChatId === currentChatId) { 
            // If the context is still the (now draft-less) chat
            if (liveEditorInstance) {
                console.debug(`[DraftService] Draft deleted for chat ${currentChatId}, clearing editor content.`);
                liveEditorInstance.chain().clearContent(false).run(); // Clear content
                // Optionally set to an initial placeholder if desired, but clearContent is usually enough
                // liveEditorInstance.chain().setContent(getInitialContent(), false).run(); 
            }
        } else if (!finalEditorState.currentChatId) {
            // If currentChatId became null (e.g., chat deleted and state reset by clearEditorAndResetDraftState)
            // The editor should have been cleared by clearEditorAndResetDraftState.
            // If liveEditorInstance still exists and is not empty, clear it.
            if (liveEditorInstance && !liveEditorInstance.isEmpty) {
                 console.debug('[DraftService] Chat context cleared, ensuring editor is empty.');
                 liveEditorInstance.chain().clearContent(false).run();
            }
        }
        // If currentChatId changed to something else, that context switch (setCurrentChatContext) would handle editor content.
    }
}


/**
 * Saves the current editor content as a draft.
 * If content is empty, it triggers the modified clearCurrentDraft (which now deletes).
 * Handles local DB update and server communication (online/offline).
 */
export const saveDraftDebounced = debounce(async (chatIdFromMessageInput?: string) => {
    const editor = getEditorInstance();
    if (!editor) {
        console.error('[DraftService] Cannot save draft, editor instance not available.');
        return;
    }

    const currentState = get(draftEditorUIState);
    let currentChatIdForOperation = currentState.currentChatId;

    // Determine the definitive chat ID for this operation.
    // Priority:
    // 1. If internal state (currentState.currentChatId) is null (e.g., after chat deletion/reset),
    //    then any chatIdFromMessageInput is stale, and we must create a new chat.
    // 2. If internal state is not null, and chatIdFromMessageInput differs, align with MessageInput.
    // 3. Otherwise, use the existing currentState.currentChatId.
    if (chatIdFromMessageInput) {
        if (currentState.currentChatId === null) {
            // If MessageInput provides a chat ID but our state doesn't have one,
            // we should use the MessageInput's chat ID instead of creating a new chat
            console.info(`[DraftService] MessageInput has chatId (${chatIdFromMessageInput}) but draft context is null. Using MessageInput's chatId.`);
            currentChatIdForOperation = chatIdFromMessageInput;
            // Update the draft state to use the MessageInput's chat ID
            draftEditorUIState.update(s => ({
                ...s,
                currentChatId: chatIdFromMessageInput,
                currentUserDraftVersion: 0, // Reset version as we're setting a new context
                lastSavedContentMarkdown: null, // Reset last saved content
                newlyCreatedChatIdToSelect: null
            }));
        } else if (chatIdFromMessageInput !== currentState.currentChatId) {
            // MessageInput's context is different, and internal state is not null.
            // Align draft service's context with MessageInput.
            console.info(`[DraftService] Aligning draft operation context with MessageInput: ${chatIdFromMessageInput}. Previous draft state context: ${currentState.currentChatId}`);
            draftEditorUIState.update(s => ({
                ...s,
                currentChatId: chatIdFromMessageInput,
                currentUserDraftVersion: 0, // Reset version, as we are switching context
                lastSavedContentMarkdown: null, // Reset last saved, content will be compared anew
                newlyCreatedChatIdToSelect: null
            }));
            currentChatIdForOperation = chatIdFromMessageInput;
        }
        // If chatIdFromMessageInput is present and matches currentState.currentChatId,
        // currentChatIdForOperation is already correctly set from currentState.currentChatId.
    }
    // If chatIdFromMessageInput was null, currentChatIdForOperation remains whatever was in currentState.currentChatId.
    // Now currentChatIdForOperation is the one to use.
    // If chatIdFromMessageInput was null, currentChatIdForOperation remains what was in the state.

    const contentJSON = editor.getJSON() as TiptapJSON;
    
    // Convert TipTap content to markdown for storage
    const contentMarkdown = tipTapToCanonicalMarkdown(contentJSON);
    
    // Encrypt the markdown content with the user's master key
    const encryptedMarkdown = encryptWithMasterKey(contentMarkdown);
    if (!encryptedMarkdown) {
        console.error('[DraftService] Failed to encrypt draft content - master key not available');
        draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true }));
        return;
    }
    
    // Debug logging for draft updates
    console.log('💾 [DraftService] Saving draft as encrypted markdown:', {
        chatId: currentChatIdForOperation,
        cleartext: contentMarkdown,
        cleartextLength: contentMarkdown.length,
        encrypted: encryptedMarkdown.substring(0, 100) + '...',
        encryptedLength: encryptedMarkdown.length,
        tiptapJSON: contentJSON
    });

    // If content is empty, treat as clearing/deleting the draft
    if (editor.isEmpty || isContentEmptyExceptMention(editor)) {
        console.info('[DraftService] Editor content is empty. Triggering draft deletion process.');
        if (currentChatIdForOperation) { // Check the resolved ID
            // clearCurrentDraft reads from draftEditorUIState, which we've just updated if necessary.
            await clearCurrentDraft(); // This will also handle resetting lastSavedContentJSON
        } else {
            // If no chat context, just reset the UI editor and state
            clearEditorAndResetDraftState(false); // This should also reset lastSavedContentJSON via draftCore
        }
        return;
    }

    // Check if content has actually changed compared to the last saved version for this chat
    if (currentState.currentChatId === currentChatIdForOperation &&
        currentState.lastSavedContentMarkdown &&
        contentMarkdown === currentState.lastSavedContentMarkdown) {
        console.info(`[DraftService] Draft content for chat ${currentChatIdForOperation} is unchanged. Skipping save.`);
        // Ensure hasUnsavedChanges is false if content matches last save
        if (currentState.hasUnsavedChanges) {
            draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: false }));
        }
        return;
    }

    // Saving non-empty, changed content
    draftEditorUIState.update((s) => ({ ...s, hasUnsavedChanges: true }));

    let userDraft: Chat | null = null;
    let versionBeforeSave = 0;

    if (!currentChatIdForOperation) {
        // Create a new chat and its initial draft locally
        const newChat = await chatDB.createNewChatWithCurrentUserDraft(encryptedMarkdown);
        currentChatIdForOperation = newChat.chat_id; // Update for subsequent use in this function
        userDraft = newChat;
        draftEditorUIState.update(s => ({
            ...s,
            currentChatId: currentChatIdForOperation, // This is now the ID of the new chat
            currentUserDraftVersion: userDraft.draft_v,
            newlyCreatedChatIdToSelect: currentChatIdForOperation, // Signal UI to select this new chat
            hasUnsavedChanges: false,
            lastSavedContentMarkdown: contentMarkdown, // Store cleartext markdown for comparison
        }));
        console.info(`[DraftService] Created new local chat ${currentChatIdForOperation} with encrypted draft. Version: ${userDraft.draft_v}. Updated lastSavedContentMarkdown.`);
    } else {
        // Update existing draft for currentChatIdForOperation
        const existingChat = await chatDB.getChat(currentChatIdForOperation);
        
        if (!existingChat) {
            // Chat doesn't exist in local database - create a new one instead
            console.warn(`[DraftService] Chat ${currentChatIdForOperation} not found in local DB. Creating new chat instead.`);
            const newChat = await chatDB.createNewChatWithCurrentUserDraft(encryptedMarkdown);
            currentChatIdForOperation = newChat.chat_id; // Update to use the new chat ID
            userDraft = newChat;
            draftEditorUIState.update(s => ({
                ...s,
                currentChatId: currentChatIdForOperation, // Update to the new chat ID
                currentUserDraftVersion: userDraft.draft_v,
                newlyCreatedChatIdToSelect: currentChatIdForOperation, // Signal UI to select this new chat
                hasUnsavedChanges: false,
                lastSavedContentMarkdown: contentMarkdown, // Store cleartext markdown for comparison
            }));
            console.info(`[DraftService] Created new local chat ${currentChatIdForOperation} with encrypted draft. Version: ${userDraft.draft_v}. Updated lastSavedContentMarkdown.`);
        } else {
            // Chat exists - update it normally
            versionBeforeSave = existingChat.draft_v || 0;
            userDraft = await chatDB.saveCurrentUserChatDraft(currentChatIdForOperation, encryptedMarkdown);
            if (userDraft) {
                // currentChatId in state should already be currentChatIdForOperation due to earlier update or initial state
                draftEditorUIState.update(s => ({
                    ...s,
                    currentUserDraftVersion: userDraft.draft_v,
                    hasUnsavedChanges: false,
                    lastSavedContentMarkdown: contentMarkdown, // Store cleartext markdown for comparison
                }));
                console.info(`[DraftService] Saved encrypted draft locally for chat ${currentChatIdForOperation}, new version: ${userDraft.draft_v}. Updated lastSavedContentMarkdown.`);
            } else {
                console.error(`[DraftService] Failed to save draft locally for chat ${currentChatIdForOperation}.`);
                draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true }));
                return; // Stop if local save failed
            }
        }
    }

    if (!userDraft || !currentChatIdForOperation) {
        console.error("[DraftService] Critical error: UserDraft object or ID is null after local save attempt.");
        draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true }));
        return;
    }

    // Dispatch event for UI lists to update
    window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { detail: { chat_id: currentChatIdForOperation } }));

    // Send to server or queue if offline (send encrypted markdown to server)
    // NOTE: Local storage with encrypted content has already been completed above
    if (get(websocketStatus).status === 'connected') {
        try {
            // Send encrypted markdown to server for synchronization
            // The sendUpdateDraft function will NOT save to local database - that's already done above with encryption
            await chatSyncService.sendUpdateDraft(currentChatIdForOperation, encryptedMarkdown);
            console.info(`[DraftService] Sent encrypted draft to server for chat ${currentChatIdForOperation}.`);
        } catch (wsError) {
            console.error(`[DraftService] Error sending draft update via WS for chat ${currentChatIdForOperation}:`, wsError);
            draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true }));
        }
    } else {
        console.info(`[DraftService] WebSocket disconnected. Queuing draft update for chat ${currentChatIdForOperation}.`);
        const offlineChange: Omit<OfflineChange, 'change_id'> = {
            chat_id: currentChatIdForOperation,
            type: 'draft',
            value: contentMarkdown, // Send cleartext markdown to server when online
            version_before_edit: versionBeforeSave,
        };
        await chatSyncService.queueOfflineChange(offlineChange);
        draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true }));
    }
}, 1200);

/**
 * Triggers the debounced save/clear function. Called on editor updates.
 */
export function triggerSaveDraft(chatIdFromMessageInput?: string) {
    const editor = getEditorInstance();
    if (!editor) return;
    saveDraftDebounced(chatIdFromMessageInput);
}

/**
 * Immediately flushes any pending debounced save/clear operations.
 * Called on blur, visibilitychange, beforeunload.
 */
export function flushSaveDraft() {
    const editor = getEditorInstance();
    if (!editor) return;
    console.info('[DraftService] Flushing draft operation.');
    saveDraftDebounced.flush();
}

/**
 * Deletes the current chat.
 * This is a more explicit delete action than just clearing a draft.
 */
export async function deleteCurrentChat() {
    const currentState = get(draftEditorUIState); // Use renamed store
    const chatIdToDelete = currentState.currentChatId;

    if (!chatIdToDelete) {
        console.warn('[DraftService] No current chat selected to delete.');
        return;
    }

    console.info(`[DraftService] Attempting to delete chat: ${chatIdToDelete}`);

    try {
        // Optimistically clear editor and reset UI state FIRST, so user sees immediate effect.
        // clearEditorAndResetDraftState will set currentChatId to null.
        clearEditorAndResetDraftState(false); 

        // chatSyncService.sendDeleteChat handles local DB deletion and server notification.
        await chatSyncService.sendDeleteChat(chatIdToDelete);
        console.info(`[DraftService] Sent delete_chat request for ${chatIdToDelete}.`);
        // UI list update is handled by chatSyncService via 'chatDeleted' event or by Chats.svelte listening to DB changes.
        
    } catch (error) {
        console.error(`[DraftService] Error deleting chat ${chatIdToDelete}:`, error);
        // Handle error, maybe revert UI state if needed, though optimistic clear already happened.
        // If server fails, sync on reconnect should resolve.
        // For now, we assume the optimistic local clear is acceptable UX.
        // To be more robust, one might re-fetch chat list or show error.
    }
}

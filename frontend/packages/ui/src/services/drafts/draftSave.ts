import { debounce } from 'lodash-es';
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

/**
 * Deletes the draft for the current chat and, if the chat becomes empty (no messages),
 * deletes the chat as well. Handles local DB operations and server communication.
 */
async function clearCurrentDraft() {
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
        // 1. Inform the server to delete the draft.
        // chatSyncService.sendDeleteDraft is expected to handle the local DB update
        // (i.e., clearing draft_json and updating draft_v on the Chat object)
        // and then inform the server.
        // The original call to chatDB.deleteUserChatDraft(currentChatId) is removed
        // as that method no longer exists, and its function is subsumed by
        // the broader draft-in-chat model handled by chatSyncService.
        console.info(`[DraftService] Requesting draft deletion for chat ${currentChatId} via chatSyncService.`);
        
        // Inform the server to delete the draft
        // chatSyncService.sendDeleteDraft handles online/offline queuing internally
        await chatSyncService.sendDeleteDraft(currentChatId); // This will also dispatch 'chatUpdated' with 'draft_deleted'
        
        // Update UI state for the draft (version, unsaved changes)
        // No need to update currentUserDraftVersion here if the chat context might change or be cleared.
        // If chat remains, its draft is gone. If chat is deleted, context is cleared.
        // hasUnsavedChanges should be false.
        draftEditorUIState.update(s => ({
            ...s,
            // If currentChatId is still the same, its draft version is now effectively 0 or non-existent
            currentUserDraftVersion: s.currentChatId === currentChatId ? 0 : s.currentUserDraftVersion, 
            hasUnsavedChanges: false, 
        }));
        
        // Dispatch event for UI lists to update (e.g., remove draft indicator)
        // The 'chatUpdated' event from sendDeleteDraft might cover this, or a more specific one here.
        window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { detail: { chat_id: currentChatId, draftDeleted: true } }));

        // 2. Check if the chat itself should be deleted
        const chat = await chatDB.getChat(currentChatId); // Re-fetch chat state
        if (chat && (!chat.messages || chat.messages.length === 0)) {
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
export const saveDraftDebounced = debounce(async () => {
    const editor = getEditorInstance();
    if (!editor) {
        console.error('[DraftService] Cannot save draft, editor instance not available.');
        return;
    }

    const currentState = get(draftEditorUIState); // Use renamed store
    let currentChatId = currentState.currentChatId;
    const contentJSON = editor.getJSON() as TiptapJSON; // Cast to TiptapJSON

    // If content is empty, treat as clearing/deleting the draft
    if (editor.isEmpty || isContentEmptyExceptMention(editor)) {
        console.info('[DraftService] Editor content is empty. Triggering draft deletion process.');
        if (currentChatId) { // Only process if there's a chat context
            await clearCurrentDraft(); // This now handles deletion of draft and potentially chat
        } else {
            // If no chat context, just reset the UI editor and state
            clearEditorAndResetDraftState(false); 
        }
        return;
    }

    draftEditorUIState.update((s) => ({ ...s, hasUnsavedChanges: true })); // Use renamed store; Mark as unsaved initially

    let userDraft: Chat | null = null; // Changed type from UserChatDraft to Chat
    let versionBeforeSave = 0;

    if (!currentChatId) {
        // Create a new chat and its initial draft locally
        // createNewChatWithCurrentUserDraft now returns the full Chat object
        const newChat = await chatDB.createNewChatWithCurrentUserDraft(contentJSON);
        currentChatId = newChat.chat_id;
        userDraft = newChat; // Assign the full Chat object
        draftEditorUIState.update(s => ({ // Use renamed store
            ...s,
            currentChatId: currentChatId,
            currentUserDraftVersion: userDraft.draft_v, // Use draft_v from Chat object
            newlyCreatedChatIdToSelect: currentChatId, // Signal UI to select this new chat
            hasUnsavedChanges: false, // Optimistically false, will be true if offline queuing happens
        }));
        console.info(`[DraftService] Created new local chat ${currentChatId} with draft. Version: ${userDraft.draft_v}`);
    } else {
        // Get existing draft version before saving
        // getUserChatDraft no longer exists; get the full chat and access draft_v
        const existingChat = await chatDB.getChat(currentChatId);
        versionBeforeSave = existingChat?.draft_v || 0; // Use draft_v from Chat object

        // Update existing draft
        // saveCurrentUserChatDraft now updates the draft within the Chat object and returns the updated Chat
        userDraft = await chatDB.saveCurrentUserChatDraft(currentChatId, contentJSON);
        if (userDraft) {
            draftEditorUIState.update(s => ({ // Use renamed store
                ...s,
                currentUserDraftVersion: userDraft.draft_v, // Use draft_v from Chat object
                hasUnsavedChanges: false, // Optimistically false
            }));
            console.info(`[DraftService] Saved draft locally for chat ${currentChatId}, new version: ${userDraft.draft_v}.`);
        } else {
            console.error(`[DraftService] Failed to save draft locally for chat ${currentChatId}.`);
            draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true })); // Use renamed store; Revert to true if DB save failed
            return; // Stop if local save failed
        }
    }
    
    if (!userDraft || !currentChatId) {
        console.error("[DraftService] Critical error: UserDraft object or ID is null after local save attempt.");
        draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true })); // Use renamed store
        return;
    }

    // Dispatch event for UI lists to update
    window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { detail: { chat_id: currentChatId } }));

    // Send to server or queue if offline
    if (get(websocketStatus).status === 'connected') {
        try {
            await chatSyncService.sendUpdateDraft(currentChatId, contentJSON);
            console.info(`[DraftService] Sent update_draft to server for chat ${currentChatId}.`);
        } catch (wsError) {
            console.error(`[DraftService] Error sending draft update via WS for chat ${currentChatId}:`, wsError);
            draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true })); // Use renamed store; Mark unsaved on WS error
        }
    } else {
        console.info(`[DraftService] WebSocket disconnected. Queuing draft update for chat ${currentChatId}.`);
        const offlineChange: Omit<OfflineChange, 'change_id'> = {
            chat_id: currentChatId,
            type: 'draft',
            value: contentJSON,
            version_before_edit: versionBeforeSave,
        };
        await chatSyncService.queueOfflineChange(offlineChange);
        draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true })); // Use renamed store; Ensure it's marked unsaved
    }
}, 700);

/**
 * Triggers the debounced save/clear function. Called on editor updates.
 */
export function triggerSaveDraft() {
    const editor = getEditorInstance();
    if (!editor) return;
    saveDraftDebounced();
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
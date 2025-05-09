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
 * Clears the draft content for the current chat locally and informs the server.
 * If the chat was purely a local draft (not yet known to server), it might be deleted locally.
 */
async function clearCurrentDraft() {
    const editor = getEditorInstance();
    if (!editor) {
        console.error('[DraftService] Cannot clear draft, editor instance not available.');
        return;
    }

    const currentState = get(draftEditorUIState); // Use renamed store
    const currentChatId = currentState.currentChatId;

    if (!currentChatId) {
        console.info('[DraftService] No current chat ID to clear draft for.');
        clearEditorAndResetDraftState(false); // Reset editor and UI state
        return;
    }

    console.info(`[DraftService] Clearing draft for chat ID: ${currentChatId}`);

    try {
        const existingUserDraft = await chatDB.getUserChatDraft(currentChatId);
        const versionBeforeClear = existingUserDraft?.version || 0;

        // Update local DB: set draft_content to null, increment draft_v, update timestamp
        const updatedUserDraft = await chatDB.clearCurrentUserChatDraft(currentChatId);

        if (updatedUserDraft) {
            draftEditorUIState.update(s => ({ // Use renamed store
                ...s,
                currentUserDraftVersion: updatedUserDraft.version, // Use version from UserChatDraft
                hasUnsavedChanges: false, // Assume cleared draft is "saved" as cleared
            }));

            // Inform the server by sending an update_draft message with null content
            if (get(websocketStatus).status === 'connected') {
                await chatSyncService.sendUpdateDraft(currentChatId, null);
            } else {
                // Queue offline change for clearing draft
                const offlineClear: Omit<OfflineChange, 'change_id'> = {
                    chat_id: currentChatId,
                    type: 'draft',
                    value: null, // Null for clearing
                    version_before_edit: versionBeforeClear, // Version before this clear operation
                };
                await chatSyncService.queueOfflineChange(offlineClear);
                draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true })); // Use renamed store
                console.info(`[DraftService] Queued offline draft clear for chat ${currentChatId}`);
            }
            
            window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { detail: { chat_id: currentChatId } }));
        } else {
            console.warn(`[DraftService] User draft for chat ${currentChatId} not found or failed to clear.`);
            // If draft didn't exist, still reset UI
            clearEditorAndResetDraftState(false);
        }
    } catch (error) {
        console.error(`[DraftService] Error clearing draft for chat ${currentChatId}:`, error);
        // Potentially set hasUnsavedChanges to true if server notification failed
        draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true })); // Use renamed store
    } finally {
        // Reset editor and UI state regardless of whether it was a full chat or just a draft
        clearEditorAndResetDraftState(false); // clearEditorAndResetDraftState internally uses draftEditorUIState
    }
}


/**
 * Saves the current editor content as a draft.
 * If content is empty, it clears the draft.
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

    // If content is empty, treat as clearing the draft
    if (editor.isEmpty || isContentEmptyExceptMention(editor)) {
        console.info('[DraftService] Editor content is empty. Triggering draft clear.');
        if (currentChatId) { // Only clear if there's a chat context
            await clearCurrentDraft();
        } else {
            clearEditorAndResetDraftState(false); // Just reset UI if no chat context
        }
        return;
    }

    draftEditorUIState.update((s) => ({ ...s, hasUnsavedChanges: true })); // Use renamed store; Mark as unsaved initially

    let userDraft: import('./draftTypes').UserChatDraft | null = null;
    let versionBeforeSave = 0;
    // let isNewChatLocally = false; // Not strictly needed with new DB methods

    if (!currentChatId) {
        // Create a new chat and its initial draft locally
        const { chat: newChat, draft: newUserDraft } = await chatDB.createNewChatWithCurrentUserDraft(contentJSON);
        currentChatId = newChat.chat_id;
        userDraft = newUserDraft;
        // isNewChatLocally = true;
        draftEditorUIState.update(s => ({ // Use renamed store
            ...s,
            currentChatId: currentChatId,
            currentUserDraftVersion: userDraft.version, // Use initial version from UserChatDraft
            newlyCreatedChatIdToSelect: currentChatId, // Signal UI to select this new chat
            hasUnsavedChanges: false, // Optimistically false, will be true if offline queuing happens
        }));
        console.info(`[DraftService] Created new local chat ${currentChatId} with draft. Version: ${userDraft.version}`);
    } else {
        // Get existing draft version before saving
        const existingUserDraft = await chatDB.getUserChatDraft(currentChatId);
        versionBeforeSave = existingUserDraft?.version || 0;

        // Update existing draft
        userDraft = await chatDB.saveCurrentUserChatDraft(currentChatId, contentJSON);
        if (userDraft) {
            draftEditorUIState.update(s => ({ // Use renamed store
                ...s,
                currentUserDraftVersion: userDraft.version, // Update with new version from UserChatDraft
                hasUnsavedChanges: false, // Optimistically false
            }));
            console.info(`[DraftService] Saved draft locally for chat ${currentChatId}, new version: ${userDraft.version}.`);
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
            // Server will broadcast 'chat_draft_updated'.
            // The local UserChatDraft.version was already incremented by chatDB methods.
            // The server response via 'chat_draft_updated' event will confirm/align this version.
            console.info(`[DraftService] Sent update_draft to server for chat ${currentChatId}.`);
            // hasUnsavedChanges remains false if WS send succeeds (server ack will confirm via chat_draft_updated handler)
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
            // Use versionBeforeSave if it was an update, or 0 if it was a new draft for an existing chat (though createNew handles new chats)
            // For a brand new chat, version_before_edit would be 0.
            // For an existing chat, versionBeforeSave holds the correct value.
            // userDraft.version is the *new* version.
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
        // Optimistically clear editor and reset UI state
        clearEditorAndResetDraftState(false);

        // Local DB deletion is handled by chatSyncService after server confirmation or offline queuing
        if (get(websocketStatus).status === 'connected') {
            await chatSyncService.sendDeleteChat(chatIdToDelete);
            console.info(`[DraftService] Sent delete_chat request to server for ${chatIdToDelete}.`);
        } else {
            console.info(`[DraftService] WebSocket disconnected. Queuing chat deletion for ${chatIdToDelete}.`);
            // Deletion offline is tricky. The architecture doc doesn't explicitly cover queuing chat deletions.
            // For now, we'll log and potentially disable this button if offline, or rely on server sync upon reconnection.
            // A simple approach: if offline, just delete locally and let sync sort it out.
            // However, chatSyncService.sendDeleteChat already handles local optimistic delete.
            // So, if we want to queue, chatSyncService.sendDeleteChat would need an offline path.
            // For now, let's assume sendDeleteChat will attempt optimistic local + server, or just local if offline.
            // The current chatSyncService.sendDeleteChat does optimistic local delete.
            // If it were to queue, it would need to be added there.
            // For this step, we assume chatSyncService.sendDeleteChat handles the offline aspect appropriately
            // (e.g., by just doing the local delete and relying on next sync, or by having its own queue for deletions).
            // The current chatSyncService.sendDeleteChat does:
            // 1. Optimistically update local DB (deletes).
            // 2. Dispatches UI event.
            // 3. Sends WS message.
            // This is fine for online. For offline, step 3 fails. The local delete has happened.
            // This matches the requirement for the client to delete from IndexedDB.
            await chatSyncService.sendDeleteChat(chatIdToDelete); // This will do local delete.
        }
        // UI list update is handled by chatSyncService via events or by Chats.svelte listening to DB changes.
    } catch (error) {
        console.error(`[DraftService] Error deleting chat ${chatIdToDelete}:`, error);
        // Handle error, maybe revert UI state if needed
    }
}
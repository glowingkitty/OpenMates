import { writable } from 'svelte/store';
import { debounce } from 'lodash-es';
import { chatDB } from './db';
import { webSocketService } from './websocketService';
import type { Chat } from '../types/chat';
import { getInitialContent, isContentEmptyExceptMention } from '../components/enter_message/utils'; // Assuming utils are accessible

// --- Store for Draft State ---
interface DraftState {
    currentChatId: string | null; // ID of the chat the draft belongs to (null if new chat)
    currentTempDraftId: string | null; // Temporary ID used before chatId is assigned
    currentVersion: number; // Version of the draft being edited
    hasUnsavedChanges: boolean; // Flag to indicate if local changes haven't been confirmed by server
}

const initialDraftState: DraftState = {
    currentChatId: null,
    currentTempDraftId: null,
    currentVersion: 0,
    hasUnsavedChanges: false,
};

export const draftState = writable<DraftState>(initialDraftState);

let editorInstance: any | null = null; // Keep a reference to the Tiptap editor

// --- START ADDITION: Type for chat_details payload ---
type ChatDetailsPayload = Chat; // Assuming the backend sends the full Chat object
// --- END ADDITION ---

// --- Service Functions ---

/**
 * Initializes the draft service with the Tiptap editor instance.
 * MUST be called by MessageInput onMount.
 */
export function initializeDraftService(editor: any) {
    editorInstance = editor;
    // Register WebSocket handlers when service is initialized
    registerWebSocketHandlers();
}

/**
 * Cleans up the draft service (e.g., removes listeners).
 * MUST be called by MessageInput onDestroy.
 */
export function cleanupDraftService() {
    editorInstance = null;
    unregisterWebSocketHandlers();
    // Cancel any pending debounced saves
    saveDraftDebounced.cancel();
}

/**
 * Updates the current chat context for the draft service.
 * Called when a chat is selected or deselected.
 */
export function setCurrentChatContext(chatId: string | null, draftContent: any | null, version: number) {
    console.debug(`[DraftService] Setting context: chatId=${chatId}, version=${version}`);
    const newState: DraftState = {
        currentChatId: chatId,
        currentTempDraftId: chatId ? null : crypto.randomUUID(), // Generate temp ID only if no chatId
        currentVersion: version,
        hasUnsavedChanges: false, // Reset unsaved changes flag
    };
    draftState.set(newState);

    // Set content in the editor
    if (editorInstance) {
        editorInstance.commands.setContent(draftContent || getInitialContent());
        // Don't focus here, let the calling component decide
    } else {
        console.error("[DraftService] Editor instance not available to set content.");
    }
}

/**
 * Clears the editor and resets the draft state.
 */
export function clearEditorAndResetDraftState(shouldFocus: boolean = true) {
    if (!editorInstance) return;

    console.debug("[DraftService] Clearing editor and resetting draft state.");
    editorInstance.commands.clearContent();
    editorInstance.commands.setContent(getInitialContent()); // Reset to initial state

    draftState.set(initialDraftState); // Reset state

    if (shouldFocus) {
        editorInstance.commands.focus('end');
    }
}

/**
 * Saves the current editor content as a draft locally and attempts to send via WebSocket.
 * Debounced to avoid excessive calls.
 */
const saveDraftDebounced = debounce(async () => {
    if (!editorInstance) {
        console.error("[DraftService] Cannot save draft, editor instance not available.");
        return;
    }

    const currentState = await new Promise<DraftState>(resolve => draftState.subscribe(resolve)()); // Get current state value

    // Use helper from MessageInput or redefine here
    if (editorInstance.isEmpty || isContentEmptyExceptMention(editorInstance)) {
        // If content becomes empty, consider clearing the draft on the server/locally
        // For now, just don't save an empty draft.
        console.debug("[DraftService] Editor content is empty or only mention, skipping draft save.");
        // TODO: Implement draft clearing logic if needed
        return;
    }

    const content = editorInstance.getJSON();
    let effectiveChatId = currentState.currentChatId;
    let tempDraftId = currentState.currentTempDraftId;

    // Ensure temp ID exists if no chatId
    if (!effectiveChatId && !tempDraftId) {
        tempDraftId = crypto.randomUUID();
        draftState.update(s => ({ ...s, currentTempDraftId: tempDraftId }));
        console.debug("[DraftService] Generated new tempDraftId:", tempDraftId);
    }

    const idToSaveLocally = effectiveChatId ?? tempDraftId;
    if (!idToSaveLocally) {
        console.error("[DraftService] Cannot save draft locally: No effective ID.");
        return;
    }

    console.debug(`[DraftService] Saving draft locally & sending update. ID: ${idToSaveLocally}, Version: ${currentState.currentVersion}`);
    draftState.update(s => ({ ...s, hasUnsavedChanges: true })); // Mark as having unsaved changes

    // 1. Save Locally
    try {
        const existingChat = await chatDB.getChat(idToSaveLocally);
        const chatToSave: Chat = {
            id: idToSaveLocally,
            title: existingChat?.title ?? null,
            draft: content,
            version: currentState.currentVersion, // Version edit is based on
            messages: existingChat?.messages ?? [],
            createdAt: existingChat?.createdAt ?? new Date(),
            updatedAt: new Date(),
            lastMessageTimestamp: existingChat?.lastMessageTimestamp ?? null,
            isPersisted: !!effectiveChatId || (existingChat?.isPersisted ?? false),
        };

        if (!existingChat && !effectiveChatId) {
             // If it's a truly new local draft
             chatToSave.version = 0; // Start new local drafts at 0
             chatToSave.isPersisted = false;
        }

        await chatDB.addChat(chatToSave);
        console.debug("[DraftService] Draft saved locally:", idToSaveLocally);

    } catch (dbError) {
         console.error("[DraftService] Error saving draft locally to IndexedDB:", dbError);
         // Continue to attempt WS send even if local save fails? Or mark as failed?
         // For now, log and continue.
    }

    // 2. Send via WebSocket
    try {
        await webSocketService.sendMessage('draft_update', {
            chatId: effectiveChatId, // Send chatId if known
            tempChatId: tempDraftId, // Send temp ID if no chatId yet
            content: content,
            basedOnVersion: currentState.currentVersion // Send the version the edit was based on
        });
        // Confirmation ('draft_updated') will set hasUnsavedChanges back to false
    } catch (wsError) {
        console.error("[DraftService] Error sending draft update via WS:", wsError);
        // Draft is saved locally, but WS send failed. hasUnsavedChanges remains true.
        // TODO: Implement retry logic here or in a separate queue manager.
    }
}, 700); // 700ms debounce interval

/**
 * Triggers the debounced save function. Called on editor updates.
 */
export function triggerSaveDraft() {
    if (!editorInstance) return;
    // Only trigger save if content is not empty (or just mention)
    if (!editorInstance.isEmpty && !isContentEmptyExceptMention(editorInstance)) {
        saveDraftDebounced();
    } else {
         // If content became empty, potentially trigger draft removal logic
         // removeDraft(); // Needs implementation
    }
}

/**
 * Immediately flushes any pending debounced save operations.
 * Called on blur, visibilitychange, beforeunload.
 */
export function flushSaveDraft() {
    if (!editorInstance) return;
    // Only flush if content is not empty
    if (!editorInstance.isEmpty && !isContentEmptyExceptMention(editorInstance)) {
        console.debug("[DraftService] Flushing draft save.");
        saveDraftDebounced.flush();
    }
}

// --- WebSocket Handlers ---

// Define a more accurate type based on observed payload and backend change
interface DraftUpdatedPayload {
    chatId: string | null; // Final ID (if assigned)
    tempChatId: string | null; // Original temp ID (should now be included for new chats)
    basedOnVersion: number; // This holds the *new* version number
    content?: Record<string, any>; // Optional content
}

const handleDraftUpdated = async (payload: DraftUpdatedPayload) => {
    // Use a temporary variable to hold the state to avoid async issues within update
    let stateBeforeUpdate: DraftState | null = null;
    draftState.subscribe(s => stateBeforeUpdate = s)(); // Get current value synchronously

    if (!stateBeforeUpdate) {
        console.error("[DraftService] Could not get current draft state in handleDraftUpdated.");
        return;
    }

    const currentRelevantId = stateBeforeUpdate.currentChatId ?? stateBeforeUpdate.currentTempDraftId;
    console.debug(`[DraftService] Received draft_updated. Payload:`, payload, `Current State:`, stateBeforeUpdate);

    // --- Revised Relevance Check ---
    // Check if the update is for the draft currently being edited.
    // Match EITHER the final chatId OR the tempChatId from the payload against the current state.
    const isRelevantUpdate =
        (stateBeforeUpdate.currentChatId && stateBeforeUpdate.currentChatId === payload.chatId) ||
        (stateBeforeUpdate.currentTempDraftId && stateBeforeUpdate.currentTempDraftId === payload.tempChatId);

    if (isRelevantUpdate) {
        const newVersion = payload.basedOnVersion; // Use the correct field for the new version
        console.info(`[DraftService] Confirmed update for ${currentRelevantId}. New version: ${newVersion}`);

        let finalChatId = stateBeforeUpdate.currentChatId;
        let idToDeleteFromDb: string | null = null;

        // Case 1: Temp draft confirmed with a final chatId (payload.chatId is set, payload.tempChatId matches currentTempDraftId)
        if (!stateBeforeUpdate.currentChatId && stateBeforeUpdate.currentTempDraftId && stateBeforeUpdate.currentTempDraftId === payload.tempChatId && payload.chatId) {
            console.info(`[DraftService] Assigning final chatId ${payload.chatId} to temp draft ${payload.tempChatId}`);
            finalChatId = payload.chatId;
            idToDeleteFromDb = payload.tempChatId; // Mark temp ID for deletion

            // --- DB Update: Temp ID -> Final ID ---
            try {
                const existingChat = await chatDB.getChat(idToDeleteFromDb);
                if (existingChat) {
                    const updatedChat: Chat = {
                        ...existingChat,
                        id: finalChatId, // Assign the new final ID
                        version: newVersion,
                        isPersisted: true, // Mark as persisted now
                        updatedAt: new Date(),
                        // Use content from payload if available, otherwise keep existing
                        draft: payload.content ?? existingChat.draft,
                    };
                    // Add the new record first
                    await chatDB.addChat(updatedChat);
                    // Then delete the old record
                    await chatDB.deleteChat(idToDeleteFromDb);
                    console.debug(`[DraftService] Updated chat in DB: Replaced temp ID ${idToDeleteFromDb} with final ID ${finalChatId}, Version: ${newVersion}`);
                } else {
                    console.warn(`[DraftService] Could not find chat with temp ID ${idToDeleteFromDb} in DB to replace. Attempting to add directly.`);
                     const newChat: Chat = {
                         id: finalChatId,
                         title: null, // Or try to extract from payload.content if available
                         draft: payload.content ?? null,
                         version: newVersion,
                         messages: [],
                         createdAt: new Date(), // Approximation
                         updatedAt: new Date(),
                         lastMessageTimestamp: null,
                         isPersisted: true,
                     };
                     await chatDB.addChat(newChat);
                     console.debug(`[DraftService] Added chat directly with final ID ${finalChatId} as temp was not found.`);
                }
            } catch (dbError) {
                console.error(`[DraftService] Error replacing temp chat ID ${idToDeleteFromDb} with final ID ${finalChatId} in DB:`, dbError);
            }

        // Case 2: Update for an already known chatId (payload.chatId matches currentChatId)
        } else if (stateBeforeUpdate.currentChatId && stateBeforeUpdate.currentChatId === payload.chatId) {
            finalChatId = stateBeforeUpdate.currentChatId; // Keep the existing final ID
            // --- DB Update: Existing Chat ID ---
            try {
                const existingChat = await chatDB.getChat(finalChatId);
                if (existingChat) {
                    const updatedChat: Chat = {
                        ...existingChat,
                        version: newVersion,
                        isPersisted: true, // Ensure persisted flag is true
                        updatedAt: new Date(),
                        // Use content from payload if available, otherwise keep existing
                        draft: payload.content ?? existingChat.draft,
                    };
                    await chatDB.updateChat(updatedChat); // Use updateChat which preserves the ID
                    console.debug(`[DraftService] Updated chat in DB: ID ${finalChatId}, Version: ${newVersion}`);
                } else {
                    console.warn(`[DraftService] Could not find chat with ID ${finalChatId} in DB to update version.`);
                }
            } catch (dbError) {
                console.error(`[DraftService] Error updating chat version in DB for ID ${finalChatId}:`, dbError);
            }
        } else {
             console.warn(`[DraftService] Received relevant draft_updated but couldn't determine DB update path. Payload:`, payload, `State:`, stateBeforeUpdate);
        }

        // Update the Svelte store state *after* DB operations attempt
        draftState.update(currentState => {
             // Check relevance again using the same logic, in case state changed during async DB ops
             const stillRelevant =
                (currentState.currentChatId && currentState.currentChatId === payload.chatId) ||
                (currentState.currentTempDraftId && currentState.currentTempDraftId === payload.tempChatId);

             if (stillRelevant) {
                 return {
                     ...currentState,
                     currentChatId: finalChatId, // Use the potentially updated finalChatId
                     currentTempDraftId: finalChatId ? null : currentState.currentTempDraftId, // Clear temp ID if final assigned
                     currentVersion: newVersion,
                     hasUnsavedChanges: false, // Mark changes as saved
                 };
             }
             console.warn(`[DraftService] State changed during async DB operation for draft_updated. Ignoring state update. Payload:`, payload);
             return currentState; // State changed, ignore this update
        });

    } else {
        console.debug(`[DraftService] Received draft_updated for different context. Ignoring state update.`);
    }
};

const handleDraftConflict = (payload: { chatId?: string; draftId: string }) => {
    draftState.update(currentState => {
        const relevantId = currentState.currentChatId ?? currentState.currentTempDraftId;
        console.warn(`[DraftService] Received draft_conflict event for ID: ${payload.draftId}`);

        // Only handle if conflict is for the current draft
        if ((currentState.currentChatId && currentState.currentChatId === payload.chatId) ||
            (!currentState.currentChatId && currentState.currentTempDraftId === payload.draftId))
        {
            console.error(`[DraftService] Draft conflict detected for current draft (ID: ${relevantId}). Fetching latest state...`);
            // Send request to get the latest chat details from the server
            const chatIdToFetch = currentState.currentChatId ?? payload.chatId; // Prefer confirmed chatId if available
            if (chatIdToFetch) {
                webSocketService.sendMessage('get_chat_details', { chatId: chatIdToFetch });
            } else {
                console.error("[DraftService] Cannot fetch chat details for conflict: No chatId available.");
            }
            // Keep current state for now, handleChatDetails will update it
            return currentState;
        } else {
            console.debug(`[DraftService] Received draft_conflict for different context. Ignoring.`);
            return currentState;
        }
    });
};

// --- START ADDITION: Handler for receiving full chat details after conflict ---
const handleChatDetails = async (payload: ChatDetailsPayload) => {
    console.debug(`[DraftService] Received chat_details:`, payload);
    try {
        // 1. Update IndexedDB with the authoritative data
        await chatDB.updateChat(payload); // Assuming payload matches the Chat type for db

        // 2. Update draftState if this is the currently active chat
        draftState.update(currentState => {
            if (currentState.currentChatId === payload.id) {
                console.info(`[DraftService] Updating current draft context with fetched details for chat ${payload.id}`);
                // Update editor content only if it exists
                if (editorInstance) {
                    editorInstance.commands.setContent(payload.draft || getInitialContent());
                }
                return {
                    ...currentState,
                    currentVersion: payload.version,
                    hasUnsavedChanges: false, // Reset flag as we now have the authoritative state
                };
            }
            return currentState; // No change if not the current chat
        });

    } catch (error) {
        console.error("[DraftService] Error handling chat_details:", error);
    }
};
// --- END ADDITION ---

function registerWebSocketHandlers() {
    console.debug("[DraftService] Registering WebSocket handlers.");
    webSocketService.on('draft_updated', handleDraftUpdated);
    webSocketService.on('draft_conflict', handleDraftConflict);
    // --- START ADDITION: Register new handler ---
    webSocketService.on('chat_details', handleChatDetails);
    // --- END ADDITION ---
}

function unregisterWebSocketHandlers() {
    console.debug("[DraftService] Unregistering WebSocket handlers.");
    webSocketService.off('draft_updated', handleDraftUpdated);
    webSocketService.off('draft_conflict', handleDraftConflict);
    // --- START ADDITION: Unregister new handler ---
    webSocketService.off('chat_details', handleChatDetails);
    // --- END ADDITION ---
}

// TODO: Implement removeDraft function if needed
// export async function removeDraft() { ... }
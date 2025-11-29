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
import { extractUrlFromJsonEmbedBlock } from '../../components/enter_message/services/urlMetadataService'; // For URL extraction
import { chatMetadataCache } from '../chatMetadataCache'; // For cache invalidation
import { authStore } from '../../stores/authStore'; // Import auth store to check authentication status
import { isPublicChat } from '../../demo_chats/convertToChat'; // Import to detect demo/legal chats
import {
	saveSessionStorageDraft,
	deleteSessionStorageDraft,
	getSessionStorageDraftPreview
} from './sessionStorageDraftService'; // Import sessionStorage draft service

/**
 * Generate a preview text from markdown content for chat list display
 * This mirrors the logic in Chat.svelte's extractDisplayTextFromMarkdown function
 * @param markdown The markdown content to generate a preview from
 * @param maxLength Maximum length of the preview (default: 100 characters)
 * @returns Truncated preview text suitable for display
 */
function generateDraftPreview(markdown: string, maxLength: number = 100): string {
    if (!markdown) return '';
    
    try {
        // Replace json_embed code blocks with their URLs for display, ensuring proper spacing
        const displayText = markdown.replace(/```json_embed\n([\s\S]*?)\n```/g, (match, jsonContent) => {
            const url = extractUrlFromJsonEmbedBlock(match);
            if (url) {
                // Ensure the URL has spaces around it for proper separation from surrounding text
                return ` ${url} `;
            }
            return match; // Return original if URL extraction failed
        });
        
        // Clean up multiple spaces and trim
        const cleanedText = displayText.replace(/\s+/g, ' ').trim();
        
        // Truncate to maxLength if needed
        if (cleanedText.length > maxLength) {
            return cleanedText.substring(0, maxLength) + '...';
        }
        
        return cleanedText;
    } catch (error) {
        console.error('[DraftService] Error generating draft preview:', error);
        // Fallback: simple truncation of original markdown
        return markdown.length > maxLength ? markdown.substring(0, maxLength) + '...' : markdown;
    }
}

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

    const isAuthenticated = get(authStore).isAuthenticated;
    const currentState = get(draftEditorUIState);
    const currentChatId = currentState.currentChatId;

    if (!currentChatId) {
        console.info('[DraftService] No current chat ID to clear/delete draft for.');
        if (editor) clearEditorAndResetDraftState(false); // Reset editor if it exists
        else draftEditorUIState.set(initialDraftEditorState); // Else, just reset state
        return;
    }

    // CRITICAL: Handle non-authenticated users with sessionStorage
    if (!isAuthenticated) {
        console.info(`[DraftService] Deleting sessionStorage draft for chat ID: ${currentChatId}`);
        deleteSessionStorageDraft(currentChatId);
        
        // Update state
        draftEditorUIState.update(s => ({
            ...s,
            currentUserDraftVersion: 0,
            hasUnsavedChanges: false,
            lastSavedContentMarkdown: null
        }));
        
        // Dispatch event for UI updates
        window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { 
            detail: { chat_id: currentChatId, draftDeleted: true } 
        }));
        
        // Clear editor content
        if (editor) {
            editor.chain().clearContent(false).run();
        }
        
        return; // Exit early for non-authenticated users
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
                 // CRITICAL: Invalidate cache before dispatching event to ensure UI components fetch fresh data
                 // This prevents stale draft previews from appearing in the chat list
                 chatMetadataCache.invalidateChat(currentChatId);
                 console.debug('[DraftService] Invalidated cache for chat:', currentChatId);
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
            
            // Delete from IndexedDB first
            console.debug(`[DraftService] Deleting chat from IndexedDB: ${currentChatId}`);
            await chatDB.deleteChat(currentChatId);
            console.debug(`[DraftService] Chat deleted from IndexedDB: ${currentChatId}`);
            
            // Dispatch chatDeleted event AFTER deletion to update UI components
            console.debug(`[DraftService] Dispatching chatDeleted event for UI update: ${currentChatId}`);
            chatSyncService.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: currentChatId } }));
            console.debug(`[DraftService] chatDeleted event dispatched for chat: ${currentChatId}`);
            
            // Send delete request to server
            await chatSyncService.sendDeleteChat(currentChatId);
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

    const isAuthenticated = get(authStore).isAuthenticated;
    const currentState = get(draftEditorUIState);
    let currentChatIdForOperation = currentState.currentChatId;

    // CRITICAL: Handle non-authenticated users with sessionStorage
    // For non-authenticated users, save drafts to sessionStorage as cleartext
    if (!isAuthenticated) {
        // CRITICAL: Prevent draft deletion during context switching
        // When switching chats, the editor might be temporarily empty while loading the new chat's draft
        if (currentState.isSwitchingContext) {
            console.debug('[DraftService] Context switch in progress, skipping draft save/deletion to prevent data loss');
            return;
        }
        
        // Determine chat ID for sessionStorage draft
        // CRITICAL: For demo chats, always prioritize the draft state's currentChatId to ensure separate drafts per demo chat
        // The draft state is updated synchronously in setCurrentChatContext when switching chats, so it's more reliable
        // Only use chatIdFromMessageInput if the state doesn't have a chat ID yet (e.g., new chat creation)
        // This ensures that when switching between demo chats, each chat maintains its own separate draft
        if (currentState.currentChatId) {
            // Always use the draft state's currentChatId for demo chats to ensure separate drafts
            // This prevents overwriting one demo chat's draft when typing in another demo chat
            currentChatIdForOperation = currentState.currentChatId;
            console.debug('[DraftService] Using draft state chat ID for non-authenticated user:', {
                chatId: currentChatIdForOperation,
                propChatId: chatIdFromMessageInput,
                isDemoChat: currentChatIdForOperation.startsWith('demo-') || currentChatIdForOperation.startsWith('legal-')
            });
        } else if (chatIdFromMessageInput) {
            // Fallback to prop if state doesn't have a chat ID (e.g., new chat creation)
            currentChatIdForOperation = chatIdFromMessageInput;
            console.debug('[DraftService] Using prop chat ID for non-authenticated user (state has no chat ID):', currentChatIdForOperation);
            
            // Update draft state with the prop's chat ID to keep them in sync
            draftEditorUIState.update(s => ({
                ...s,
                currentChatId: currentChatIdForOperation
            }));
        } else {
            // No chat ID available - generate a new one for new chats
            // This ensures new chats created by non-authenticated users get a chat ID
            currentChatIdForOperation = crypto.randomUUID();
            console.debug('[DraftService] Generated new chat ID for non-authenticated user draft:', currentChatIdForOperation);
            
            // Update draft state with the new chat ID
            draftEditorUIState.update(s => ({
                ...s,
                currentChatId: currentChatIdForOperation,
                newlyCreatedChatIdToSelect: currentChatIdForOperation
            }));
        }

        const contentJSON = editor.getJSON() as TiptapJSON;
        
        // CRITICAL: Only delete draft if we're sure the editor is actually empty
        // AND we're not in the middle of a context switch
        // AND the chat ID matches the current context (to prevent deleting wrong chat's draft)
        // AND we're not switching to a demo chat (which might have no draft initially)
        if (editor.isEmpty || isContentEmptyExceptMention(editor)) {
            // CRITICAL: Never delete drafts during context switches - this prevents deleting the wrong chat's draft
            // when switching between demo chats. The isSwitchingContext flag is set for 200ms after setCurrentChatContext,
            // which should be enough time for the context switch to complete.
            if (currentState.isSwitchingContext) {
                console.debug('[DraftService] Editor empty but context switch in progress - skipping deletion to prevent data loss:', {
                    chatIdForOperation: currentChatIdForOperation,
                    currentStateChatId: currentState.currentChatId,
                    isSwitchingContext: currentState.isSwitchingContext
                });
                return;
            }
            
            // Double-check: Only delete if the chat ID matches the current context
            // This prevents deleting the wrong chat's draft during rapid switching
            if (currentChatIdForOperation === currentState.currentChatId) {
                console.info('[DraftService] Editor content is empty for non-authenticated user, deleting sessionStorage draft:', {
                    chatId: currentChatIdForOperation,
                    isDemoChat: currentChatIdForOperation?.startsWith('demo-') || currentChatIdForOperation?.startsWith('legal-')
                });
                deleteSessionStorageDraft(currentChatIdForOperation);
                
                // Update state
                draftEditorUIState.update(s => ({
                    ...s,
                    hasUnsavedChanges: false,
                    lastSavedContentMarkdown: null
                }));
                
                // Dispatch event for UI updates
                window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { 
                    detail: { chat_id: currentChatIdForOperation, draftDeleted: true } 
                }));
            } else {
                console.debug('[DraftService] Editor empty but context mismatch - skipping deletion to prevent data loss:', {
                    chatIdForOperation: currentChatIdForOperation,
                    currentStateChatId: currentState.currentChatId
                });
            }
            return;
        }
        
        // Convert TipTap content to markdown for storage
        const contentMarkdown = tipTapToCanonicalMarkdown(contentJSON);
        
        // Check if content has changed
        if (currentState.currentChatId === currentChatIdForOperation &&
            currentState.lastSavedContentMarkdown &&
            contentMarkdown === currentState.lastSavedContentMarkdown) {
            console.info(`[DraftService] Draft content for chat ${currentChatIdForOperation} is unchanged (non-authenticated). Skipping save.`);
            return;
        }
        
        // Generate preview text from markdown for chat list display
        const previewText = generateDraftPreview(contentMarkdown);
        
        // Save to sessionStorage (cleartext, no encryption)
        saveSessionStorageDraft(currentChatIdForOperation, contentJSON, previewText);
        
        // Update state
        draftEditorUIState.update(s => ({
            ...s,
            currentChatId: currentChatIdForOperation,
            hasUnsavedChanges: false,
            lastSavedContentMarkdown: contentMarkdown
        }));
        
        // Dispatch event for UI updates (chat list refresh)
        window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { 
            detail: { chat_id: currentChatIdForOperation } 
        }));
        
        console.debug('[DraftService] Saved draft to sessionStorage for non-authenticated user:', {
            chatId: currentChatIdForOperation,
            markdownLength: contentMarkdown.length
        });
        
        return; // Exit early for non-authenticated users
    }

    // Continue with authenticated user flow (IndexedDB + encryption)

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
    } else {
        // No chatIdFromMessageInput provided, use internal state
        currentChatIdForOperation = currentState.currentChatId;
        
        // If both internal state and MessageInput have no chat ID, we need to create a new chat
        if (currentChatIdForOperation === null) {
            console.info(`[DraftService] Both internal state and MessageInput have no chat ID. Will create new chat for draft.`);
            // currentChatIdForOperation will remain null, which will trigger new chat creation below
        }
    }
    // Now currentChatIdForOperation is the one to use.
    // If chatIdFromMessageInput was null, currentChatIdForOperation remains what was in the state.

    // CRITICAL: Check if we're saving a draft to a demo/legal chat (public chat)
    // If so, we MUST generate a new UUID for the chat so it becomes a regular chat
    // This ensures the chat can't be identified as demo/legal later
    if (currentChatIdForOperation && isPublicChat(currentChatIdForOperation)) {
        const oldChatId = currentChatIdForOperation;
        currentChatIdForOperation = crypto.randomUUID();
        console.info(`[DraftService] 🔄 Converting public chat ${oldChatId} to regular chat ${currentChatIdForOperation} - user created draft in demo/legal chat`);
        
        // Update draft state to use the new chat ID
        draftEditorUIState.update(s => ({
            ...s,
            currentChatId: currentChatIdForOperation,
            newlyCreatedChatIdToSelect: currentChatIdForOperation
        }));
    }

    const contentJSON = editor.getJSON() as TiptapJSON;
    
    // Convert TipTap content to markdown for storage
    const contentMarkdown = tipTapToCanonicalMarkdown(contentJSON);
    
    // Generate preview text from markdown for chat list display
    const previewText = generateDraftPreview(contentMarkdown);
    
    // CRITICAL FIX: await encryptWithMasterKey since it's async to prevent TypeError when calling substring
    const encryptedMarkdown = await encryptWithMasterKey(contentMarkdown);
    const encryptedPreview = previewText ? await encryptWithMasterKey(previewText) : null;
    
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
        previewText: previewText,
        previewLength: previewText?.length || 0,
        encryptedPreview: encryptedPreview ? encryptedPreview.substring(0, 50) + '...' : null,
        encryptedPreviewLength: encryptedPreview?.length || 0,
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
        console.info(`[DraftService] Creating new chat for draft. currentChatIdForOperation is falsy: ${currentChatIdForOperation}`);
        try {
            console.debug(`[DraftService] About to call createNewChatWithCurrentUserDraft with encryptedMarkdown length: ${encryptedMarkdown?.length}, encryptedPreview length: ${encryptedPreview?.length}`);
            // Create a new chat and its initial draft locally
            const newChat = await chatDB.createNewChatWithCurrentUserDraft(encryptedMarkdown, encryptedPreview);
            console.debug(`[DraftService] createNewChatWithCurrentUserDraft returned:`, {
                chatId: newChat.chat_id,
                draftVersion: newChat.draft_v,
                hasEncryptedDraftMd: !!newChat.encrypted_draft_md,
                hasEncryptedDraftPreview: !!newChat.encrypted_draft_preview
            });
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
        } catch (error) {
            console.error(`[DraftService] Error creating new chat for draft:`, error);
            // If chat creation fails, we can't save the draft
            draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true }));
            return;
        }
    } else {
        // Check if chat exists in database before deciding whether to create or update
        let existingChat: Chat | null = null;
        try {
            existingChat = await chatDB.getChat(currentChatIdForOperation);
        } catch (error) {
            console.error(`[DraftService] Error during database lookup for chat ${currentChatIdForOperation}:`, error);
            draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true }));
            return;
        }
        
        if (!existingChat) {
            // Chat doesn't exist in local database - create a new one
            console.info(`[DraftService] Chat ${currentChatIdForOperation} not found in local DB. Creating new chat with draft.`);
            try {
                const newChat = await chatDB.createNewChatWithCurrentUserDraft(encryptedMarkdown, encryptedPreview);
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
            } catch (error) {
                console.error(`[DraftService] Error creating new chat for non-existent chat ${currentChatIdForOperation}:`, error);
                draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true }));
                return;
            }
        } else {
            // Chat exists - update it normally
            console.info(`[DraftService] Updating existing draft for chat ${currentChatIdForOperation}`);
            versionBeforeSave = existingChat.draft_v || 0;
            userDraft = await chatDB.saveCurrentUserChatDraft(currentChatIdForOperation, encryptedMarkdown, encryptedPreview);
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

    // Invalidate cache directly (important for when Chats component is unmounted)
    console.debug(`[DraftService] Invalidating cache for updated draft in chat: ${currentChatIdForOperation}`);
    chatMetadataCache.invalidateChat(currentChatIdForOperation);
    
    // Dispatch event for UI lists to update
    window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { detail: { chat_id: currentChatIdForOperation } }));

    // Send to server or queue if offline (send encrypted markdown to server)
    // NOTE: Local storage with encrypted content has already been completed above
    const wsStatus = get(websocketStatus);
    if (wsStatus.status === 'connected') {
        try {
            // Send encrypted markdown and preview to server for synchronization
            // The sendUpdateDraft function will NOT save to local database - that's already done above with encryption
            await chatSyncService.sendUpdateDraft(currentChatIdForOperation, encryptedMarkdown, encryptedPreview);
            console.info(`[DraftService] Successfully sent encrypted draft to server for chat ${currentChatIdForOperation}.`);
        } catch (wsError) {
            console.error(`[DraftService] Error sending draft update via WS for chat ${currentChatIdForOperation}:`, wsError);
            draftEditorUIState.update(s => ({ ...s, hasUnsavedChanges: true }));
        }
    } else {
        console.info(`[DraftService] WebSocket status is '${wsStatus.status}', not 'connected'. Queuing draft update for chat ${currentChatIdForOperation}.`);
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
 * CRITICAL: For non-authenticated users, prefer using draft state's currentChatId
 * to avoid race conditions when switching chats quickly.
 */
export function triggerSaveDraft(chatIdFromMessageInput?: string) {
    const editor = getEditorInstance();
    if (!editor) return;
    
    // CRITICAL: For non-authenticated users, check if we're switching context
    // If so, skip the save to prevent deleting the wrong chat's draft
    const currentState = get(draftEditorUIState);
    if (!get(authStore).isAuthenticated && currentState.isSwitchingContext) {
        console.debug('[DraftService] Context switch in progress, skipping triggerSaveDraft to prevent data loss');
        return;
    }
    
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

        // Delete from IndexedDB first
        console.debug(`[DraftService] Deleting chat from IndexedDB: ${chatIdToDelete}`);
        await chatDB.deleteChat(chatIdToDelete);
        console.debug(`[DraftService] Chat deleted from IndexedDB: ${chatIdToDelete}`);
        
        // Dispatch chatDeleted event AFTER deletion to update UI components
        console.debug(`[DraftService] Dispatching chatDeleted event for UI update: ${chatIdToDelete}`);
        chatSyncService.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: chatIdToDelete } }));
        console.debug(`[DraftService] chatDeleted event dispatched for chat: ${chatIdToDelete}`);
        
        // Send delete request to server
        await chatSyncService.sendDeleteChat(chatIdToDelete);
        console.info(`[DraftService] Sent delete_chat request for ${chatIdToDelete}.`);
        // UI list update is handled by chatDeleted event dispatched above
        
    } catch (error) {
        console.error(`[DraftService] Error deleting chat ${chatIdToDelete}:`, error);
        // Handle error, maybe revert UI state if needed, though optimistic clear already happened.
        // If server fails, sync on reconnect should resolve.
        // For now, we assume the optimistic local clear is acceptable UX.
        // To be more robust, one might re-fetch chat list or show error.
    }
}

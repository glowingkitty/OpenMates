import { get } from 'svelte/store';
import { getInitialContent } from '../../components/enter_message/utils'; // Adjusted path
import { draftEditorUIState, initialDraftEditorState } from './draftState'; // Renamed import
import type { DraftEditorState } from './draftTypes'; // Renamed type
import { registerWebSocketHandlers, unregisterWebSocketHandlers } from './draftWebsocket'; // Will be created next
import { saveDraftDebounced } from './draftSave'; // Will be created next
import { authStore } from '../../stores/authStore'; // Import authStore for authentication checks

let editorInstance: any | null = null; // Keep a reference to the Tiptap editor

/**
 * Initializes the draft service with the Tiptap editor instance.
 * MUST be called by MessageInput onMount.
 */
export function initializeDraftService(editor: any) {
	if (editorInstance) {
		console.warn('[DraftService] initializeDraftService called more than once.');
		// Optionally clean up previous instance if re-initialization is intended
		// cleanupDraftService();
	}
	editorInstance = editor;
	console.info('[DraftService] Editor instance set.');
	// Register WebSocket handlers when service is initialized
	registerWebSocketHandlers();
}

/**
 * Cleans up the draft service (e.g., removes listeners).
 * MUST be called by MessageInput onDestroy.
 */
export function cleanupDraftService() {
	if (!editorInstance) {
		// console.warn("[DraftService] cleanupDraftService called but no editor instance exists.");
		return; // Avoid errors if called multiple times or without init
	}
	console.info('[DraftService] Cleaning up draft service.');
	editorInstance = null;
	unregisterWebSocketHandlers();
	// Cancel any pending debounced saves
	saveDraftDebounced.cancel();
	// Reset state? Optional, depends on desired behavior on component destroy/re-mount
	// draftEditorUIState.set(initialDraftEditorState); // Use renamed store and state
}

/**
 * Returns the current editor instance. Use with caution.
 */
export function getEditorInstance(): any | null {
	return editorInstance;
}

/**
 * Updates the current chat context for the draft service.
 * Called when a chat is selected or deselected, or a new chat is started.
 * CRITICAL: Saves the previous chat's draft before switching to prevent data loss.
 */
export async function setCurrentChatContext(
	chatId: string | null,
	draftContent: any | null,
	version: number
) {
	console.info(`[DraftService] Setting context: chatId=${chatId}, version=${version}`);
	const currentState = get(draftEditorUIState); // Use renamed store
	
	// CRITICAL: Save the previous chat's draft before switching context
	// This prevents draft loss when quickly switching between chats
	if (currentState.currentChatId && currentState.currentChatId !== chatId) {
		console.debug(`[DraftService] Saving draft for previous chat ${currentState.currentChatId} before switching to ${chatId}`);
		// Flush any pending saves for the previous chat
		const { flushSaveDraft } = await import('./draftSave');
		flushSaveDraft();
		// Small delay to ensure the save completes
		await new Promise(resolve => setTimeout(resolve, 50));
	}

	// Set flag to prevent draft deletion during context switch
	draftEditorUIState.update(s => ({ ...s, isSwitchingContext: true }));

	const newState: DraftEditorState = { // Use renamed type
		...currentState, // Preserve other state like newlyCreatedChatIdToSelect
		currentChatId: chatId,
		currentUserDraftVersion: version, // Ensure this matches DraftEditorState field name
		hasUnsavedChanges: false, // Reset unsaved changes flag when context changes
		lastSavedContentMarkdown: null, // Reset markdown tracking for new context
		isSwitchingContext: true, // Set flag to prevent deletion during switch
	};
	draftEditorUIState.set(newState); // Use renamed store

	// Set content in the editor
	if (editorInstance) {
		// Ensure content is not null/undefined before setting
		const contentToSet = draftContent ?? getInitialContent();
		console.debug('[DraftService] Setting editor content:', contentToSet);
		// Use different methods to avoid triggering 'update' event which calls triggerSaveDraft
		editorInstance.chain().setContent(contentToSet, false).run();
		// Do NOT auto-focus the editor - user must manually click to focus
		// This prevents unwanted focus when switching between chats
		console.debug('[DraftService] Skipped auto-focus - user must click to focus');
	} else {
		console.error('[DraftService] Editor instance not available to set content.');
	}
	
	// Clear the switching flag after a delay to allow editor updates to settle
	// CRITICAL: Use a longer delay (500ms) to ensure all editor update events from the context switch
	// have completed before allowing draft saves/deletions. This prevents deleting the wrong chat's draft
	// when switching between demo chats.
	setTimeout(() => {
		draftEditorUIState.update(s => ({ ...s, isSwitchingContext: false }));
		console.debug('[DraftService] Context switch complete, cleared isSwitchingContext flag');
	}, 500); // 500ms to ensure all editor updates from context switch have settled
}

/**
 * Clears the editor and resets the draft state to initial values.
 * Typically used when starting a completely new chat from scratch via UI action.
 * CRITICAL: For non-authenticated users, also deletes the draft from sessionStorage.
 * 
 * @param shouldFocus - Whether to focus the editor after clearing
 * @param preserveContext - If true, preserves the current chat context (doesn't reset currentChatId or delete drafts)
 *                          This is used when switching to a chat that has no draft - we just clear the editor content
 *                          without deleting the previous chat's draft or resetting the context.
 */
export async function clearEditorAndResetDraftState(shouldFocus: boolean = true, preserveContext: boolean = false) {
	if (!editorInstance) {
		console.error('[DraftService] Cannot clear editor, instance not available.');
		return;
	}

	console.info('[DraftService] Clearing editor and resetting draft state.', { preserveContext });
	
	const currentState = get(draftEditorUIState);
	const isAuthenticated = get(authStore).isAuthenticated;
	
	// CRITICAL: Only delete draft from sessionStorage if we're NOT preserving context
	// When preserving context (e.g., switching to a chat with no draft), we should NOT delete
	// the previous chat's draft - we're just clearing the editor content for the new chat
	if (!preserveContext && !isAuthenticated && currentState.currentChatId) {
		console.debug('[DraftService] Non-authenticated user clearing editor - deleting sessionStorage draft');
		const { deleteSessionStorageDraft } = await import('./sessionStorageDraftService');
		deleteSessionStorageDraft(currentState.currentChatId);
		
		// Dispatch event for UI updates
		const { LOCAL_CHAT_LIST_CHANGED_EVENT } = await import('./draftConstants');
		window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { 
			detail: { chat_id: currentState.currentChatId, draftDeleted: true } 
		}));
	}
	
	// Use chain().clearContent() to avoid triggering update event
	editorInstance.chain().clearContent(false).run();
	// Set to initial state, also without emitting update
	editorInstance.chain().setContent(getInitialContent(), false).run();

	// CRITICAL: Only reset the entire draft state if we're NOT preserving context
	// When preserving context, we keep the currentChatId and other state intact
	// This prevents accidentally deleting drafts when switching between chats
	if (preserveContext) {
		// Just reset the editor-related state, but keep the chat context
		draftEditorUIState.update(s => ({
			...s,
			hasUnsavedChanges: false,
			lastSavedContentMarkdown: null,
			currentUserDraftVersion: 0
		}));
		console.debug('[DraftService] Cleared editor content but preserved chat context');
	} else {
		// Full reset - used when explicitly clearing the editor (e.g., starting new chat)
		draftEditorUIState.set(initialDraftEditorState);
	}

	if (shouldFocus) {
		// Focus after a short delay to ensure content is set
		setTimeout(() => editorInstance?.commands.focus('end'), 50);
	}
}
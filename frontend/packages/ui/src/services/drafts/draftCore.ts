import { get } from 'svelte/store';
import { getInitialContent } from '../../components/enter_message/utils'; // Adjusted path
import { draftState, initialDraftState } from './draftState';
import type { DraftState } from './draftTypes';
import { registerWebSocketHandlers, unregisterWebSocketHandlers } from './draftWebsocket'; // Will be created next
import { saveDraftDebounced } from './draftSave'; // Will be created next

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
	// draftState.set(initialDraftState);
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
 */
export function setCurrentChatContext(
	chatId: string | null,
	draftContent: any | null,
	version: number
) {
	console.info(`[DraftService] Setting context: chatId=${chatId}, version=${version}`);
	const currentState = get(draftState); // Get current state

	const newState: DraftState = {
		...currentState, // Preserve other state like user_id and newlyCreatedChatIdToSelect
		currentChatId: chatId,
		draft_v: version,
		hasUnsavedChanges: false, // Reset unsaved changes flag when context changes
	};
	draftState.set(newState);

	// Set content in the editor
	if (editorInstance) {
		// Ensure content is not null/undefined before setting
		const contentToSet = draftContent ?? getInitialContent();
		console.debug('[DraftService] Setting editor content:', contentToSet);
		// Use different methods to avoid triggering 'update' event which calls triggerSaveDraft
		editorInstance.chain().setContent(contentToSet, false).run();
		// Ensure cursor is at the end after setting content
		setTimeout(() => editorInstance?.commands.focus('end'), 50);
	} else {
		console.error('[DraftService] Editor instance not available to set content.');
	}
}

/**
 * Clears the editor and resets the draft state to initial values.
 * Typically used when starting a completely new chat from scratch via UI action.
 */
export function clearEditorAndResetDraftState(shouldFocus: boolean = true) {
	if (!editorInstance) {
		console.error('[DraftService] Cannot clear editor, instance not available.');
		return;
	}

	console.info('[DraftService] Clearing editor and resetting draft state.');
	// Use chain().clearContent() to avoid triggering update event
	editorInstance.chain().clearContent(false).run();
	// Set to initial state, also without emitting update
	editorInstance.chain().setContent(getInitialContent(), false).run();

	draftState.set(initialDraftState); // Reset state

	if (shouldFocus) {
		// Focus after a short delay to ensure content is set
		setTimeout(() => editorInstance?.commands.focus('end'), 50);
	}
}
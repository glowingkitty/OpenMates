import { debounce } from 'lodash-es';
import { get } from 'svelte/store'; // Use get for synchronous access
import { chatDB } from '../db';
import { webSocketService } from '../websocketService';
import type { Chat } from '../../types/chat'; // Adjusted path
import { isContentEmptyExceptMention } from '../../components/enter_message/utils'; // Adjusted path
import { draftState, initialDraftState } from './draftState';
import type { DraftState } from './draftTypes';
import { LOCAL_CHAT_LIST_CHANGED_EVENT } from './draftConstants';
import { getEditorInstance, clearEditorAndResetDraftState } from './draftCore'; // Import getEditorInstance

/**
 * Deletes the draft (and potentially the chat) locally and informs the server.
 */
async function removeDraft() {
	const editor = getEditorInstance();
	if (!editor) {
		console.error('[DraftService] Cannot remove draft, editor instance not available.');
		return;
	}

	const currentState = get(draftState); // Get current state synchronously
	const idToDelete = currentState.currentChatId ?? currentState.currentTempDraftId;

	if (!idToDelete) {
		console.info('[DraftService] No draft ID to remove (likely already cleared or never saved).');
		// Ensure editor is clear and state is reset anyway, but don't focus
		clearEditorAndResetDraftState(false);
		return;
	}

	console.info(`[DraftService] Removing draft/chat with ID: ${idToDelete}`);

	let dbDeleteSuccess = false;
	try {
		// Check if the chat exists before attempting deletion
		const existingChat = await chatDB.getChat(idToDelete);
		if (existingChat) {
			await chatDB.deleteChat(idToDelete);
			console.info(`[DraftService] Draft/Chat ${idToDelete} removed locally from DB.`);
			dbDeleteSuccess = true;
		} else {
			console.info(`[DraftService] Chat/Draft ${idToDelete} not found in DB, skipping local deletion.`);
			// Even if not in DB, we might need to clear state and inform server if it was a persisted chat ID
			dbDeleteSuccess = true; // Consider this "successful" in terms of proceeding
		}
	} catch (dbError) {
		console.error(
			`[DraftService] Error removing draft/chat ${idToDelete} locally from DB:`,
			dbError
		);
		// Proceed to inform server even if local delete failed? Maybe not.
		// If local delete fails, the state might become inconsistent.
		// For now, we stop here if DB delete fails.
		return;
	}

	// Only inform server if it was a persisted chat (had a final chatId)
	if (currentState.currentChatId) {
		try {
			// Use a specific 'delete_chat' event if available, otherwise maybe 'draft_update' with null content?
			// Assuming 'delete_chat' exists:
			await webSocketService.sendMessage('delete_chat', {
				chatId: currentState.currentChatId
			});
			console.info(
				`[DraftService] Sent delete_chat request to server for chat ID: ${currentState.currentChatId}`
			);
		} catch (wsError) {
			console.error(
				`[DraftService] Error sending delete_chat via WS for chat ID ${currentState.currentChatId}:`,
				wsError
			);
			// TODO: Handle potential inconsistency - local deleted, server not notified. Queue for retry?
		}
	} else {
		console.info(`[DraftService] Draft ${idToDelete} was temporary, not sending delete request to server.`);
	}

	// Dispatch event to update UI lists *after* DB operation
	if (dbDeleteSuccess) {
		console.debug('[DraftService] Dispatching local chat list changed event after draft removal.');
		window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT));
	}

	// Reset the editor and state *after* successful deletion and potential server notification
	// Don't refocus after deletion
	clearEditorAndResetDraftState(false);
}

/**
 * Saves the current editor content as a draft locally and attempts to send via WebSocket.
 * Debounced to avoid excessive calls.
 */
export const saveDraftDebounced = debounce(async () => {
	const editor = getEditorInstance();
	if (!editor) {
		console.error('[DraftService] Cannot save draft, editor instance not available.');
		return;
	}

	// Get current state value synchronously BEFORE any async operations
	const currentState = get(draftState); // Use get for synchronous access
	if (!currentState) {
		console.error('[DraftService] Could not get current draft state in saveDraftDebounced.');
		return; // Should not happen with svelte stores
	}

	// --- START DELETION LOGIC ---
	// Check if content is effectively empty BEFORE proceeding with save
	if (editor.isEmpty || isContentEmptyExceptMention(editor)) {
		console.info('[DraftService] Editor content is empty or only mention. Triggering draft removal.');
		// Call removeDraft instead of saving
		await removeDraft(); // removeDraft handles DB, WS, state reset, event dispatch
		return; // Stop execution here, don't save empty draft
	}
	// --- END DELETION LOGIC ---

	const content = editor.getJSON();
	console.info('[DraftService] Saving draft content:', content);
	let effectiveChatId = currentState.currentChatId;
	let tempDraftId = currentState.currentTempDraftId;

	// Ensure temp ID exists if no chatId (should only happen on the very first save attempt for a new chat)
	if (!effectiveChatId && !tempDraftId) {
		tempDraftId = crypto.randomUUID();
		// Update state immediately so subsequent calls within debounce window use the same temp ID
		draftState.update((s) => {
			// Only update if still relevant (no chatId assigned in meantime and no tempId yet)
			if (!s.currentChatId && !s.currentTempDraftId) {
				console.log('[DraftService] Generated and setting new tempDraftId:', tempDraftId);
				return { ...s, currentTempDraftId: tempDraftId };
			}
			return s; // State changed concurrently, ignore
		});
		// Re-fetch state after update to ensure we use the new tempDraftId
		const updatedState = get(draftState);
		tempDraftId = updatedState.currentTempDraftId; // Use the potentially updated temp ID
		console.log('[DraftService] Using tempDraftId after update:', tempDraftId);
	} else if (!effectiveChatId && currentState.currentTempDraftId) {
		// Ensure we use the tempDraftId from the potentially updated state
		tempDraftId = currentState.currentTempDraftId;
	}

	const idToSaveLocally = effectiveChatId ?? tempDraftId;
	if (!idToSaveLocally) {
		console.error('[DraftService] Cannot save draft locally: No effective ID.');
		return;
	}

	console.info(
		`[DraftService] Saving draft locally & sending update. ID: ${idToSaveLocally}, Version: ${currentState.currentVersion}`
	);
	draftState.update((s) => ({ ...s, hasUnsavedChanges: true })); // Mark as having unsaved changes

	let dbOperationSuccess = false; // Flag to track DB success

	// 1. Save Locally
	try {
		const existingChat = await chatDB.getChat(idToSaveLocally);
		const chatToSave: Chat = {
			id: idToSaveLocally,
			title: existingChat?.title ?? null, // Keep existing title or null for new
			draft: content,
			version: currentState.currentVersion, // Version edit is based on
			messages: existingChat?.messages ?? [],
			createdAt: existingChat?.createdAt ?? new Date(),
			updatedAt: new Date(), // <<< Update timestamp on local save
			lastMessageTimestamp: existingChat?.lastMessageTimestamp ?? null,
			isPersisted: !!effectiveChatId || (existingChat?.isPersisted ?? false),
			// Ensure other fields from Chat type are present if needed
			mates: existingChat?.mates ?? [],
			unreadCount: existingChat?.unreadCount ?? 0
		};

		if (!existingChat && !effectiveChatId) {
			// If it's a truly new local draft (no existing record, no final chatId yet)
			chatToSave.version = 0; // Start new local drafts at 0
			chatToSave.isPersisted = false;
			chatToSave.title = ''; // Default new drafts to empty title
		}

		// Use addChat which handles both add and update (put)
		await chatDB.addChat(chatToSave);
		console.info('[DraftService] Draft saved locally:', idToSaveLocally);
		dbOperationSuccess = true; // Mark DB operation as successful
	} catch (dbError) {
		console.error('[DraftService] Error saving draft locally to IndexedDB:', dbError);
		// Continue to attempt WS send even if local save fails? Or mark as failed?
		// For now, log and continue, but keep hasUnsavedChanges true.
		draftState.update((s) => ({ ...s, hasUnsavedChanges: true }));
	}

	// Dispatch event after successful local DB save
	if (dbOperationSuccess) {
		console.debug('[DraftService] Dispatching local chat list changed event after local save.');
		window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT));
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
		console.error('[DraftService] Error sending draft update via WS:', wsError);
		// Draft is saved locally, but WS send failed. hasUnsavedChanges remains true.
		draftState.update((s) => ({ ...s, hasUnsavedChanges: true }));
		// TODO: Implement retry logic here or in a separate queue manager.
	}
}, 700); // 700ms debounce interval

/**
 * Triggers the debounced save function or draft removal. Called on editor updates.
 */
export function triggerSaveDraft() {
	const editor = getEditorInstance();
	if (!editor) return;

	// Check content emptiness and decide whether to save or remove
	// Let the debounced function handle the empty check and call removeDraft if needed
	saveDraftDebounced();
}

/**
 * Immediately flushes any pending debounced save/remove operations.
 * Called on blur, visibilitychange, beforeunload.
 */
export function flushSaveDraft() {
	const editor = getEditorInstance();
	if (!editor) return;
	// Flush regardless of content? Yes, ensures last state (empty or not) is processed.
	console.info('[DraftService] Flushing draft operation.');
	saveDraftDebounced.flush();
}
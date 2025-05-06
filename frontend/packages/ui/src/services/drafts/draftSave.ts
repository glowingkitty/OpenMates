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

	// Only inform server if it was a persisted chat (had a final chatId and user_id)
	// The client UUID (idToDelete) is always sent. If user_id is known, server can reconstruct full ID.
	if (idToDelete) { // idToDelete is the client UUID
		try {
			await webSocketService.sendMessage('delete_chat', {
				// chatId on server is composite, but client only knows its UUID and potentially user_id part
				// Server will need to handle deletion based on client_id and potentially user_id if provided
				chatId: idToDelete, // Send the client UUID as the primary identifier
				user_id: currentState.user_id // Send user_id if known
			});
			console.info(
				`[DraftService] Sent delete_chat request to server for client UUID: ${idToDelete}, user_id: ${currentState.user_id}`
			);
		} catch (wsError) {
			console.error(
				`[DraftService] Error sending delete_chat via WS for client UUID ${idToDelete}:`,
				wsError
			);
			// TODO: Handle potential inconsistency - local deleted, server not notified. Queue for retry?
		}
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
	// currentChatId is the client-generated UUID.
	// currentTempDraftId is deprecated in favor of always having a client UUID.
	let clientChatUUID = currentState.currentChatId;

	// If no currentChatId, it's a brand new draft. Generate a UUID.
	if (!clientChatUUID) {
		clientChatUUID = crypto.randomUUID();
		// Update state immediately so subsequent calls use the same UUID.
		// Also, this new UUID is what we'll use to select the chat.
		draftState.update((s) => {
			if (!s.currentChatId) { // Ensure it hasn't been set concurrently
				console.log('[DraftService] Generated new clientChatUUID for new draft:', clientChatUUID);
				return {
				...s,
				currentChatId: clientChatUUID,
				currentTempDraftId: null, // Clear old temp ID logic
				newlyCreatedChatIdToSelect: clientChatUUID, // Signal this new UUID for selection
				user_id: undefined // New draft won't have a server user_id part yet
				};
			}
			return s;
		});
		// Re-fetch state to ensure we use the new clientChatUUID and other updated fields
		const updatedState = get(draftState);
		clientChatUUID = updatedState.currentChatId; // Should be the new UUID
		console.log('[DraftService] Using clientChatUUID after state update for new draft:', clientChatUUID);
	}

	if (!clientChatUUID) {
		console.error('[DraftService] Cannot save draft: No clientChatUUID available.');
		return;
	}

	console.info(
		`[DraftService] Saving draft. Client UUID: ${clientChatUUID}, Server UserID Part: ${currentState.user_id}, Version: ${currentState.currentVersion}`
	);
	draftState.update((s) => ({ ...s, hasUnsavedChanges: true }));

	let dbOperationSuccess = false;
	let isNewChatEntryForDB = false;

	// 1. Save Locally
	try {
		const existingChat = await chatDB.getChat(clientChatUUID);
		isNewChatEntryForDB = !existingChat;

		const chatToSave: Chat = {
			id: clientChatUUID, // Always use the client UUID as the primary ID in the local DB
			user_id: currentState.user_id ?? existingChat?.user_id, // Persist user_id if known
			title: existingChat?.title ?? (isNewChatEntryForDB ? '' : null),
			draft: content,
			version: currentState.currentVersion,
			messages: existingChat?.messages ?? [],
			createdAt: existingChat?.createdAt ?? new Date(),
			updatedAt: new Date(),
			lastMessageTimestamp: existingChat?.lastMessageTimestamp ?? null,
			isPersisted: !!currentState.user_id || (existingChat?.isPersisted ?? false), // Persisted if user_id is known
			mates: existingChat?.mates ?? [],
			unreadCount: existingChat?.unreadCount ?? 0
		};

		if (isNewChatEntryForDB) {
			chatToSave.version = 0; // New local drafts start at version 0
			// newlyCreatedChatIdToSelect was set when UUID was generated for a new draft
		}

		await chatDB.addChat(chatToSave); // addChat handles add or update (put)
		console.info('[DraftService] Draft saved locally:', clientChatUUID);
		dbOperationSuccess = true;

		// If a new chat was created and saved to DB, ensure newlyCreatedChatIdToSelect is set
		// This is mostly for cases where the UUID might not have been set in the initial generation block
		// (e.g. if loading an existing draft that somehow missed its UUID in draftState initially)
		if (isNewChatEntryForDB && !get(draftState).newlyCreatedChatIdToSelect) {
			console.info('[DraftService] New chat entry in DB, ensuring newlyCreatedChatIdToSelect is set:', chatToSave.id);
			draftState.update(s => ({ ...s, newlyCreatedChatIdToSelect: chatToSave.id }));
		}


	} catch (dbError) {
		console.error('[DraftService] Error saving draft locally to IndexedDB:', dbError);
		draftState.update((s) => ({ ...s, hasUnsavedChanges: true }));
	}

	if (dbOperationSuccess) {
		console.info('[DraftService] Dispatching local chat list changed event after local save.');
		window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT));
	}

	// 2. Send via WebSocket
	// Payload to server: client_id (our UUID), user_hash_suffix (if known), content, basedOnVersion
	try {
		const payloadForServer = {
			client_id: clientChatUUID,
			user_hash_suffix: currentState.user_id, // This is the 10-char hash from server
			content: content,
			basedOnVersion: currentState.currentVersion
		};
		console.debug('[DraftService] Sending draft_update to WS with payload:', payloadForServer);
		await webSocketService.sendMessage('draft_update', payloadForServer);
		// Confirmation ('draft_updated') from server will set hasUnsavedChanges back to false
		// and provide the server_chat_id and user_id (hash suffix)
	} catch (wsError) {
		console.error('[DraftService] Error sending draft update via WS:', wsError);
		draftState.update((s) => ({ ...s, hasUnsavedChanges: true }));
		// TODO: Implement retry logic
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
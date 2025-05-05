import { get } from 'svelte/store';
import { chatDB } from '../db';
import { webSocketService } from '../websocketService';
import type { Chat } from '../../types/chat'; // Adjusted path
import { getInitialContent } from '../../components/enter_message/utils'; // Adjusted path
import { draftState } from './draftState';
import type {
	DraftState,
	DraftUpdatedPayload,
	DraftConflictPayload,
	ChatDetailsPayload
} from './draftTypes';
import { LOCAL_CHAT_LIST_CHANGED_EVENT } from './draftConstants';
import { getEditorInstance } from './draftCore';

// --- WebSocket Handlers ---

const handleDraftUpdated = async (payload: DraftUpdatedPayload) => {
	// Use get for synchronous access to avoid async issues within update
	const stateBeforeUpdate = get(draftState);

	if (!stateBeforeUpdate) {
		console.error('[DraftService] Could not get current draft state in handleDraftUpdated.');
		return;
	}

	const currentRelevantId = stateBeforeUpdate.currentChatId ?? stateBeforeUpdate.currentTempDraftId;
	console.info(
		`[DraftService] Received draft_updated. Payload:`,
		payload,
		`Current State:`,
		stateBeforeUpdate
	);

	// --- Revised Relevance Check ---
	// Check if the update is for the draft currently being edited.
	// Match EITHER the final chatId OR the tempChatId from the payload against the current state.
	const isRelevantUpdate =
		(stateBeforeUpdate.currentChatId && stateBeforeUpdate.currentChatId === payload.chatId) ||
		(stateBeforeUpdate.currentTempDraftId &&
			stateBeforeUpdate.currentTempDraftId === payload.tempChatId);

	let dbOperationSuccess = false; // Track DB success for event dispatch

	if (isRelevantUpdate) {
		const newVersion = payload.basedOnVersion; // Use the correct field for the new version
		console.info(
			`[DraftService] Confirmed update for ${currentRelevantId}. New version: ${newVersion}`
		);

		let finalChatId = stateBeforeUpdate.currentChatId;
		let idToDeleteFromDb: string | null = null;

		// Case 1: Temp draft confirmed with a final chatId
		if (
			!stateBeforeUpdate.currentChatId &&
			stateBeforeUpdate.currentTempDraftId &&
			stateBeforeUpdate.currentTempDraftId === payload.tempChatId &&
			payload.chatId
		) {
			console.info(
				`[DraftService] Assigning final chatId ${payload.chatId} to temp draft ${payload.tempChatId}`
			);
			finalChatId = payload.chatId;
			idToDeleteFromDb = payload.tempChatId; // Mark temp ID for deletion

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
						draft: payload.content ?? existingChat.draft
					};
					// Add the new record first
					await chatDB.addChat(updatedChat);
					// Then delete the old record
					await chatDB.deleteChat(idToDeleteFromDb);
					console.info(
						`[DraftService] Updated chat in DB: Replaced temp ID ${idToDeleteFromDb} with final ID ${finalChatId}, Version: ${newVersion}`
					);
					dbOperationSuccess = true;
				} else {
					console.warn(
						`[DraftService] Could not find chat with temp ID ${idToDeleteFromDb} in DB to replace. Attempting to add directly.`
					);
					const newChat: Chat = {
						id: finalChatId,
						title: '', // Default title
						draft: payload.content ?? null,
						version: newVersion,
						messages: [],
						createdAt: new Date(), // Approximation
						updatedAt: new Date(),
						lastMessageTimestamp: null,
						isPersisted: true,
						mates: [], // Add default
						unreadCount: 0 // Add default
					};
					await chatDB.addChat(newChat);
					console.info(
						`[DraftService] Added chat directly with final ID ${finalChatId} as temp was not found.`
					);
					dbOperationSuccess = true; // Still counts as a successful DB change
				}
			} catch (dbError) {
				console.error(
					`[DraftService] Error replacing temp chat ID ${idToDeleteFromDb} with final ID ${finalChatId} in DB:`,
					dbError
				);
			}

			// Case 2: Update for an already known chatId
		} else if (stateBeforeUpdate.currentChatId && stateBeforeUpdate.currentChatId === payload.chatId) {
			finalChatId = stateBeforeUpdate.currentChatId; // Keep the existing final ID
			try {
				const existingChat = await chatDB.getChat(finalChatId);
				if (existingChat) {
					const updatedChat: Chat = {
						...existingChat,
						version: newVersion,
						isPersisted: true, // Ensure persisted flag is true
						updatedAt: new Date(),
						// Use content from payload if available, otherwise keep existing
						draft: payload.content ?? existingChat.draft
					};
					await chatDB.updateChat(updatedChat); // Use updateChat which preserves the ID
					console.info(
						`[DraftService] Updated chat in DB: ID ${finalChatId}, Version: ${newVersion}`
					);
					dbOperationSuccess = true;
				} else {
					console.warn(
						`[DraftService] Could not find chat with ID ${finalChatId} in DB to update version.`
					);
				}
			} catch (dbError) {
				console.error(
					`[DraftService] Error updating chat version in DB for ID ${finalChatId}:`,
					dbError
				);
			}
		} else {
			console.warn(
				`[DraftService] Received relevant draft_updated but couldn't determine DB update path. Payload:`,
				payload,
				`State:`,
				stateBeforeUpdate
			);
		}

		// Update the Svelte store state *after* DB operations attempt
		draftState.update((currentState) => {
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
					hasUnsavedChanges: false // Mark changes as saved
				};
			}
			console.warn(
				`[DraftService] State changed during async DB operation for draft_updated. Ignoring state update. Payload:`,
				payload
			);
			return currentState; // State changed, ignore this update
		});
	} else {
		console.info(`[DraftService] Received draft_updated for different context (not currently edited).`);

		// If the update is NOT for the currently active draft,
		// check if we need to add this chat locally (e.g., created on another device)
		// or update its version if it already exists locally but isn't active.
		try {
			// Ensure payload.chatId exists before proceeding
			if (payload.chatId) {
				const existingChat = await chatDB.getChat(payload.chatId);
				if (!existingChat) {
					console.info(
						`[DraftService] Received draft update for non-active, non-existent chat ${payload.chatId}. Creating new local entry.`
					);
					const now = new Date();
					const newChat: Chat = {
						// <<< Use Chat type
						id: payload.chatId,
						title: '', // Default to empty title for a new draft entry
						draft: payload.content ?? null, // Include the draft content
						version: payload.basedOnVersion, // Use the version from the payload
						messages: [], // No messages yet for a draft
						createdAt: now, // Use current time as approximation
						updatedAt: now,
						lastMessageTimestamp: null,
						isPersisted: true, // Assume persisted if we get an update with final ID
						mates: [], // Add default
						unreadCount: 0 // Add default
					};
					await chatDB.addChat(newChat); // Add to local DB
					console.debug(`[DraftService] Added new chat entry for draft ${payload.chatId} to DB.`);
					dbOperationSuccess = true;
				} else {
					// Optionally update the existing non-active chat's version/draft if needed
					console.info(
						`[DraftService] Received draft_updated for non-active, existing chat ${payload.chatId}. Updating version/content.`
					);
					const updatedChat: Chat = {
						...existingChat,
						version: payload.basedOnVersion,
						draft: payload.content ?? existingChat.draft, // Update draft if provided
						updatedAt: new Date(),
						// Ensure isPersisted is true if we received an update with a final ID
						isPersisted: true
					};
					await chatDB.updateChat(updatedChat);
					dbOperationSuccess = true;
				}
			} else {
				console.warn(
					`[DraftService] Received non-relevant draft_updated without a final chatId. Cannot process DB addition/update. Payload:`,
					payload
				);
			}
		} catch (error) {
			console.error(
				`[DraftService] Error checking/adding/updating non-active chat ${payload.chatId} during draft update:`,
				error
			);
		}
	}

	// Dispatch event after successful DB operation from WS handler
	// This ensures the list updates even if the change came from the server for a non-active chat
	if (dbOperationSuccess) {
		console.debug(
			'[DraftService] Dispatching local chat list changed event after handling draft_updated WS message.'
		);
		window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT));
	}
};

const handleDraftConflict = (payload: DraftConflictPayload) => {
	draftState.update((currentState) => {
		const relevantId = currentState.currentChatId ?? currentState.currentTempDraftId;
		console.warn(`[DraftService] Received draft_conflict event for ID: ${payload.draftId}`);

		// Only handle if conflict is for the current draft
		if (
			(currentState.currentChatId && currentState.currentChatId === payload.chatId) || // Match final ID if present
			(currentState.currentChatId && currentState.currentChatId === payload.draftId) || // Match final ID against draftId
			(!currentState.currentChatId && currentState.currentTempDraftId === payload.draftId) // Match temp ID against draftId
		) {
			console.error(
				`[DraftService] Draft conflict detected for current draft (ID: ${relevantId}). Fetching latest state...`
			);
			// Send request to get the latest chat details from the server
			const chatIdToFetch = currentState.currentChatId ?? payload.chatId; // Prefer confirmed chatId if available
			if (chatIdToFetch) {
				webSocketService.sendMessage('get_chat_details', { chatId: chatIdToFetch });
			} else {
				console.error('[DraftService] Cannot fetch chat details for conflict: No chatId available.');
				// Maybe reset hasUnsavedChanges flag here? Or notify user?
			}
			// Keep current state for now, handleChatDetails will update it
			return currentState;
		} else {
			console.info(`[DraftService] Received draft_conflict for different context. Ignoring.`);
			return currentState;
		}
	});
};

// Handler for receiving full chat details after conflict or other request
const handleChatDetails = async (payload: ChatDetailsPayload) => {
	console.info(`[DraftService] Received chat_details:`, payload);
	let dbOperationSuccess = false;
	try {
		// 1. Update IndexedDB with the authoritative data
		// Ensure the payload conforms to the Chat type expected by the DB
		const chatToUpdate: Chat = {
			...payload, // Spread the payload
			// Ensure date fields are Date objects if they arrive as strings
			createdAt: payload.createdAt ? new Date(payload.createdAt) : new Date(),
			updatedAt: payload.updatedAt ? new Date(payload.updatedAt) : new Date(),
			lastMessageTimestamp: payload.lastMessageTimestamp
				? new Date(payload.lastMessageTimestamp)
				: null,
			// Ensure messages have Date objects
			messages:
				payload.messages?.map((msg) => ({
					...msg,
					createdAt: msg.createdAt ? new Date(msg.createdAt) : new Date()
				})) ?? [],
			// Ensure defaults for potentially missing fields
			title: payload.title ?? '',
			draft: payload.draft ?? null,
			version: payload.version ?? 0,
			isPersisted: payload.isPersisted ?? false,
			mates: payload.mates ?? [],
			unreadCount: payload.unreadCount ?? 0
		};
		await chatDB.updateChat(chatToUpdate); // Use updateChat (put) to add or replace
		dbOperationSuccess = true;
		console.info(`[DraftService] Updated/Added chat ${payload.id} in DB from chat_details.`);

		// 2. Update draftState and editor if this is the currently active chat
		draftState.update((currentState) => {
			if (currentState.currentChatId === payload.id) {
				console.info(
					`[DraftService] Updating current draft context with fetched details for chat ${payload.id}`
				);
				const editorInstance = getEditorInstance();
				// Update editor content only if it exists
				if (editorInstance) {
					const contentToSet = payload.draft || getInitialContent();
					console.debug('[DraftService] Setting editor content from chat_details:', contentToSet);
					// Use chain to avoid triggering update event
					editorInstance.chain().setContent(contentToSet, false).run();
					// Refocus after a delay
					setTimeout(() => editorInstance?.commands.focus('end'), 50);
				}
				return {
					...currentState,
					currentVersion: payload.version ?? 0, // Use version from payload
					hasUnsavedChanges: false // Reset flag as we now have the authoritative state
				};
			}
			return currentState; // No change if not the current chat
		});
	} catch (error) {
		console.error('[DraftService] Error handling chat_details:', error);
	}

	// Dispatch event after successful DB operation from WS handler
	if (dbOperationSuccess) {
		console.debug(
			'[DraftService] Dispatching local chat list changed event after handling chat_details WS message.'
		);
		window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT));
	}
};

export function registerWebSocketHandlers() {
	console.info('[DraftService] Registering WebSocket handlers.');
	webSocketService.on('draft_updated', handleDraftUpdated);
	webSocketService.on('draft_conflict', handleDraftConflict);
	webSocketService.on('chat_details', handleChatDetails);
}

export function unregisterWebSocketHandlers() {
	console.info('[DraftService] Unregistering WebSocket handlers.');
	webSocketService.off('draft_updated', handleDraftUpdated);
	webSocketService.off('draft_conflict', handleDraftConflict);
	webSocketService.off('chat_details', handleChatDetails);
}
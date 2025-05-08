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

	// stateBeforeUpdate.currentChatId is the client's UUID
	// payload.id is the client's UUID from the server
	// payload.user_id is the 10-char user hash suffix from the server
	// payload.chatId is the server's composite ID (user_hash_suffix + client_uuid)

	console.info(
		`[DraftService] Received draft_updated. Payload:`, payload, `Current State:`, stateBeforeUpdate
	);

	// Relevance Check: Is this update for the draft currently being edited?
	// Match if the client UUID in the payload matches the client UUID in our current state.
	const isRelevantUpdate = stateBeforeUpdate.currentChatId === payload.id;
	let dbOperationSuccess = false;

	if (isRelevantUpdate) {
		const newVersion = payload.basedOnVersion;
		const clientUUID = payload.id; // This is our primary local ID
		const serverUserIDSuffix = payload.user_id; // The 10-char hash part

		console.info(
			`[DraftService] Confirmed update for current draft (Client UUID: ${clientUUID}). New version: ${newVersion}, Server UserID Suffix: ${serverUserIDSuffix}`
		);

		try {
			const existingChat = await chatDB.getChat(clientUUID);
			if (existingChat) {
				const updatedChat: Chat = {
					...existingChat,
					id: clientUUID, // Ensure this is the client UUID
					user_id: serverUserIDSuffix, // Update with the server-provided user_id
					version: newVersion,
					isPersisted: true, // Now confirmed by server, so it's persisted
					updatedAt: new Date(),
					draft: payload.content ?? existingChat.draft,
					// title might be updated by a separate mechanism or kept as is
				};
				const chatBeforeDbUpdateAttempt = JSON.parse(JSON.stringify(existingChat));
				console.debug(`[DraftService] Attempting to update chat in DB. Client UUID: ${clientUUID}. Current DB Version: ${chatBeforeDbUpdateAttempt.version}. New Version from Server: ${newVersion}. Chat object to save:`, JSON.parse(JSON.stringify(updatedChat)));
				await chatDB.updateChat(updatedChat);
				const chatAfterDbUpdateAttempt = await chatDB.getChat(clientUUID);
				console.info(
					`[DraftService] Updated chat in DB: Client UUID ${clientUUID}, Version FROM PAYLOAD: ${newVersion}, UserID Suffix: ${serverUserIDSuffix}. Chat in DB AFTER update:`, JSON.parse(JSON.stringify(chatAfterDbUpdateAttempt))
				);
				dbOperationSuccess = true;
			} else {
				// This case should ideally not happen if isRelevantUpdate is true and a draft was being edited.
				// However, if it does, it means a new chat was created and confirmed by the server.
				console.warn(
					`[DraftService] Chat with Client UUID ${clientUUID} not found in DB for an update, but was relevant. Creating new entry.`
				);
				const newChat: Chat = {
					id: clientUUID,
					user_id: serverUserIDSuffix,
					title: '', // Default title for new
					draft: payload.content ?? null,
					version: newVersion,
					messages: [],
					createdAt: new Date(), // Approximation
					updatedAt: new Date(),
					lastMessageTimestamp: null,
					isPersisted: true,
					mates: [],
					unreadCount: 0
				};
				await chatDB.addChat(newChat);
				dbOperationSuccess = true;
			}
		} catch (dbError) {
			console.error(
				`[DraftService] Error updating/adding chat in DB for Client UUID ${clientUUID}:`, dbError
			);
		}

		// Update the Svelte store state
		draftState.update((currentState) => {
			// Check relevance again in case state changed during async DB ops
			if (currentState.currentChatId === clientUUID) {
				const newStateForDraftUpdate = {
					...currentState,
					// currentChatId remains clientUUID
					// user_id is no longer in draftState
					currentVersion: newVersion,
					hasUnsavedChanges: false, // Mark changes as saved/confirmed
					// newlyCreatedChatIdToSelect should have been clientUUID if it was new,
					// and Chats.svelte would consume it. If it's still set, keep it.
					newlyCreatedChatIdToSelect: currentState.newlyCreatedChatIdToSelect === clientUUID ? clientUUID : null
				};
				console.debug('[DraftService] draftState WILL BE UPDATED by handleDraftUpdated. Client UUID:', clientUUID, 'New State:', newStateForDraftUpdate);
				return newStateForDraftUpdate;
			}
			console.warn(
				`[DraftService] State changed during async DB op for draft_updated. Ignoring state update. Payload:`, payload
			);
			return currentState;
		});

	} else { // Update is for a non-active chat (e.g., updated on another device)
		console.info(`[DraftService] Received draft_updated for different context (Client UUID: ${payload.id}).`);
		try {
			const clientUUIDForNonActive = payload.id;
			const serverUserIDSuffixForNonActive = payload.user_id;
			const existingChat = await chatDB.getChat(clientUUIDForNonActive);

			if (!existingChat) {
				console.info(
					`[DraftService] Non-active chat ${clientUUIDForNonActive} not in DB. Creating new local entry.`
				);
				const newChatEntry: Chat = {
					id: clientUUIDForNonActive,
					user_id: serverUserIDSuffixForNonActive,
					title: '', // Default
					draft: payload.content ?? null,
					version: payload.basedOnVersion,
					messages: [],
					createdAt: new Date(), // Approx
					updatedAt: new Date(),
					lastMessageTimestamp: null,
					isPersisted: true, // Confirmed by server
					mates: [],
					unreadCount: 0
				};
				await chatDB.addChat(newChatEntry);
				dbOperationSuccess = true;
			} else {
				console.info(
					`[DraftService] Updating non-active, existing chat ${clientUUIDForNonActive} in DB.`
				);
				const updatedChatEntry: Chat = {
					...existingChat,
					id: clientUUIDForNonActive,
					user_id: serverUserIDSuffixForNonActive,
					version: payload.basedOnVersion,
					draft: payload.content ?? existingChat.draft,
					updatedAt: new Date(),
					isPersisted: true
				};
				await chatDB.updateChat(updatedChatEntry);
				dbOperationSuccess = true;
			}
		} catch (error) {
			console.error(
				`[DraftService] Error handling non-active chat ${payload.id} from draft_updated:`, error
			);
		}
	}

	if (dbOperationSuccess) {
		console.debug(
			'[DraftService] Dispatching local chat list changed event after handling draft_updated WS.'
		);
		window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT));
	}
};

const handleDraftConflict = (payload: DraftConflictPayload) => {
	// payload.id is the client UUID
	// payload.chatId is the server's composite ID
	draftState.update((currentState) => {
		console.warn(`[DraftService] Received draft_conflict event. Client UUID: ${payload.id}, Server Chat ID: ${payload.chatId}`);

		// Only handle if conflict is for the current draft (match by client UUID)
		if (currentState.currentChatId === payload.id) {
			console.error(
				`[DraftService] Draft conflict for current draft (Client UUID: ${payload.id}). Fetching latest state...`
			);
			// Server expects the composite chatId to fetch details
			if (payload.chatId) {
				webSocketService.sendMessage('get_chat_details', { chatId: payload.chatId });
			} else {
				// This case should ideally not happen if server sends composite chatId on conflict
				console.error('[DraftService] Cannot fetch chat details for conflict: Server composite chatId missing in payload.');
			}
			return currentState; // Keep current state, handleChatDetails will update
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

let handleWsOpen: (() => void) | null = null;

export function registerWebSocketHandlers() {
	console.info('[DraftService] Registering WebSocket handlers.');
	webSocketService.on('draft_updated', handleDraftUpdated);
	webSocketService.on('draft_conflict', handleDraftConflict);
	webSocketService.on('chat_details', handleChatDetails);

	// Listen for WebSocket reconnect/open and re-sync current draft
	handleWsOpen = async () => {
		const state = get(draftState);
		if (state.currentChatId) {
			try {
				const chat = await chatDB.getChat(state.currentChatId);
				if (chat && chat.user_id) {
					const compositeChatId = `${chat.user_id}_${state.currentChatId}`;
					console.info('[DraftService] WebSocket reconnected. Requesting latest chat details for composite ID:', compositeChatId);
					webSocketService.sendMessage('get_chat_details', { chatId: compositeChatId });
				} else if (chat) {
					// If chat exists but user_id is somehow missing, maybe it's a purely local draft
					// or an older chat that hasn't been synced with user_id yet.
					// In this scenario, sending just the client UUID might be appropriate if the backend can handle it,
					// or we might not be able to re-sync this specific draft without user_id.
					// For now, we'll assume 'get_chat_details' primarily uses composite ID.
					console.warn(`[DraftService] WebSocket reconnected. Chat ${state.currentChatId} found but missing user_id. Cannot form composite ID for get_chat_details.`);
					// Optionally, attempt with client UUID if backend supports it for drafts not yet associated with a user_id on server.
					// webSocketService.sendMessage('get_chat_details', { chatId: state.currentChatId });
				} else {
					console.warn(`[DraftService] WebSocket reconnected. Chat ${state.currentChatId} not found in DB. Cannot re-sync.`);
				}
			} catch (error) {
				console.error(`[DraftService] Error fetching chat ${state.currentChatId} from DB on WebSocket open:`, error);
			}
		}
	};
	webSocketService.on('open', handleWsOpen);
}

export function unregisterWebSocketHandlers() {
	console.info('[DraftService] Unregistering WebSocket handlers.');
	webSocketService.off('draft_updated', handleDraftUpdated);
	webSocketService.off('draft_conflict', handleDraftConflict);
	webSocketService.off('chat_details', handleChatDetails);
	if (handleWsOpen) {
		webSocketService.off('open', handleWsOpen);
		handleWsOpen = null;
	}
}
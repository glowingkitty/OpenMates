import { get } from 'svelte/store';
import { chatDB } from '../db';
import { webSocketService } from '../websocketService';
import type { Chat, TiptapJSON } from '../../types/chat'; // Adjusted path, TiptapJSON might be from here or draftTypes
import { getInitialContent } from '../../components/enter_message/utils'; // Adjusted path
import { draftEditorUIState } from './draftState'; // Renamed store
import type {
	DraftEditorState, // Renamed type
	ServerChatDraftUpdatedEventPayload, // Updated payload type
	DraftConflictPayload,
	   ChatDetailsServerResponse, // Added for specific server response type
	   UserChatDraft,
	   TiptapJSON as DraftTiptapJSON // Alias for clarity if TiptapJSON is also from ../../types/chat
} from './draftTypes';
import { LOCAL_CHAT_LIST_CHANGED_EVENT } from './draftConstants';
import { getEditorInstance } from './draftCore';

// --- WebSocket Handlers ---

const handleDraftUpdated = async (payload: ServerChatDraftUpdatedEventPayload) => {
	// Use get for synchronous access to avoid async issues within update
	const currentEditorState = get(draftEditorUIState);

	if (!currentEditorState) {
		console.error('[DraftService] Could not get current draft editor state in handleDraftUpdated.');
		return;
	}

	const { chat_id, data, versions, last_edited_overall_timestamp } = payload;
    const { draft_json } = data;
    const { user_draft_v: newUserDraftVersion } = versions;

	console.info(
		`[DraftService] Received chat_draft_updated for chat_id: ${chat_id}. New version: ${newUserDraftVersion}. Payload:`, payload
	);

	let dbOperationSuccess = false;

    // Update the user's draft in IndexedDB
    try {
        const existingDraft = await chatDB.getUserChatDraft(chat_id);
        const updatedDraft: UserChatDraft = {
            chat_id: chat_id,
            draft_json: draft_json,
            version: newUserDraftVersion,
            last_edited_timestamp: last_edited_overall_timestamp // Use server's timestamp
        };
        await chatDB.addOrUpdateUserChatDraft(updatedDraft);
        console.info(`[DraftService] Updated/Added user draft for chat ${chat_id} in DB. Version: ${newUserDraftVersion}`);
        dbOperationSuccess = true;

        // Also update the parent chat's last_edited_overall_timestamp
        const chat = await chatDB.getChat(chat_id);
        if (chat) {
            chat.last_edited_overall_timestamp = last_edited_overall_timestamp;
            chat.updatedAt = new Date(last_edited_overall_timestamp * 1000); // Convert to Date
            await chatDB.updateChat(chat);
        }

    } catch (dbError) {
        console.error(`[DraftService] Error updating/adding user draft in DB for chat ${chat_id}:`, dbError);
    }

	// Relevance Check: Is this update for the draft currently being edited in the UI?
	if (currentEditorState.currentChatId === chat_id) {
		console.info(`[DraftService] Confirmed update for current draft UI (chat_id: ${chat_id}). New version: ${newUserDraftVersion}`);
		
		// Update the Svelte store state for the editor UI
		draftEditorUIState.update((currentState) => {
			// Check relevance again in case state changed during async DB ops
			if (currentState.currentChatId === chat_id) {
				const newState: DraftEditorState = {
					...currentState,
					currentUserDraftVersion: newUserDraftVersion,
					hasUnsavedChanges: false, // Mark changes as saved/confirmed from server
				};
				console.debug('[DraftService] draftEditorUIState WILL BE UPDATED. Chat ID:', chat_id, 'New State:', newState);
				return newState;
			}
			console.warn(
				`[DraftService] Editor state changed during async DB op for chat_draft_updated. Ignoring UI state update. Payload:`, payload
			);
			return currentState;
		});

        // Optionally, update the Tiptap editor instance directly if it's the active chat
        // This is usually handled by reactive Svelte bindings to the draft content store,
        // but if direct manipulation is needed:
        const editorInstance = getEditorInstance();
        if (editorInstance && editorInstance.isEditable) {
             // Check if editor content needs updating (e.g., if this update came from another device)
            const currentEditorContent = editorInstance.getJSON();
            if (JSON.stringify(currentEditorContent) !== JSON.stringify(draft_json)) {
                console.debug(`[DraftService] Updating Tiptap editor content for active chat ${chat_id} from WebSocket.`);
                editorInstance.chain().setContent(draft_json || getInitialContent(), false).run();
            }
        }

	} else {
        // Update is for a non-active chat (e.g., updated on another device by this same user)
		console.info(`[DraftService] Received chat_draft_updated for non-active chat (chat_id: ${chat_id}). DB already updated.`);
	}

	if (dbOperationSuccess) {
		console.debug(
			'[DraftService] Dispatching local chat list changed event after handling chat_draft_updated WS.'
		);
		// This event might trigger UI refresh for chat list items if they display draft snippets.
		window.dispatchEvent(new CustomEvent(LOCAL_CHAT_LIST_CHANGED_EVENT, { detail: { chat_id } }));
	}
};

const handleDraftConflict = (payload: DraftConflictPayload) => {
	// payload.chat_id is the server's composite ID
	draftEditorUIState.update((currentState) => {
		console.warn(`[DraftService] Received draft_conflict event. Server Chat ID: ${payload.chat_id}`);

		// Only handle if conflict is for the current draft (match by chat_id)
		if (currentState.currentChatId === payload.chat_id) {
			console.error(
				`[DraftService] Draft conflict for current draft (Chat ID: ${payload.chat_id}). Fetching latest state...`
			);
			// Server expects the composite chat_id to fetch details
			if (payload.chat_id) {
				webSocketService.sendMessage('get_chat_details', { chat_id: payload.chat_id });
			} else {
				// This case should ideally not happen if server sends composite chat_id on conflict
				console.error('[DraftService] Cannot fetch chat details for conflict: Server composite chat_id missing in payload.');
			}
			return currentState; // Keep current state, handleChatDetails will update
		} else {
			console.info(`[DraftService] Received draft_conflict for different context (current: ${currentState.currentChatId}, conflict: ${payload.chat_id}). Ignoring.`);
			return currentState;
		}
	});
};

// Handler for receiving full chat details after conflict or other request
const handleChatDetails = async (payload: ChatDetailsServerResponse) => { // Changed Chat to ChatDetailsServerResponse
	console.info(`[DraftService] Received chat_details:`, payload); // payload is of type ChatDetailsServerResponse
	let dbOperationSuccess = false;
	try {
		// The payload for 'chat_details' might still be based on the old 'Chat' type.
		// We need to adapt it to the new structure: separate Chat and UserChatDraft.
		
		// 1. Update Chat entity in IndexedDB (without draft fields)
		const chatToUpdate: Chat = { // Assuming Chat type is updated to exclude draft fields
			chat_id: payload.chat_id, // Use chat_id from payload
			title: payload.title ?? '',
			messages_v: payload.messages_v ?? 0,
			title_v: payload.title_v ?? 0,
			last_edited_overall_timestamp: payload.last_edited_overall_timestamp ?? Math.floor(Date.now()/1000),
			unread_count: payload.unread_count ?? 0,
			messages: payload.messages?.map((msg: any) => ({ // Ensure messages are correctly typed
					...msg,
					timestamp: msg.timestamp ? msg.timestamp : Math.floor(new Date(msg.createdAt).getTime() / 1000) // Ensure timestamp is number
				})) ?? [],
			createdAt: payload.createdAt ? new Date(payload.createdAt) : new Date(),
			updatedAt: payload.updatedAt ? new Date(payload.updatedAt) : new Date(),
			// Removed: draft_content, draft_v, draft_version_db
	           // Ensure all fields expected by the current Chat type are present
		};
		await chatDB.updateChat(chatToUpdate);
		dbOperationSuccess = true;
		console.info(`[DraftService] Updated/Added chat ${payload.chat_id} in DB from chat_details.`);

	       // 2. Update UserChatDraft in IndexedDB if draft content is part of the payload
	       // The 'chat_details' event might not carry the user-specific draft anymore,
	       // or it might. This depends on the server's implementation of 'get_chat_details'.
	       // For now, let's assume it *might* carry the current user's draft.
	       // The backend's `ChatResponse` schema still has a `draft` field.
	       if (payload.draft_content !== undefined) { // Check if draft content is present
	           const userDraftToUpdate: UserChatDraft = {
	               chat_id: payload.chat_id,
	               draft_json: payload.draft_content, // This is the decrypted draft from server
	               version: payload.draft_v ?? 0, // This would be the user's draft version
	               last_edited_timestamp: payload.updatedAt ? Math.floor(new Date(payload.updatedAt).getTime() / 1000) : Math.floor(Date.now()/1000)
	           };
	           await chatDB.addOrUpdateUserChatDraft(userDraftToUpdate);
	           console.info(`[DraftService] Updated/Added user draft for chat ${payload.chat_id} from chat_details.`);
	       }

		// 3. Update draftEditorUIState and editor if this is the currently active chat
		draftEditorUIState.update((currentState) => {
			if (currentState.currentChatId === payload.chat_id) {
				console.info(
					`[DraftService] Updating current draft context with fetched details for chat ${payload.chat_id}`
				);
				const editorInstance = getEditorInstance();
				if (editorInstance) {
					const contentToSet = payload.draft_content || getInitialContent(); // Use draft_content from payload
					console.debug('[DraftService] Setting editor content from chat_details:', contentToSet);
					editorInstance.chain().setContent(contentToSet, false).run();
					setTimeout(() => editorInstance?.commands.focus('end'), 50);
				}
				return {
					...currentState,
					currentUserDraftVersion: payload.draft_v ?? 0, // Use user's draft version
					hasUnsavedChanges: false
				};
			}
			return currentState;
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
		const state = get(draftEditorUIState); // Use renamed store
		if (state.currentChatId) {
			try {
				// On reconnect, the client should send its current versions to the server
				// as part of the initial sync process (chat_sync_architecture.md Section 5).
				// The server will then respond with deltas.
				// Forcing a 'get_chat_details' might be redundant if initial sync handles this.
				// However, if we want to ensure the currently viewed chat is absolutely up-to-date:
				console.info(`[DraftService] WebSocket reconnected. Requesting latest details for active chat: ${state.currentChatId}`);
				webSocketService.sendMessage('get_chat_details', { chat_id: state.currentChatId });
			} catch (error) {
				console.error(`[DraftService] Error processing active chat ${state.currentChatId} on WebSocket open:`, error);
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
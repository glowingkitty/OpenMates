import { get } from 'svelte/store';
import { chatDB } from '../db';
import { webSocketService } from '../websocketService';
import { chatMetadataCache } from '../chatMetadataCache';
import type { Chat, Message, TiptapJSON } from '../../types/chat'; // Adjusted path, TiptapJSON might be from here or draftTypes
import { getInitialContent } from '../../components/enter_message/utils'; // Adjusted path
import { draftEditorUIState } from './draftState'; // Renamed store
import { decryptWithMasterKey } from '../cryptoService'; // Import decryption
import { parse_message } from '../../message_parsing/parse_message'; // Import parser
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
	   const { encrypted_draft_md, encrypted_draft_preview } = data;
	   const { draft_v: newUserDraftVersion } = versions; // Corrected: ChatComponentVersions uses draft_v

	console.info(
		`[DraftService] Received chat_draft_updated for chat_id: ${chat_id}. New version: ${newUserDraftVersion}. Payload:`, payload
	);

	let dbOperationSuccess = false;

    // Update the user's draft directly within the Chat object in IndexedDB
    try {
        const chat = await chatDB.getChat(chat_id);
        if (chat) {
            chat.encrypted_draft_md = encrypted_draft_md; // from payload.data
            chat.encrypted_draft_preview = encrypted_draft_preview || null; // from payload.data
            chat.draft_v = newUserDraftVersion; // from payload.versions (corrected)
            // CRITICAL: Don't update last_edited_overall_timestamp from draft updates
            // Only messages should update this timestamp for proper sorting
            // Chats with drafts will appear at the top via sorting logic, but won't affect message-based sorting
            // chat.last_edited_overall_timestamp = last_edited_overall_timestamp; // REMOVED
            chat.updated_at = last_edited_overall_timestamp; // Keep updated_at for internal tracking

            await chatDB.updateChat(chat);
            console.info(`[DraftService] Updated chat ${chat_id} with new draft in DB. Version: ${newUserDraftVersion}`);
            // Invalidate metadata cache since draft content changed
            chatMetadataCache.invalidateChat(chat_id);
            dbOperationSuccess = true;
        } else {
            console.warn(`[DraftService] Chat ${chat_id} not found in DB to update draft from WebSocket.`);
            // If the chat doesn't exist, we cannot update its draft.
            // This might indicate a race condition or an issue where a draft update arrives for a deleted/non-existent chat.
        }
    } catch (dbError) {
        console.error(`[DraftService] Error updating chat with draft in DB for chat ${chat_id}:`, dbError);
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
					currentUserDraftVersion: newUserDraftVersion, // Use newUserDraftVersion from payload
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
            // Decrypt the draft content first
            let decryptedDraftContent: TiptapJSON | null = null;
            if (encrypted_draft_md) {
                try {
                    const decryptedMarkdown = decryptWithMasterKey(encrypted_draft_md);
                    if (decryptedMarkdown) {
                        // Parse markdown back to TipTap JSON
                        decryptedDraftContent = parse_message(decryptedMarkdown, 'write', { unifiedParsingEnabled: true });
                    }
                } catch (error) {
                    console.error('[DraftService] Error decrypting draft content for editor update:', error);
                }
            }
            
             // Check if editor content needs updating (e.g., if this update came from another device)
            const currentEditorContent = editorInstance.getJSON();
            if (JSON.stringify(currentEditorContent) !== JSON.stringify(decryptedDraftContent)) {
                console.debug(`[DraftService] Updating Tiptap editor content for active chat ${chat_id} from WebSocket.`);
                editorInstance.chain().setContent(decryptedDraftContent || getInitialContent(), false).run();
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
		
		// 1. Update Chat entity in IndexedDB, including draft fields
		const chatToUpdate: Chat = {
			chat_id: payload.chat_id,
			title: payload.encrypted_title ? decryptWithMasterKey(payload.encrypted_title) : null,
			encrypted_title: null,
			messages_v: payload.messages_v ?? 0,
			title_v: payload.title_v ?? 0,
			encrypted_draft_md: payload.encrypted_draft_md, // Encrypted draft content from payload
			draft_v: payload.draft_v ?? 0,      // Draft version from payload
			last_edited_overall_timestamp: payload.last_edited_overall_timestamp ?? Math.floor(Date.now()/1000),
			unread_count: payload.unread_count ?? 0,
			mates: (payload as any).mates ?? [],
			created_at: (payload as any).created_at ?? Math.floor(Date.now() / 1000),
			updated_at: (payload as any).updated_at ?? Math.floor(Date.now() / 1000),
		};

		await chatDB.addOrUpdateChatWithFullData(chatToUpdate, []);
		dbOperationSuccess = true;
		console.info(`[DraftService] Updated/Added chat ${payload.chat_id} (including draft) in DB from chat_details.`);

		   // Section for separate UserChatDraft update is removed as draft is part of Chat object.

		// 2. Update draftEditorUIState and editor if this is the currently active chat
		draftEditorUIState.update((currentState) => {
			if (currentState.currentChatId === payload.chat_id) {
				console.info(
					`[DraftService] Updating current draft context with fetched details for chat ${payload.chat_id}`
				);
				const editorInstance = getEditorInstance();
				if (editorInstance) {
					// Decrypt the draft content first
					let contentToSet: TiptapJSON = getInitialContent();
					if (payload.encrypted_draft_md) {
						try {
							const decryptedMarkdown = decryptWithMasterKey(payload.encrypted_draft_md);
							if (decryptedMarkdown) {
								// Parse markdown back to TipTap JSON
								contentToSet = parse_message(decryptedMarkdown, 'write', { unifiedParsingEnabled: true });
							}
						} catch (error) {
							console.error('[DraftService] Error decrypting draft content from chat_details:', error);
						}
					}
					console.debug('[DraftService] Setting editor content from chat_details:', contentToSet);
					editorInstance.chain().setContent(contentToSet, false).run();
					// Do NOT auto-focus the editor - user must manually click to focus
					// This prevents unwanted focus when receiving draft updates from websocket
					console.debug('[DraftService] Skipped auto-focus after websocket draft update - user must click to focus');
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

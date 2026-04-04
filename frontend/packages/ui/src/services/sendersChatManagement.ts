/**
 * sendersChatManagement.ts — Chat CRUD operations
 *
 * Contains sender functions for chat-level management: updating titles,
 * deleting chats, deleting messages, updating chat keys (hide/unhide),
 * and setting the active chat for cross-device sync.
 *
 * Split from chatSyncServiceSenders.ts for maintainability (Phase 04, Plan 01).
 * See docs/architecture/ for the encryption and sync architecture.
 */
import type { ChatSynchronizationService } from "./chatSyncService";
import { chatDB } from "./db";
import { webSocketService } from "./websocketService";
import { notificationStore } from "../stores/notificationStore";
import { get } from "svelte/store";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { encryptWithChatKey } from "./encryption/MessageEncryptor";
import type {
	UpdateTitlePayload,
	DeleteChatPayload,
	DeleteMessagePayload,
	SetActiveChatPayload
} from "../types/chat";

export async function sendUpdateTitleImpl(
	serviceInstance: ChatSynchronizationService,
	chat_id: string,
	new_title: string
): Promise<void> {
	// Get chat key — user has this chat open, key should be in cache
	let chatKey = chatKeyManager.getKeySync(chat_id);
	if (!chatKey) {
		chatKey = await chatKeyManager.getKey(chat_id);
	}
	if (!chatKey) {
		console.error(
			`[ChatSyncService:Senders] No chat key available for title encryption (chat ${chat_id})`
		);
		notificationStore.error("Failed to encrypt title - chat key not available");
		return;
	}

	// Encrypt title with chat-specific key for server storage/syncing
	const encryptedTitle = await encryptWithChatKey(new_title, chatKey);
	if (!encryptedTitle) {
		notificationStore.error("Failed to encrypt title - encryption returned null");
		return;
	}

	// OPE-314: Include encrypted_chat_key for server-side key validation.
	// Prevents persisting a title encrypted with a stale key from a secondary device.
	const chatRecord = await chatDB.getChat(chat_id);
	const payload: UpdateTitlePayload & { encrypted_chat_key?: string } = {
		chat_id,
		encrypted_title: encryptedTitle
	};
	if (chatRecord?.encrypted_chat_key) {
		payload.encrypted_chat_key = chatRecord.encrypted_chat_key;
	}
	const tx = await chatDB.getTransaction(chatDB["CHATS_STORE_NAME"], "readwrite");
	try {
		const chat = await chatDB.getChat(chat_id, tx);
		if (chat) {
			// Update encrypted title and version
			chat.encrypted_title = encryptedTitle;
			chat.title_v = (chat.title_v || 0) + 1; // Frontend increments title_v
			chat.updated_at = Math.floor(Date.now() / 1000);
			await chatDB.updateChat(chat, tx); // This will encrypt for IndexedDB storage
			tx.oncomplete = () => {
				serviceInstance.dispatchEvent(
					new CustomEvent("chatUpdated", {
						detail: { chat_id, type: "title_updated", chat }
					})
				);
			};
			tx.onerror = () =>
				console.error(
					"[ChatSyncService:Senders] Error in sendUpdateTitle optimistic transaction:",
					tx.error
				);
		} else {
			if (tx.abort) tx.abort();
		}
	} catch (error) {
		console.error(
			"[ChatSyncService:Senders] Error in sendUpdateTitle optimistic update:",
			error
		);
		if (tx.abort && !tx.error) tx.abort();
	}
	await webSocketService.sendMessage("update_title", payload);
}

/**
 * Send delete chat request to server
 * NOTE: The actual deletion from IndexedDB should be done by the caller (e.g., Chat.svelte)
 * before calling this function. This function only handles server communication.
 * NOTE: The chatDeleted event is now dispatched by the caller (Chat.svelte) after IndexedDB deletion
 * to ensure proper UI update timing.
 * @param chat_id - The ID of the chat to delete
 * @param embed_ids_to_delete - Optional array of embed IDs that were deleted from IndexedDB
 *                              Server will verify these embeds are not used by other chats before deleting from Directus
 */
export async function sendDeleteChatImpl(
	serviceInstance: ChatSynchronizationService,
	chat_id: string,
	embed_ids_to_delete: string[] = []
): Promise<void> {
	// Include embed_ids in the payload for server-side cleanup
	// Server will check if each embed is used by any other chat (not in last 100)
	// before permanently deleting from Directus
	const payload: DeleteChatPayload & { embed_ids_to_delete?: string[] } = {
		chatId: chat_id,
		embed_ids_to_delete:
			embed_ids_to_delete.length > 0 ? embed_ids_to_delete : undefined
	};

	try {
		// Send delete request to server
		console.debug(
			`[ChatSyncService:Senders] Sending delete_chat request to server for chat ${chat_id}`,
			{
				embedIdsToDelete: embed_ids_to_delete.length
			}
		);
		await webSocketService.sendMessage("delete_chat", payload);
		console.debug(
			`[ChatSyncService:Senders] Delete request sent successfully for chat ${chat_id} with ${embed_ids_to_delete.length} embed deletions`
		);

		// NOTE: chatDeleted event is now dispatched by Chat.svelte after IndexedDB deletion
		// to ensure proper UI update timing. No need to dispatch it here.
	} catch (error) {
		console.error(
			`[ChatSyncService:Senders] Error sending delete_chat request for chat ${chat_id}:`,
			error
		);
		throw error; // Re-throw so caller can handle the error
	}
}

/**
 * Send delete message request to server.
 * NOTE: The actual deletion from IndexedDB should be done by the caller
 * before calling this function. This function only handles server communication.
 * @param chat_id - The ID of the chat containing the message
 * @param message_id - The client_message_id of the message to delete
 * @param embed_ids_to_delete - Optional array of embed IDs to delete on the server (not shared with other chats)
 */
export async function sendDeleteMessageImpl(
	serviceInstance: ChatSynchronizationService,
	chat_id: string,
	message_id: string,
	embed_ids_to_delete?: string[]
): Promise<void> {
	const payload: DeleteMessagePayload = {
		chatId: chat_id,
		messageId: message_id
	};

	// Include embed IDs if any need server-side cleanup
	if (embed_ids_to_delete && embed_ids_to_delete.length > 0) {
		payload.embedIdsToDelete = embed_ids_to_delete;
	}

	try {
		console.debug(
			`[ChatSyncService:Senders] Sending delete_message request to server for message ${message_id} in chat ${chat_id}` +
				(embed_ids_to_delete?.length
					? ` (${embed_ids_to_delete.length} embeds to delete)`
					: "")
		);
		await webSocketService.sendMessage("delete_message", payload);
		console.debug(
			`[ChatSyncService:Senders] Delete message request sent successfully for message ${message_id}`
		);
	} catch (error) {
		console.error(
			`[ChatSyncService:Senders] Error sending delete_message request for message ${message_id}:`,
			error
		);
		throw error;
	}
}

/**
 * Send encrypted_chat_key update to server for chat metadata sync
 * Used for hiding/unhiding chats by updating the encryption wrapper
 *
 * @param serviceInstance ChatSynchronizationService instance
 * @param chat_id Chat ID to update
 * @param encrypted_chat_key New encrypted chat key (encrypted with combined secret for hidden chats)
 */
export async function sendUpdateChatKeyImpl(
	serviceInstance: ChatSynchronizationService,
	chat_id: string,
	encrypted_chat_key: string
): Promise<void> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		console.warn(
			"[ChatSyncService:Senders] Cannot send encrypted_chat_key update - WebSocket not connected"
		);
		return;
	}

	try {
		// Get current chat to preserve version info
		const chat = await chatDB.getChat(chat_id);
		if (!chat) {
			console.error(
				`[ChatSyncService:Senders] Chat ${chat_id} not found for encrypted_chat_key update`
			);
			return;
		}

		// Create payload for encrypted_chat_metadata handler
		// This handler accepts encrypted_chat_key and updates it in Directus
		// message_id is optional - we omit it since we're only updating metadata
		const payload = {
			chat_id,
			encrypted_chat_key,
			// Explicitly allow chat key rotation for hidden chat hide/unhide flows.
			// This prevents accidental key overwrites from general message syncs.
			allow_chat_key_rotation: true,
			chat_key_rotation_reason: "hidden_chat",
			// Include version info to preserve chat state
			versions: {
				messages_v: chat.messages_v || 0,
				title_v: chat.title_v || 0,
				last_edited_overall_timestamp:
					chat.last_edited_overall_timestamp || Math.floor(Date.now() / 1000)
			}
		};

		console.debug(
			`[ChatSyncService:Senders] Sending encrypted_chat_key update for chat ${chat_id}`,
			{
				hasEncryptedChatKey: !!encrypted_chat_key,
				encryptedChatKeyLength: encrypted_chat_key?.length || 0,
				messagesV: payload.versions.messages_v,
				titleV: payload.versions.title_v
			}
		);

		// Send via encrypted_chat_metadata handler (backend supports updating just encrypted_chat_key)
		await webSocketService.sendMessage("encrypted_chat_metadata", payload);

		console.info(
			`[ChatSyncService:Senders] Successfully sent encrypted_chat_key update for chat ${chat_id}`
		);
	} catch (error) {
		console.error(
			`[ChatSyncService:Senders] Error sending encrypted_chat_key update for chat ${chat_id}:`,
			error
		);
		throw error;
	}
}

export async function sendSetActiveChatImpl(
	serviceInstance: ChatSynchronizationService,
	chatId: string | null
): Promise<void> {
	// Skip all IndexedDB and WebSocket operations for unauthenticated users.
	// Demo chats don't need last_opened tracking or server sync.
	const { authStore } = await import("../stores/authState");
	const isAuthenticated = get(authStore).isAuthenticated;
	if (!isAuthenticated) {
		console.debug(
			`[ChatSyncService:Senders] User not authenticated, skipping set_active_chat for: ${chatId}`
		);
		return;
	}

	// CRITICAL: Skip public/demo/legal chats — they are client-side-only static content
	// and must NEVER be persisted as last_opened. If sent to the server, demo chat IDs
	// (e.g. "demo-for-everyone") overwrite the real last_opened UUID, breaking the
	// "Continue where you left off" resume card on next login.
	if (chatId !== null) {
		const { isPublicChat } = await import("../demo_chats/convertToChat");
		if (isPublicChat(chatId)) {
			console.debug(
				`[ChatSyncService:Senders] Skipping set_active_chat for public/demo chat: ${chatId}`
			);
			return;
		}
	}

	// CRITICAL: Update IndexedDB immediately when switching chats (but NOT for new chat window).
	// This ensures tab reload uses the correct last_opened chat (from IndexedDB, not server).
	// The server update happens via WebSocket, but IndexedDB update is immediate for better UX.
	//
	// When chatId is null (new chat window), we intentionally do NOT update last_opened.
	// This preserves the previous real chat ID so the "Continue where you left off" resume card
	// always shows the last chat with actual content, not a blank new chat screen.
	// Signup paths (e.g. '/signup/one_time_codes') and '/chat/new' (signup completion) are passed
	// as explicit string values, not null, so they still get stored correctly.
	if (chatId !== null) {
		try {
			// Import userDB and updateProfile dynamically to avoid circular dependencies
			const { userDB } = await import("../services/userDB");
			const { updateProfile } = await import("../stores/userProfile");

			// Update IndexedDB with new last_opened chat
			// This is the source of truth for tab reload scenarios
			await userDB.updateUserData({ last_opened: chatId });

			// Also update the userProfile store to keep it in sync
			updateProfile({ last_opened: chatId });

			console.debug(
				`[ChatSyncService:Senders] Updated IndexedDB with last_opened: ${chatId}`
			);
		} catch (error) {
			console.error(
				`[ChatSyncService:Senders] Error updating IndexedDB with last_opened: ${chatId}:`,
				error
			);
			// Don't fail the whole operation if IndexedDB update fails
		}
	} else {
		console.debug(
			`[ChatSyncService:Senders] Skipping last_opened update for new chat window (preserving previous value)`
		);
	}

	// Send to server via WebSocket (for cross-device sync and login scenarios)
	// Note: Server handles null chatId by not updating last_opened (per backend logic)
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		console.warn(
			"[ChatSyncService:Senders] WebSocket not connected. Cannot send 'set_active_chat'."
		);
		return;
	}
	const payload: SetActiveChatPayload = { chat_id: chatId };
	try {
		await webSocketService.sendMessage("set_active_chat", payload);
		console.debug(
			`[ChatSyncService:Senders] Sent 'set_active_chat' to server: ${chatId}`
		);
	} catch (error) {
		console.error(
			`[ChatSyncService:Senders] Error sending 'set_active_chat' for chat_id: ${chatId}:`,
			error
		);
	}
}

/**
 * sendersSync.ts — Sync utilities, offline change management, and miscellaneous senders
 *
 * Contains sender functions for: offline change queueing and replay, scroll position
 * and read status sync, post-processing metadata sync, AI task/skill cancellation,
 * PDF processing cancellation, app settings/memories, new chat suggestions,
 * load-more-chats pagination, and inspiration chat sync.
 *
 * Split from chatSyncServiceSenders.ts for maintainability (Phase 04, Plan 01).
 * See docs/architecture/ for the sync and encryption architecture.
 */
import type { ChatSynchronizationService } from "./chatSyncService";
import { chatDB } from "./db";
import { webSocketService } from "./websocketService";
import { notificationStore } from "../stores/notificationStore";
import { get } from "svelte/store";
import { websocketStatus } from "../stores/websocketStatusStore";
import type {
	OfflineChange,
	CancelAITaskPayload,
	SyncOfflineChangesPayload
} from "../types/chat";

/**
 * Send a cancel_pdf_processing WebSocket message.
 *
 * Called when the user presses Stop on a PDF embed that is already in 'processing'
 * status (OCR task is running on the server). The server handler will:
 *   1. Revoke the Celery OCR task via /internal/pdf/cancel.
 *   2. Delete S3 files and the Directus upload_files record.
 *   3. Broadcast draft_embed_deleted to other devices for IndexedDB cleanup.
 *
 * Note: client-side node deletion (removing the embed from TipTap) is done by
 * the caller (Embed.ts cancelpdfupload handler) before calling this function.
 */
export async function sendCancelPdfProcessingImpl(
	_serviceInstance: ChatSynchronizationService,
	embed_id: string,
	chat_id?: string
): Promise<void> {
	try {
		await webSocketService.sendMessage("cancel_pdf_processing", {
			embed_id,
			chat_id: chat_id ?? null
		});
		console.debug(
			`[ChatSyncService:Senders] Sent cancel_pdf_processing for embed ${embed_id} (chat ${chat_id ?? "n/a"})`
		);
	} catch (error) {
		// Non-fatal: the PDF task will eventually complete or time out, and the embed
		// record will be cleaned up by the periodic billing reconciliation.
		console.error(
			`[ChatSyncService:Senders] Failed to send cancel_pdf_processing for embed ${embed_id}:`,
			error
		);
	}
}

/**
 * Sends app settings/memories confirmation to server.
 *
 * When user confirms app settings/memories request, client:
 * 1. Loads app settings/memories from IndexedDB (encrypted)
 * 2. Decrypts using app-specific keys
 * 3. Sends decrypted data to server (server encrypts with vault key and caches)
 *
 * Cache is chat-specific, so app settings/memories are automatically evicted
 * when the chat is evicted from cache.
 *
 * @param serviceInstance ChatSynchronizationService instance
 * @param chatId Chat ID where the request was made
 * @param appSettingsMemories Array of decrypted app settings/memories entries
 *                            Format: [{ app_id: string, item_key: string, content: any }, ...]
 */
export async function sendAppSettingsMemoriesConfirmedImpl(
	serviceInstance: ChatSynchronizationService,
	chatId: string,
	appSettingsMemories: Array<{
		app_id: string;
		item_key: string;
		content: unknown; // Decrypted content (will be JSON stringified by server)
	}>
): Promise<void> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		console.warn(
			"[ChatSyncService:Senders] WebSocket not connected. Cannot send 'app_settings_memories_confirmed'."
		);
		return;
	}

	// NOTE: Empty arrays ARE allowed - this indicates user rejected all categories
	// The server handler detects is_rejection=true when array is empty and continues
	// processing the AI request WITHOUT the app settings/memories data
	if (!appSettingsMemories || !Array.isArray(appSettingsMemories)) {
		console.warn(
			"[ChatSyncService:Senders] Invalid app settings/memories (not an array)"
		);
		return;
	}

	const payload = {
		chat_id: chatId,
		// Empty array signals rejection - server will continue processing without data
		app_settings_memories: appSettingsMemories.map((item) => ({
			app_id: item.app_id,
			item_key: item.item_key,
			content: item.content // Decrypted content - server will encrypt with vault key
		}))
	};

	try {
		await webSocketService.sendMessage("app_settings_memories_confirmed", payload);
		if (appSettingsMemories.length === 0) {
			console.info(
				`[ChatSyncService:Senders] Sent rejection (empty array) for chat ${chatId} - server will continue without app settings/memories`
			);
		} else {
			console.info(
				`[ChatSyncService:Senders] Sent ${appSettingsMemories.length} app settings/memories confirmations for chat ${chatId}`
			);
		}
	} catch (error) {
		console.error(
			`[ChatSyncService:Senders] Error sending 'app_settings_memories_confirmed' for chat_id: ${chatId}:`,
			error
		);
	}
}

/**
 * Sends an app settings/memories entry to server for permanent storage in Directus.
 *
 * This is used when creating entries from the App Store settings UI:
 * 1. Client encrypts entry with master key and stores in IndexedDB
 * 2. Client sends encrypted entry to server via this function
 * 3. Server stores encrypted entry in Directus (zero-knowledge - server never decrypts)
 * 4. Server broadcasts to other logged-in devices for multi-device sync
 *
 * @param serviceInstance ChatSynchronizationService instance
 * @param entry The encrypted app settings/memories entry to store
 */
export async function sendStoreAppSettingsMemoriesEntryImpl(
	serviceInstance: ChatSynchronizationService,
	entry: {
		id: string;
		app_id: string;
		item_key: string;
		item_type: string; // Category ID for filtering (e.g., 'preferred_technologies')
		encrypted_item_json: string;
		encrypted_app_key: string;
		created_at: number;
		updated_at: number;
		item_version: number;
		sequence_number?: number;
	}
): Promise<boolean> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		console.warn(
			"[ChatSyncService:Senders] WebSocket not connected. Cannot send 'store_app_settings_memories_entry'."
		);
		return false;
	}

	if (
		!entry ||
		!entry.id ||
		!entry.app_id ||
		!entry.item_key ||
		entry.encrypted_item_json === undefined
	) {
		console.error(
			"[ChatSyncService:Senders] Invalid entry data for store_app_settings_memories_entry"
		);
		return false;
	}

	const payload = { entry };

	try {
		await webSocketService.sendMessage("store_app_settings_memories_entry", payload);
		console.info(
			`[ChatSyncService:Senders] Sent app settings/memories entry ${entry.id} for app ${entry.app_id} to server`
		);
		return true;
	} catch (error) {
		console.error(
			`[ChatSyncService:Senders] Error sending 'store_app_settings_memories_entry' for entry ${entry.id}:`,
			error
		);
		return false;
	}
}

export async function sendCancelAiTaskImpl(
	serviceInstance: ChatSynchronizationService,
	taskId: string,
	chatId?: string
): Promise<void> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		notificationStore.error("Cannot cancel AI task: Not connected to server.");
		return;
	}
	if (!taskId) return;
	const payload: CancelAITaskPayload = { task_id: taskId };
	// Include chat_id if available so server can clear active task marker immediately
	if (chatId) {
		payload.chat_id = chatId;
	}
	try {
		await webSocketService.sendMessage("cancel_ai_task", payload);
	} catch {
		notificationStore.error("Failed to send AI task cancellation request.");
	}
}

/**
 * Cancel a specific skill execution without stopping the entire AI response.
 * This allows users to skip a long-running skill while the main AI processing continues.
 *
 * @param skillTaskId - Unique ID for the skill invocation (different from main task_id)
 * @param embedId - Optional embed ID for logging purposes
 */
export async function sendCancelSkillImpl(
	serviceInstance: ChatSynchronizationService,
	skillTaskId: string,
	embedId?: string
): Promise<void> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		notificationStore.error("Cannot cancel skill: Not connected to server.");
		return;
	}
	if (!skillTaskId) {
		console.warn(
			"[ChatSyncService:Senders] Cannot cancel skill: No skill_task_id provided"
		);
		return;
	}

	const payload = {
		skill_task_id: skillTaskId,
		embed_id: embedId // Optional, for better logging on backend
	};

	try {
		await webSocketService.sendMessage("cancel_skill", payload);
		console.info(
			`[ChatSyncService:Senders] Sent cancel_skill request for skill_task_id: ${skillTaskId}`
		);
	} catch (error) {
		console.error(
			`[ChatSyncService:Senders] Error sending cancel_skill for skill_task_id: ${skillTaskId}:`,
			error
		);
		notificationStore.error("Failed to send skill cancellation request.");
	}
}

export async function queueOfflineChangeImpl(
	serviceInstance: ChatSynchronizationService,
	change: Omit<OfflineChange, "change_id">
): Promise<void> {
	const fullChange: OfflineChange = {
		...change,
		change_id: crypto.randomUUID()
	};
	await chatDB.addOfflineChange(fullChange);
	notificationStore.info(`Change saved offline. Will sync when reconnected.`, 3000);
}

export async function sendOfflineChangesImpl(): Promise<void> {
	if (get(websocketStatus).status !== "connected") {
		console.warn(
			"[ChatSyncService:Senders] Cannot send offline changes, WebSocket not connected."
		);
		return;
	}
	const changes = await chatDB.getOfflineChanges();
	if (changes.length === 0) return;
	notificationStore.info(
		`Attempting to sync ${changes.length} offline change(s)...`
	);
	const payload: SyncOfflineChangesPayload = { changes };
	await webSocketService.sendMessage("sync_offline_changes", payload);
}

// Scroll position and read status sync methods
export async function sendScrollPositionUpdateImpl(
	serviceInstance: ChatSynchronizationService,
	chat_id: string,
	message_id: string
): Promise<void> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		console.warn(
			"[ChatSyncService:Senders] Cannot send scroll position update - WebSocket not connected"
		);
		return;
	}

	try {
		const payload = {
			chat_id,
			message_id
		};

		console.debug(
			"[ChatSyncService:Senders] Sending scroll position update:",
			payload
		);
		await webSocketService.sendMessage("scroll_position_update", payload);
	} catch (error) {
		console.error(
			"[ChatSyncService:Senders] Error sending scroll position update:",
			error
		);
	}
}

export async function sendChatReadStatusImpl(
	serviceInstance: ChatSynchronizationService,
	chat_id: string,
	unread_count: number
): Promise<void> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		console.warn(
			"[ChatSyncService:Senders] Cannot send chat read status - WebSocket not connected"
		);
		return;
	}

	try {
		const payload = {
			chat_id,
			unread_count
		};

		console.debug(
			"[ChatSyncService:Senders] Sending chat read status update:",
			payload
		);
		await webSocketService.sendMessage("chat_read_status_update", payload);
	} catch (error) {
		console.error(
			"[ChatSyncService:Senders] Error sending chat read status update:",
			error
		);
	}
}

/**
 * Send encrypted post-processing metadata (suggestions, summary, tags) to server for Directus sync
 * Called after client encrypts plaintext suggestions received from post-processing
 */
export async function sendPostProcessingMetadataImpl(
	serviceInstance: ChatSynchronizationService,
	chat_id: string,
	encrypted_follow_up_suggestions: string,
	encrypted_new_chat_suggestions: string[],
	encrypted_chat_summary: string,
	encrypted_chat_tags: string,
	encrypted_top_recommended_apps: string = "",
	encrypted_updated_title: string = "",
	encrypted_chat_key: string = ""
): Promise<void> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		console.warn(
			"[ChatSyncService:Senders] Cannot send post-processing metadata - WebSocket not connected"
		);
		return;
	}

	try {
		interface PostProcessingPayload {
			chat_id: string;
			encrypted_follow_up_suggestions?: string;
			encrypted_new_chat_suggestions?: string[];
			encrypted_chat_summary?: string;
			encrypted_chat_tags?: string;
			encrypted_top_recommended_apps_for_chat?: string;
			encrypted_title?: string; // OPE-265: Updated title from post-processing
			encrypted_chat_key?: string; // OPE-314: Include for server-side key validation
			title_v?: number;
		}

		// Build payload with all the encrypted post-processing metadata
		const payload: PostProcessingPayload = {
			chat_id,
			encrypted_follow_up_suggestions,
			encrypted_new_chat_suggestions,
			encrypted_chat_summary,
			encrypted_chat_tags
		};

		// Only include top recommended apps if provided
		if (encrypted_top_recommended_apps) {
			payload.encrypted_top_recommended_apps_for_chat =
				encrypted_top_recommended_apps;
		}

		// OPE-265: Include updated title from post-processing if the conversation drifted
		if (encrypted_updated_title) {
			payload.encrypted_title = encrypted_updated_title;
		}

		// OPE-314: Include encrypted_chat_key so server can validate metadata was
		// encrypted with the correct key. Without this, the immutability guard is
		// bypassed and metadata encrypted with a stale/wrong key gets persisted.
		if (encrypted_chat_key) {
			payload.encrypted_chat_key = encrypted_chat_key;
		}


		console.debug(
			"[ChatSyncService:Senders] Sending encrypted post-processing metadata for sync to Directus"
		);
		await webSocketService.sendMessage("update_post_processing_metadata", payload);
	} catch (error) {
		console.error(
			"[ChatSyncService:Senders] Error sending post-processing metadata:",
			error
		);
		throw error; // Don't swallow errors
	}
}

/**
 * Send delete new chat suggestion request to server
 * This removes the suggestion from Directus
 */
export async function sendDeleteNewChatSuggestionImpl(
	serviceInstance: ChatSynchronizationService,
	encryptedSuggestion: string
): Promise<void> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		console.warn(
			"[ChatSyncService:Senders] Cannot send delete_new_chat_suggestion - WebSocket not connected"
		);
		return;
	}

	// Final validation: reject empty strings (default suggestions cannot be deleted)
	if (!encryptedSuggestion || encryptedSuggestion.trim() === "") {
		console.error(
			"[ChatSyncService:Senders] CRITICAL: Attempted to send empty encrypted_suggestion - rejecting request"
		);
		throw new Error(
			"Cannot delete default suggestion: encrypted_suggestion is empty"
		);
	}

	try {
		console.debug(
			"[ChatSyncService:Senders] Sending delete new chat suggestion request to server"
		);
		await webSocketService.sendMessage("delete_new_chat_suggestion", {
			encrypted_suggestion: encryptedSuggestion
		});
		console.info(
			"[ChatSyncService:Senders] Successfully sent delete suggestion request to server"
		);
	} catch (error) {
		console.error(
			"[ChatSyncService:Senders] Error sending delete_new_chat_suggestion:",
			error
		);
		throw error;
	}
}

export async function sendDeleteNewChatSuggestionByIdImpl(
	serviceInstance: ChatSynchronizationService,
	suggestionId: string
): Promise<void> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		console.warn(
			"[ChatSyncService:Senders] Cannot send delete_new_chat_suggestion - WebSocket not connected"
		);
		return;
	}

	// Final validation: reject empty strings (default suggestions cannot be deleted)
	if (!suggestionId || suggestionId.trim() === "") {
		console.error(
			"[ChatSyncService:Senders] CRITICAL: Attempted to send empty suggestion_id - rejecting request"
		);
		throw new Error("Cannot delete suggestion: suggestion_id is empty");
	}

	try {
		console.debug(
			"[ChatSyncService:Senders] Sending delete new chat suggestion by ID request to server"
		);
		await webSocketService.sendMessage("delete_new_chat_suggestion", {
			suggestion_id: suggestionId
		});
		console.info(
			"[ChatSyncService:Senders] Successfully sent delete suggestion by ID request to server"
		);
	} catch (error) {
		console.error(
			"[ChatSyncService:Senders] Error sending delete_new_chat_suggestion by ID:",
			error
		);
		throw error;
	}
}

/**
 * Request additional older chats from the server beyond the initial 100.
 * Used by the "Show more" button for on-demand pagination.
 * Chats returned are metadata-only (no messages) and stored in memory only.
 */
export async function sendLoadMoreChatsImpl(
	serviceInstance: ChatSynchronizationService,
	offset: number,
	limit: number = 20
): Promise<void> {
	try {
		await webSocketService.sendMessage("load_more_chats", {
			offset,
			limit
		});
		console.info(
			`[ChatSyncService:Senders] Requested more chats: offset=${offset}, limit=${limit}`
		);
	} catch (error) {
		console.error(
			"[ChatSyncService:Senders] Error requesting more chats:",
			error
		);
	}
}

// ─── Metadata-only chats sync (positions 101–1000) ──────────────────────────

/**
 * Request metadata-only chat records for positions 101–1000 from the server.
 * Called automatically after Phase 3 completes when total_chat_count > 100.
 * These chats are stored in IndexedDB (metadata only, no messages) to enable
 * expanded sidebar display and search across up to 1000 chats.
 *
 * @param existingChatIds - Chat IDs already in IndexedDB (skipped by server to save bandwidth)
 */
export async function sendSyncMetadataChatsImpl(
	serviceInstance: ChatSynchronizationService,
	existingChatIds: string[] = []
): Promise<void> {
	try {
		await webSocketService.sendMessage("sync_metadata_chats", {
			existing_chat_ids: existingChatIds
		});
		console.info(
			`[ChatSyncService:Senders] Requested metadata chats sync (existing_on_client=${existingChatIds.length})`
		);
	} catch (error) {
		console.error(
			"[ChatSyncService:Senders] Error requesting metadata chats sync:",
			error
		);
	}
}

// ─── Inspiration chat sync ─────────────────────────────────────────────────

/**
 * Sync an inspiration-created chat to the server and other devices.
 *
 * When a user clicks a daily inspiration banner, a chat is created locally
 * with a pre-built assistant message. This function sends the encrypted chat
 * metadata and first message to the server so that:
 *   1. The chat appears in the phased sync for other devices.
 *   2. The server's sync cache is populated (so "Continue where you left off"
 *      works cross-device).
 *   3. Other connected devices receive a broadcast to show the new chat.
 *
 * The server handler broadcasts a `new_chat_message` event to all other devices
 * of the same user (same shape as normal cross-device chat sync).
 */
/**
 * Embed data to include in the sync_inspiration_chat payload so other devices
 * can store and decrypt the inspiration video embed immediately without waiting
 * for a Directus round-trip via request_embed.
 */
export interface InspirationEmbedData {
	embed_id: string;
	/** Client-encrypted embed content (TOON-encoded video metadata) */
	encrypted_content: string;
	/** Client-encrypted embed type (e.g. "video") */
	encrypted_type: string;
	/** Client-encrypted text preview (e.g. video title) */
	encrypted_text_preview: string;
	/** Embed key wrappers (master + chat) for decryption on other devices */
	embed_keys: Array<{
		hashed_embed_id: string;
		key_type: "master" | "chat";
		hashed_chat_id: string | null;
		encrypted_embed_key: string;
		hashed_user_id: string;
		created_at: number;
	}>;
}

export async function sendSyncInspirationChatImpl(
	serviceInstance: ChatSynchronizationService,
	chatId: string,
	messageId: string,
	messageContent: string,
	category: string,
	encryptedTitle: string,
	encryptedCategory: string,
	encryptedContent: string,
	encryptedChatKey: string,
	createdAt: number,
	encryptedFollowUpSuggestions?: string,
	inspirationEmbed?: InspirationEmbedData
): Promise<void> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		console.warn(
			"[ChatSyncService:Senders] WebSocket not connected — cannot sync inspiration chat."
		);
		return;
	}

	try {
		const payload: Record<string, unknown> = {
			chat_id: chatId,
			message_id: messageId,
			content: messageContent,
			role: "assistant",
			category,
			created_at: createdAt,
			messages_v: 1,
			title_v: 1,
			encrypted_title: encryptedTitle,
			encrypted_category: encryptedCategory,
			encrypted_content: encryptedContent,
			encrypted_chat_key: encryptedChatKey
		};

		// Include encrypted follow-up suggestions if available so the backend
		// can persist them to Directus (zero-knowledge — server never decrypts).
		if (encryptedFollowUpSuggestions) {
			payload.encrypted_follow_up_suggestions = encryptedFollowUpSuggestions;
		}

		// Include the inspiration video embed data (encrypted content + key wrappers)
		// so other devices can store and decrypt the embed immediately when they
		// receive the new_chat_message broadcast. Without this, the second device
		// must wait for the store_embed and store_embed_keys WS calls to reach
		// Directus before request_embed can return the data — a race that often
		// fails when the user switches devices quickly after opening an inspiration.
		if (inspirationEmbed) {
			payload.inspiration_embed = {
				embed_id: inspirationEmbed.embed_id,
				encrypted_content: inspirationEmbed.encrypted_content,
				encrypted_type: inspirationEmbed.encrypted_type,
				encrypted_text_preview: inspirationEmbed.encrypted_text_preview,
				embed_keys: inspirationEmbed.embed_keys
			};
		}

		await webSocketService.sendMessage("sync_inspiration_chat", payload);
		console.info(
			`[ChatSyncService:Senders] Sent sync_inspiration_chat for chat ${chatId}`,
			encryptedFollowUpSuggestions
				? "(with follow-up suggestions)"
				: "(no follow-up suggestions)",
			inspirationEmbed
				? `(with embed ${inspirationEmbed.embed_id})`
				: "(no embed)"
		);
	} catch (error) {
		// Non-fatal — the chat will sync on next phased sync or when user sends a follow-up.
		console.error(
			"[ChatSyncService:Senders] Error sending sync_inspiration_chat:",
			error
		);
	}
}

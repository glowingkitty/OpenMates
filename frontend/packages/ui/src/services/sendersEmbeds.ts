/**
 * sendersEmbeds.ts — Embed storage and retrieval sender operations
 *
 * Contains sender functions for storing encrypted embeds in Directus,
 * requesting embed data from the server, and storing wrapped embed keys.
 * These functions delegate to embedSenders.ts for offline-aware queueing.
 *
 * Split from chatSyncServiceSenders.ts for maintainability (Phase 04, Plan 01).
 * See docs/architecture/ for the embed encryption architecture.
 */
import type { ChatSynchronizationService } from "./chatSyncService";
import { webSocketService } from "./websocketService";
import type { StoreEmbedPayload } from "../types/chat";

/**
 * Send encrypted embed to server for Directus storage
 */
export async function sendStoreEmbedImpl(
	serviceInstance: ChatSynchronizationService,
	payload: StoreEmbedPayload,
	embedKeysPayload?: { keys: Array<Record<string, unknown>> }
): Promise<void> {
	// Delegate to embedSenders.ts which handles offline queueing in IndexedDB
	const { sendStoreEmbedImpl: embedSendersImpl } = await import("./embedSenders");
	return embedSendersImpl(serviceInstance, payload, embedKeysPayload);
}

/**
 * Request embed data from server via WebSocket
 * Server will respond with send_embed_data event containing the embed content
 */
export async function sendRequestEmbed(
	serviceInstance: ChatSynchronizationService,
	embed_id: string
): Promise<void> {
	if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
		console.warn(
			"[ChatSyncService:Senders] Cannot send request_embed - WebSocket not connected"
		);
		return;
	}

	try {
		console.debug(
			`[ChatSyncService:Senders] Requesting embed ${embed_id} from server`
		);
		await webSocketService.sendMessage("request_embed", { embed_id });
	} catch (error) {
		console.error("[ChatSyncService:Senders] Error requesting embed:", error);
		throw error;
	}
}

/**
 * Send wrapped embed keys to server for embed_keys collection storage
 * This enables offline sharing and cross-chat access (wrapped key architecture)
 *
 * Payload structure:
 * {
 *   keys: [
 *     {
 *       hashed_embed_id: string,
 *       key_type: 'master' | 'chat',
 *       hashed_chat_id: string | null,
 *       encrypted_embed_key: string,
 *       hashed_user_id: string,
 *       created_at: number
 *     },
 *     ...
 *   ]
 * }
 */
export async function sendStoreEmbedKeysImpl(
	serviceInstance: ChatSynchronizationService,
	payload: {
		keys: Array<{
			hashed_embed_id: string;
			key_type: "master" | "chat";
			hashed_chat_id: string | null;
			encrypted_embed_key: string;
			hashed_user_id: string;
			created_at: number;
		}>;
	}
): Promise<void> {
	// Delegate to embedSenders.ts which handles offline awareness
	const { sendStoreEmbedKeysImpl: embedSendersKeysImpl } =
		await import("./embedSenders");
	return embedSendersKeysImpl(serviceInstance, payload);
}

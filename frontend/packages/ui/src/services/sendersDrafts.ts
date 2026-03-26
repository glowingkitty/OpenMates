/**
 * sendersDrafts.ts — Draft management sender operations
 *
 * Contains sender functions for creating, updating, and deleting message drafts.
 * Drafts are encrypted client-side before being sent to the server for cross-device
 * sync. Draft deletion handles both online (WebSocket) and offline (queue) paths.
 *
 * Split from chatSyncServiceSenders.ts for maintainability (Phase 04, Plan 01).
 * See docs/architecture/ for the encryption and sync architecture.
 */
import type { ChatSynchronizationService } from "./chatSyncService";
import { chatDB } from "./db";
import { webSocketService } from "./websocketService";
import { notificationStore } from "../stores/notificationStore";
import { get } from "svelte/store";
import { websocketStatus } from "../stores/websocketStatusStore";
import { chatMetadataCache } from "./chatMetadataCache";
import type { OfflineChange, UpdateDraftPayload, DeleteDraftPayload } from "../types/chat";

export async function sendUpdateDraftImpl(
	serviceInstance: ChatSynchronizationService,
	chat_id: string,
	draft_content: string | null,
	draft_preview?: string | null
): Promise<void> {
	// NOTE: draft_content and draft_preview here are ENCRYPTED for secure server transmission
	// Local database saving with encrypted content should have already occurred in draftSave.ts
	const payload: UpdateDraftPayload = {
		chat_id,
		encrypted_draft_md: draft_content,
		encrypted_draft_preview: draft_preview
	};

	// Send encrypted draft to server for synchronization
	await webSocketService.sendMessage("update_draft", payload);

	console.debug(
		`[ChatSyncService:Senders] Sent encrypted draft update to server for chat ${chat_id}`,
		{
			hasDraftContent: !!draft_content,
			hasPreview: !!draft_preview
		}
	);
}

export async function sendDeleteDraftImpl(
	serviceInstance: ChatSynchronizationService,
	chat_id: string
): Promise<void> {
	const payload: DeleteDraftPayload = { chatId: chat_id };
	try {
		const chatBeforeClear = await chatDB.getChat(chat_id);
		const versionBeforeEdit = chatBeforeClear?.draft_v || 0;
		const clearedDraftChat = await chatDB.clearCurrentUserChatDraft(chat_id);
		if (clearedDraftChat) {
			// CRITICAL: Invalidate cache before dispatching event to ensure UI components fetch fresh data
			// This prevents stale draft previews from appearing in the chat list
			chatMetadataCache.invalidateChat(chat_id);
			console.debug("[sendDeleteDraftImpl] Invalidated cache for chat:", chat_id);

			serviceInstance.dispatchEvent(
				new CustomEvent("chatUpdated", {
					detail: { chat_id, type: "draft_deleted", chat: clearedDraftChat }
				})
			);
		}
		if (get(websocketStatus).status === "connected") {
			await webSocketService.sendMessage("delete_draft", payload);
		} else {
			const offlineChange: Omit<OfflineChange, "change_id"> = {
				chat_id: chat_id,
				type: "delete_draft",
				value: null,
				version_before_edit: versionBeforeEdit
			};
			// Access public method for queueing offline changes
			const queueMethod = (
				serviceInstance as ChatSynchronizationService & {
					queueOfflineChange?: (change: OfflineChange) => void;
				}
			).queueOfflineChange;
			if (queueMethod) {
				queueMethod(offlineChange);
			}
		}
	} catch (error) {
		const errorMessage = error instanceof Error ? error.message : String(error);
		notificationStore.error(`Failed to delete draft: ${errorMessage}`);
	}
}

/**
 * Send a request to delete an uploaded file that was removed from a message draft
 * before the message was sent.  This triggers server-side cleanup of:
 *   - The S3 variant files (original, full, preview) from the chatfiles bucket
 *   - The upload_files Directus record (deduplication tracking)
 *   - The user's storage_used_bytes counter (decremented)
 *
 * Called when an image/PDF/recording embed is removed from the draft editor and
 * the file was already fully uploaded to S3 (i.e., cancelUpload() was a no-op
 * because the upload completed before the user deleted it).
 *
 * Fire-and-forget: failures are logged but not thrown so they never block the UI.
 *
 * @param embed_id - The embed UUID returned by POST /v1/upload/file (TipTap node attrs.id)
 * @param chat_id  - The draft chat ID for context/logging (optional)
 */
export async function sendDeleteDraftEmbedImpl(
	_serviceInstance: ChatSynchronizationService,
	embed_id: string,
	chat_id?: string
): Promise<void> {
	try {
		await webSocketService.sendMessage("delete_draft_embed", {
			embed_id,
			chat_id: chat_id ?? null
		});
		console.debug(
			`[ChatSyncService:Senders] Sent delete_draft_embed for embed ${embed_id} (chat ${chat_id ?? "n/a"})`
		);
	} catch (error) {
		// Non-fatal: the weekly billing reconciliation will correct storage counters.
		// Orphaned upload_files records will remain in Directus but won't affect functionality.
		console.error(
			`[ChatSyncService:Senders] Failed to send delete_draft_embed for embed ${embed_id}:`,
			error
		);
	}
}

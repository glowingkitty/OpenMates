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
import { get } from "svelte/store";
import { websocketStatus } from "../stores/websocketStatusStore";
import { activeTeamContext, isActiveTeamContext } from "../stores/teamStore";
import { chatMetadataCache } from "./chatMetadataCache";
import type { OfflineChange, UpdateDraftPayload, DeleteDraftPayload } from "../types/chat";
import { resolveDraftChatContext, isDraftChatContextCurrent, deferTeamDraftSync, deferTeamDraftDelete, clearTeamDraftIntent, cancelTeamDraftPromotion, withSerializedDraftTransport, promoteDeferredTeamDraft } from "./drafts/draftContext";
import type { DraftChatContext } from "./drafts/draftContext";
import { draftEditorUIState } from "./drafts/draftState";

const DRAFT_UPDATE_RECEIPT_TIMEOUT_MS = 10_000;
const DRAFT_DELETE_RECEIPT_TIMEOUT_MS = 10_000;
const DRAFT_RECEIPT_CONNECTION_LOST_ERROR_NAME =
	"DraftReceiptConnectionLostError";

export class DraftReceiptConnectionLostError extends Error {
	constructor(chatId: string, minimumDraftVersion: number, status: string) {
		super(
			`WebSocket became ${status} while waiting for draft update receipt for chat ${chatId} at draft_v >= ${minimumDraftVersion}`
		);
		this.name = DRAFT_RECEIPT_CONNECTION_LOST_ERROR_NAME;
	}
}

export function isDraftReceiptConnectionLostError(error: unknown): boolean {
	return error instanceof Error && error.name === DRAFT_RECEIPT_CONNECTION_LOST_ERROR_NAME;
}

type DraftOfflineQueueService = ChatSynchronizationService & {
	queueOfflineChange?: (change: Omit<OfflineChange, "change_id">) => void | Promise<void>;
	sendOfflineChanges?: () => void | Promise<void>;
};

type DraftUpdateReceiptPayload = {
	chat_id?: string;
	draft_v?: number;
	success?: boolean;
};

type DraftDeleteReceiptPayload = {
	chat_id?: string;
	success?: boolean;
	draft_v?: number;
};

function waitForDraftUpdateReceiptAtVersion(chatId: string, minimumDraftVersion: number): Promise<void> {
	return new Promise((resolve, reject) => {
		let isSettled = false;
		let hasObservedInitialStatus = false;
		let unsubscribeStatus: (() => void) | undefined;

		const cleanup = () => {
			globalThis.clearTimeout(timeout);
			webSocketService.off("draft_update_receipt", handleReceipt);
			unsubscribeStatus?.();
			unsubscribeStatus = undefined;
		};

		const settle = (callback: () => void) => {
			if (isSettled) return;
			isSettled = true;
			cleanup();
			callback();
		};

		const timeout = globalThis.setTimeout(() => {
			settle(() =>
				reject(
					new Error(
						`Timed out waiting for draft update receipt for chat ${chatId} at draft_v >= ${minimumDraftVersion}`
					)
				)
			);
		}, DRAFT_UPDATE_RECEIPT_TIMEOUT_MS);

		const handleReceipt = (payload: DraftUpdateReceiptPayload): void => {
			if (payload.chat_id !== chatId) return;
			if ((payload.draft_v ?? 0) < minimumDraftVersion) return;
			if (payload.success === false) {
				settle(() => reject(new Error(`Draft update receipt reported failure for chat ${chatId}`)));
				return;
			}
			settle(resolve);
		};

		webSocketService.on("draft_update_receipt", handleReceipt);
		unsubscribeStatus = websocketStatus.subscribe((state) => {
			if (!hasObservedInitialStatus) {
				hasObservedInitialStatus = true;
				return;
			}
			if (state.status !== "connected") {
				settle(() =>
					reject(
						new DraftReceiptConnectionLostError(
							chatId,
							minimumDraftVersion,
							state.status
						)
					)
				);
			}
		});
	});
}

async function queueInterruptedDraftUpdate(
	serviceInstance: ChatSynchronizationService,
	chat_id: string,
	draft_content: string | null,
	expectedDraftVersion: number,
	teamId: string | null,
	error: unknown
): Promise<void> {
	console.warn(
		`[ChatSyncService:Senders] WebSocket connection changed before draft update receipt for chat ${chat_id}. Queuing encrypted draft update:`,
		error
	);
	const offlineChange: Omit<OfflineChange, "change_id"> = {
		chat_id,
		...(teamId ? { team_id: teamId } : {}),
		type: "draft",
		value: draft_content,
		version_before_edit: Math.max(0, expectedDraftVersion - 1)
	};
	const queueService = serviceInstance as DraftOfflineQueueService;
	if (queueService.queueOfflineChange) {
		await queueService.queueOfflineChange(offlineChange);
	} else {
		await chatDB.addOfflineChange({
			...offlineChange,
			change_id: crypto.randomUUID()
		});
	}

	if (get(websocketStatus).status === "connected") {
		void Promise.resolve(queueService.sendOfflineChanges?.()).catch((flushError: unknown) => {
			console.warn(
				`[ChatSyncService:Senders] Deferred offline draft flush failed for chat ${chat_id}:`,
				flushError
			);
		});
	}
}

function waitForDraftDeleteReceipt(chatId: string): Promise<number | undefined> {
	return new Promise((resolve, reject) => {
		const timeout = window.setTimeout(() => {
			webSocketService.off("draft_delete_receipt", handleReceipt);
			reject(new Error(`Timed out waiting for draft delete receipt for chat ${chatId}`));
		}, DRAFT_DELETE_RECEIPT_TIMEOUT_MS);

		const handleReceipt = (payload: DraftDeleteReceiptPayload): void => {
			if (payload.chat_id !== chatId) return;
			window.clearTimeout(timeout);
			webSocketService.off("draft_delete_receipt", handleReceipt);
			if (payload.success === false) {
				reject(new Error(`Draft delete receipt reported failure for chat ${chatId}`));
				return;
			}
			resolve(payload.draft_v);
		};

		webSocketService.on("draft_delete_receipt", handleReceipt);
	});
}

export async function sendUpdateDraftImpl(
	serviceInstance: ChatSynchronizationService,
	chat_id: string,
	draft_content: string | null,
	draft_preview?: string | null,
	expectedDraftVersion = 0,
	expectedContext?: DraftChatContext,
): Promise<void> {
	// NOTE: draft_content and draft_preview here are ENCRYPTED for secure server transmission
	// Local database saving with encrypted content should have already occurred in draftSave.ts
	const context = await resolveDraftChatContext(chat_id);
	if (expectedContext && (context.teamId !== expectedContext.teamId ||
		context.epoch !== expectedContext.epoch)) throw new Error("Draft workspace changed");
	// A Team draft stays local until its first message commits the Team chat.
	if (context.teamId && !context.committed) {
		const chat = await deferTeamDraftSync(chat_id, context);
		if (chat && !chat.team_chat_pending_commit && (chat.messages_v ?? 0) > 0) {
			void promoteDeferredTeamDraft(serviceInstance, chat_id);
		}
		return;
	}
	const sendCommittedUpdate = async (): Promise<void> => {
	// A delayed older sender must not overwrite a newer local Team draft after
	// it finally reaches the transport queue.
	if (context.teamId && expectedDraftVersion > 0) {
		const latest = await chatDB.getRawChat(chat_id);
		if (!isDraftChatContextCurrent(context) || latest?.team_id !== context.teamId) {
			throw new Error("Draft workspace changed");
		}
		if ((expectedContext && latest.team_draft_pending_sync !== "update") ||
			(latest.draft_v ?? 0) !== expectedDraftVersion ||
			latest.encrypted_draft_md !== draft_content) return;
	}
	const payload: UpdateDraftPayload = {
		chat_id,
		...(context.teamId ? { team_id: context.teamId } : {}),
		encrypted_draft_md: draft_content,
		encrypted_draft_preview: draft_preview,
		draft_v: expectedDraftVersion > 0 ? expectedDraftVersion : undefined
	};

	// Send encrypted draft to server for synchronization
	const receipt = waitForDraftUpdateReceiptAtVersion(chat_id, expectedDraftVersion);
	try {
		if (!isDraftChatContextCurrent(context)) throw new Error("Draft workspace changed");
		await webSocketService.sendMessage("update_draft", payload);
		await receipt;
	} catch (error) {
		receipt.catch(() => undefined);
		if (isDraftReceiptConnectionLostError(error) && isDraftChatContextCurrent(context)) {
			await queueInterruptedDraftUpdate(
				serviceInstance,
				chat_id,
				draft_content,
				expectedDraftVersion,
				context.teamId,
				error
			);
			return;
		}
		throw error;
	}

	console.debug(
		`[ChatSyncService:Senders] Sent encrypted draft update to server for chat ${chat_id}`,
		{
			hasDraftContent: !!draft_content,
			hasPreview: !!draft_preview
		}
	);
	if (context.teamId && draft_content && expectedDraftVersion > 0) {
		const sentDraft = { cipher: draft_content, version: expectedDraftVersion };
		await clearTeamDraftIntent(chat_id, context, "update", sentDraft);
		await clearTeamDraftIntent(chat_id, context, "delete", sentDraft);
	}
	};
	if (context.teamId) {
		return withSerializedDraftTransport(chat_id, sendCommittedUpdate);
	}
	await sendCommittedUpdate();
}

/** Called only with the per-chat transport held by deferred promotion. */
async function sendDeferredTeamDraftDeleteWithinTransport(
	chatId: string,
	expectedContext: DraftChatContext,
): Promise<void> {
	if (!expectedContext.teamId || !isDraftChatContextCurrent(expectedContext)) return;
	const context = await resolveDraftChatContext(chatId);
	if (!context.committed || context.teamId !== expectedContext.teamId ||
		context.epoch !== expectedContext.epoch) return;
	const chat = await chatDB.getRawChat(chatId);
	const editor = get(draftEditorUIState);
	if (!isDraftChatContextCurrent(context) || chat?.team_id !== context.teamId ||
		chat.team_draft_pending_sync !== "delete" || chat.encrypted_draft_md ||
		chat.encrypted_draft_preview || (chat.draft_v ?? 0) !== 0 ||
		(editor.currentChatId === chatId && editor.hasUnsavedChanges)) return;
	const receipt = waitForDraftDeleteReceipt(chatId);
	try {
		if (!isDraftChatContextCurrent(context)) throw new Error("Draft workspace changed");
		await webSocketService.sendMessage("delete_draft", {
			chatId, team_id: context.teamId,
		} satisfies DeleteDraftPayload);
		const deletedDraftV = await receipt;
		await clearTeamDraftIntent(chatId, context, "delete",
			{ cipher: null, version: 0 }, deletedDraftV);
	} catch (error) {
		receipt.catch(() => undefined);
		throw error;
	}
}

export async function sendDeleteDraftImpl(
	serviceInstance: ChatSynchronizationService,
	chat_id: string,
	expectedDeferredContext?: DraftChatContext,
): Promise<void> {
	// Cancel a promotion before the first asynchronous scope/database lookup.
	if (!expectedDeferredContext) cancelTeamDraftPromotion(chat_id);
	const requestedContext = get(activeTeamContext);
	return withSerializedDraftTransport(chat_id, async () => {
		if (!isActiveTeamContext(requestedContext.teamId, requestedContext.epoch)) return;
		if (expectedDeferredContext) {
			if (requestedContext.teamId !== expectedDeferredContext.teamId ||
				requestedContext.epoch !== expectedDeferredContext.epoch) return;
			await sendDeferredTeamDraftDeleteWithinTransport(chat_id, expectedDeferredContext);
			return;
		}
		await sendDeleteDraftUnlocked(serviceInstance, chat_id);
	});
}

async function sendDeleteDraftUnlocked(
	serviceInstance: ChatSynchronizationService,
	chat_id: string
): Promise<void> {
	let offlineQueueFailed = false;
	try {
		const context = await resolveDraftChatContext(chat_id);
		const payload: DeleteDraftPayload = {
			chatId: chat_id,
			...(context.teamId ? { team_id: context.teamId } : {})
		};
		const chatBeforeClear = await chatDB.getChat(chat_id);
		if (!isDraftChatContextCurrent(context)) return;
		const versionBeforeEdit = chatBeforeClear?.draft_v || 0;
		const connected = get(websocketStatus).status === "connected";
		if (!connected && (!context.teamId || context.committed)) {
			const offlineChange: Omit<OfflineChange, "change_id"> = {
				chat_id,
				...(context.teamId ? { team_id: context.teamId } : {}),
				type: "delete_draft",
				value: null,
				version_before_edit: versionBeforeEdit
			};
			const queueMethod = (serviceInstance as DraftOfflineQueueService).queueOfflineChange;
			try {
				if (queueMethod) await queueMethod.call(serviceInstance, offlineChange);
				else await chatDB.addOfflineChange({ ...offlineChange, change_id: crypto.randomUUID() });
			} catch (error) {
				offlineQueueFailed = true;
				throw error;
			}
		}
		if (!isDraftChatContextCurrent(context)) return;
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
		if (!isDraftChatContextCurrent(context)) return;
		if (context.teamId && !context.committed) {
			const chat = await deferTeamDraftDelete(chat_id, context);
			if (chat && !chat.team_chat_pending_commit && (chat.messages_v ?? 0) > 0) {
				void promoteDeferredTeamDraft(serviceInstance, chat_id);
			}
			return;
		}
		if (connected) {
			const receipt = waitForDraftDeleteReceipt(chat_id);
			try {
				if (!isDraftChatContextCurrent(context)) throw new Error("Draft workspace changed");
				await webSocketService.sendMessage("delete_draft", payload);
				const deletedDraftV = await receipt;
				if (deletedDraftV !== undefined && isDraftChatContextCurrent(context)) {
					const clearedChat = await chatDB.getRawChat(chat_id);
					if (clearedChat && !clearedChat.encrypted_draft_md && !clearedChat.encrypted_draft_preview) {
						clearedChat.cleared_draft_v = Math.max(
							clearedChat.cleared_draft_v ?? 0,
							deletedDraftV
						);
						await chatDB.upsertRawChat(clearedChat);
					}
				}
				await clearTeamDraftIntent(chat_id, context, "delete");
			} catch (error) {
				receipt.catch(() => undefined);
				throw error;
			}
		}
		if (!connected) await clearTeamDraftIntent(chat_id, context, "delete");
	} catch (error) {
		console.warn(`[ChatSyncService:Senders] Failed to delete draft for chat ${chat_id}:`, error);
		if (offlineQueueFailed) throw error;
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

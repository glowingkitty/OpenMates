/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) chat-sync decisions: the page adapter over
 * the shared Rust core Worker `sync` unit. Loaded only by the guarded branches
 * of chatSyncMerge.ts, chatSyncPhasedRetry.ts, chatSyncMessageKeyGuard.ts and
 * chatSyncServiceHandlersPhasedSync.ts, so default builds never bundle it.
 *
 * Rust (packages/openmates-rust/src/web_sync) decides: the server/local chat
 * merge and key-mismatch plan, the phased-sync retry step, synced-chat key
 * admission, metadata-only records, the authoritative-deletion plan and which
 * synced messages need an authenticated chat key. The page keeps IO only:
 * IndexedDB, chat-key unwrapping/decryption, timers, stores and events. Public
 * functions keep the TypeScript signatures; there is no TypeScript fallback.
 */
import type { Chat, Message } from '../../../types/chat';
import type { ChatSynchronizationService } from '../../chatSyncService';
import { chatKeysEqual } from '../../chatKeyConsistency';
import { decryptChatKeyWithMasterKey } from '../../encryption/MetadataEncryptor';
import { syncCall } from './syncUnitClient';
import type { SyncKeyMismatchPlan } from './syncProtocol';

type JsonRecord = Record<string, unknown>;
type ServerChat = Partial<Chat> & { id: string };

/** Key order of `mergeServerChatWithLocal`'s new-chat literal. */
export const NEW_CHAT_KEYS = [
	'chat_id', 'team_id', 'chat_visibility', 'participant_user_hashes', 'encrypted_title', 'messages_v',
	'message_window_has_more_before', 'message_window_start_cursor', 'embed_window_has_more_before', 'embed_window_start_cursor',
	'title_v', 'metadata_v', 'draft_v', 'unread_count', 'created_at', 'updated_at', 'last_edited_overall_timestamp',
	'encrypted_draft_md', 'encrypted_draft_preview', 'ideabucket', 'ideabucket_processing_window_id', 'ideabucket_triggered_at',
	'encrypted_chat_key', 'anonymous_encrypted_chat_key', 'candidate_encrypted_keys', 'encrypted_icon', 'encrypted_category',
	'last_visible_message_id', 'pinned', 'encrypted_follow_up_request_suggestions', 'encrypted_suggested_followup_message',
	'encrypted_chat_summary', 'encrypted_share_cta_text', 'encrypted_shared_short_url', 'encrypted_chat_tags',
	'encrypted_top_recommended_apps_for_chat', 'encrypted_recommendations', 'encrypted_active_focus_id',
	'encrypted_focus_phase_state', 'encrypted_auto_speak_response', 'is_shared', 'is_private', 'is_anonymous', 'share_pii',
	'share_highlights', 'parent_id', 'is_sub_chat', 'budget_limit', 'budget_spent', 'user_id',
] as const;

/** Key order of `mergeServerChatWithLocal`'s merged literal. */
export const MERGED_CHAT_KEYS = [
	'chat_id', 'team_id', 'chat_visibility', 'participant_user_hashes', 'team_chat_pending_commit', 'team_draft_pending_sync',
	'user_id', 'encrypted_title', 'messages_v', 'message_window_has_more_before', 'message_window_start_cursor',
	'embed_window_has_more_before', 'embed_window_start_cursor', 'title_v', 'metadata_v', 'draft_v', 'cleared_draft_v',
	'unread_count', 'created_at', 'updated_at', 'last_edited_overall_timestamp', 'encrypted_draft_md', 'encrypted_draft_preview',
	'ideabucket', 'ideabucket_processing_window_id', 'ideabucket_triggered_at', 'encrypted_chat_key',
	'anonymous_encrypted_chat_key', 'candidate_encrypted_keys', 'encrypted_icon', 'encrypted_category', 'last_visible_message_id',
	'pinned', 'encrypted_follow_up_request_suggestions', 'encrypted_suggested_followup_message', 'encrypted_chat_summary',
	'encrypted_share_cta_text', 'encrypted_shared_short_url', 'encrypted_chat_tags', 'encrypted_top_recommended_apps_for_chat',
	'encrypted_recommendations', 'encrypted_focus_phase_state', 'encrypted_active_focus_id', 'encrypted_auto_speak_response',
	'is_shared', 'is_private', 'is_anonymous', 'share_pii', 'share_highlights', 'parent_id', 'is_sub_chat', 'budget_limit',
	'budget_spent',
] as const;

/** Key order of `buildMetadataOnlyChatFromDetails`. */
export const METADATA_CHAT_KEYS = [
	'chat_id', 'encrypted_title', 'title', 'messages_v', 'title_v', 'metadata_v', 'draft_v', 'encrypted_draft_md',
	'encrypted_draft_preview', 'ideabucket', 'ideabucket_processing_window_id', 'ideabucket_triggered_at',
	'last_edited_overall_timestamp', 'unread_count', 'created_at', 'updated_at', 'processing_metadata', 'waiting_for_metadata',
	'encrypted_category', 'encrypted_icon', 'encrypted_chat_key', 'chat_visibility', 'participant_user_hashes',
	'anonymous_encrypted_chat_key', 'encrypted_chat_summary', 'encrypted_share_cta_text', 'encrypted_chat_tags',
	'encrypted_follow_up_request_suggestions', 'encrypted_suggested_followup_message', 'encrypted_active_focus_id',
	'encrypted_focus_phase_state', 'encrypted_auto_speak_response', 'pinned', 'is_shared', 'is_private', 'is_anonymous',
	'share_pii', 'share_highlights', 'is_metadata_only',
] as const;

/** Rebuilds the TS object shape: Rust omits `undefined` members, the literal declares every key. */
export function restoreChatShape(keys: readonly string[], json: JsonRecord): Chat {
	const chat: JsonRecord = {};
	for (const key of keys) chat[key] = json[key];
	return chat as unknown as Chat;
}

const record = (value: object | null): JsonRecord | null => value as JsonRecord | null;
const obj = (value: object): JsonRecord => value as JsonRecord;

/** Page IO of a `direct`/`master` plan: unwrap both wrappers and compare the raw keys. */
async function settleKeyMismatch(plan: SyncKeyMismatchPlan, server: ServerChat, local: Chat): Promise<boolean> {
	if (plan.kind === 'decided') return plan.mismatch;
	const serverKey = server.encrypted_chat_key as string;
	const localKey = local.encrypted_chat_key as string;
	if (plan.kind === 'direct') {
		try {
			const { unwrapDirectTeamChatKey } = await import('../../directChatService');
			const [serverRaw, localRaw] = await Promise.all([
				unwrapDirectTeamChatKey(server.team_id as string, server.id, serverKey),
				unwrapDirectTeamChatKey(local.team_id as string, local.chat_id, localKey),
			]);
			return !chatKeysEqual(serverRaw, localRaw);
		} catch {
			// Same contract as the TS reader: an unwrappable Team wrapper is a mismatch.
			return true;
		}
	}
	const [serverRaw, localRaw] = await Promise.all([decryptChatKeyWithMasterKey(serverKey), decryptChatKeyWithMasterKey(localKey)]);
	if (!serverRaw || !localRaw) return true;
	return !chatKeysEqual(serverRaw, localRaw);
}

export async function hasEncryptedChatKeyMismatch(server: ServerChat, local: Chat | null): Promise<boolean> {
	const plan = await syncCall('keyMismatch', { server: obj(server), local: record(local) });
	if (plan.kind === 'decided') return plan.mismatch;
	return settleKeyMismatch(plan, server, local as Chat);
}

export async function mergeServerChatWithLocal(server: ServerChat, local: Chat | null, currentUserId?: string): Promise<Chat> {
	const input = {
		server: obj(server),
		serverUndefined: Object.keys(server).filter((key) => obj(server)[key] === undefined),
		local: record(local),
		keyMismatch: null as boolean | null,
		now: Math.floor(Date.now() / 1000),
		...(currentUserId === undefined ? {} : { currentUserId }),
	};
	let outcome = await syncCall('merge', input);
	if (outcome.kind === 'compareKeys') {
		input.keyMismatch = await settleKeyMismatch(outcome.plan, server, local as Chat);
		outcome = await syncCall('merge', input);
	}
	if (outcome.kind !== 'merged') throw new Error('sync_merge_unsettled');
	return restoreChatShape(local ? MERGED_CHAT_KEYS : NEW_CHAT_KEYS, outcome.chat);
}

// ── Phased-sync retry ──────────────────────────────────────────────────────

/** Module state owned by chatSyncPhasedRetry.ts. */
export interface PhasedRetryState {
	attempt: number;
	timer: ReturnType<typeof setTimeout> | null;
	/** Bumped by every reset; a decision from an older generation is dropped. */
	readonly generation: number;
}

export interface PhasedRetryEffects {
	markSyncCompleted(): void;
	notifyDegraded(): void;
}

let retryChain: Promise<void> = Promise.resolve();

export function handlePhasedSyncRetryableError(
	service: ChatSynchronizationService,
	payload: { retryable?: boolean; retry_after_ms?: number },
	state: PhasedRetryState,
	effects: PhasedRetryEffects,
): Promise<void> {
	retryChain = retryChain.then(async () => {
		const generation = state.generation;
		const step = await syncCall('retry', {
			...('retryable' in payload ? { retryable: payload.retryable } : {}),
			timerPending: state.timer !== null,
			attempt: state.attempt,
			...('retry_after_ms' in payload ? { retryAfterMs: payload.retry_after_ms } : {}),
		});
		if (step.kind === 'ignore' || generation !== state.generation) return;
		service.clearPhasedSyncTimeout();
		if (step.kind === 'pending') return;
		if (step.kind === 'exhausted') {
			console.warn('[ChatSyncService] Phased sync retry budget exhausted; keeping cached chats');
			state.attempt = 0;
			if (state.timer) clearTimeout(state.timer);
			state.timer = null;
			effects.markSyncCompleted();
			service.dispatchEvent(new CustomEvent('phasedSyncComplete', {
				detail: { status: 'completed_via_error', synthetic: true, reason: 'error' },
			}));
			effects.notifyDegraded();
			return;
		}
		state.attempt = step.attempt;
		console.info(
			`[ChatSyncService] Phased sync dependency unavailable; retry ${step.attempt}/${step.maxAttempts} in ${step.delayMs}ms`,
		);
		state.timer = setTimeout(() => {
			state.timer = null;
			if (!service.webSocketConnected_FOR_SENDERS_ONLY) return;
			void service.startPhasedSync();
		}, step.delayMs);
	});
	return retryChain;
}

// ── Synced-chat key admission, metadata-only chats, deletions ──────────────

export async function shouldSkipSyncedChatWithoutKey(phase: string, chatId: string, server: Partial<Chat>, local: Chat | null): Promise<boolean> {
	const { skip } = await syncCall('admission', { chatId, server: obj(server), local: record(local) });
	if (skip) console.warn(`[ChatSyncService] ${phase} - skipping ${chatId}: missing encrypted_chat_key`);
	return skip;
}

/** Admission plus `buildMetadataOnlyChatFromDetails`; `null` when the chat has no usable key. */
export async function metadataOnlyChat(phase: string, details: ServerChat, existing: Chat | null): Promise<Chat | null> {
	const outcome = await syncCall('metadataChat', {
		chatId: details.id, server: obj(details), local: record(existing), now: Math.floor(Date.now() / 1000),
	});
	if (outcome.kind === 'skip') {
		console.warn(`[ChatSyncService] ${phase} - skipping ${details.id}: missing encrypted_chat_key`);
		return null;
	}
	return restoreChatShape(METADATA_CHAT_KEYS, outcome.chat);
}

export async function applyAuthoritativeDeletedChats(
	service: ChatSynchronizationService,
	deletedChatIds: string[] | undefined,
	explicitDeletedChatIds: string[] | undefined,
): Promise<void> {
	const plan = await syncCall('deletionPlan', {
		...(deletedChatIds === undefined ? {} : { deleted: deletedChatIds }),
		...(explicitDeletedChatIds === undefined ? {} : { explicit: explicitDeletedChatIds }),
	});
	if (plan.length === 0) return;
	const [{ chatDB }, { chatListCache }] = await Promise.all([import('../../db'), import('../../chatListCache')]);
	for (const { chatId, explicit } of plan) {
		try {
			if (!explicit) {
				// An inferred absence never erases a chat whose turn awaits acknowledgement.
				const result = await chatDB.deleteChatIfNoPendingTurn(chatId);
				if (!result.deleted) continue;
			} else {
				await chatDB.deleteChat(chatId);
			}
			chatListCache.removeChat(chatId);
			service.dispatchEvent(new CustomEvent('chatDeleted', { detail: { chat_id: chatId } }));
			console.info(`[ChatSyncService] Removed locally stale chat ${chatId} from Phase 2 authoritative deletion list`);
		} catch (error) {
			// Per-chat IDB failure: logged and the remaining deletions still apply (TS contract).
			console.error(`[ChatSyncService] Failed to apply Phase 2 authoritative deletion for chat ${chatId}:`, error);
		}
	}
}

// ── Synced-message key admission ───────────────────────────────────────────

const MESSAGE_PROJECTION = [
	'chat_id', 'encrypted_content', 'encrypted_sender_name', 'encrypted_category', 'encrypted_model_name',
	'encrypted_thinking_content', 'encrypted_thinking_signature', 'encrypted_pii_mappings',
] as const;

/** Resolves the chat key in the TS source order and authenticates the Rust-chosen sample. */
async function sampleDecrypts(chatId: string, sample: string, encryptedChatKey: string | null | undefined): Promise<boolean> {
	const [{ chatKeyManager }, { chatDB }, { decryptWithChatKey }] = await Promise.all([
		import('../../encryption/ChatKeyManager'), import('../../db'), import('../../encryption/MessageEncryptor'),
	]);
	let chatKey: Uint8Array | null = null;
	if (encryptedChatKey) chatKey = await chatKeyManager.receiveKeyFromServer(chatId, encryptedChatKey);
	if (!chatKey) chatKey = chatKeyManager.getKeySync(chatId);
	if (!chatKey) chatKey = await chatKeyManager.getKey(chatId);
	if (!chatKey) {
		const stored = (await chatDB.getChat(chatId))?.encrypted_chat_key;
		if (stored && stored !== encryptedChatKey) chatKey = await chatKeyManager.receiveKeyFromServer(chatId, stored);
	}
	return chatKey !== null && (await decryptWithChatKey(sample, chatKey)) !== null;
}

export async function filterPersistableSyncedMessagesWithSkipped(
	messages: Message[],
	encryptedChatKeysByChatId: Map<string, string | null | undefined>,
	context: string,
): Promise<{ messages: Message[]; skippedChatIds: Set<string> }> {
	const projected = messages.map((message) => {
		const out: JsonRecord = {};
		for (const key of MESSAGE_PROJECTION) out[key] = (message as unknown as JsonRecord)[key];
		return out;
	});
	const plan = await syncCall('messageKeyPlan', { messages: projected });
	const persistable: Message[] = [];
	const skippedChatIds = new Set<string>();
	for (const group of plan) {
		const chatId = group.chatId as string;
		const groupMessages = group.indices.map((index) => messages[index]);
		if (!group.needsKey || (await sampleDecrypts(chatId, group.sample as string, encryptedChatKeysByChatId.get(chatId)))) {
			persistable.push(...groupMessages);
			continue;
		}
		console.warn(
			`[ChatSyncService] ${context}: Skipping ${groupMessages.length} encrypted message(s) for chat ${chatId} because no usable chat key is available.`,
		);
		skippedChatIds.add(chatId);
	}
	return { messages: persistable, skippedChatIds };
}

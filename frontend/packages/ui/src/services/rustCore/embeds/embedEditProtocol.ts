/**
 * `embedEdit` unit protocol of the shared Rust core Worker: user-made embed
 * versions (`feature.embed-user-edits`): content edits of diagrams, slides,
 * sheets and documents, image Enhance, restore of an earlier version, the chat-open reconcile of pending "embed updated" notices and the
 * folding of `embed_updated` chat events. VITE_OPENMATES_RUST_CORE builds only.
 *
 * The Rust core (browser_embed_user_edit.rs, free function
 * `embed_group_updated_events`) does every request, commit, version check,
 * chat event write and grouping. These types only carry its presentation JSON
 * across the unit port; failures arrive as the core's stable codes
 * (`embed_version_conflict`, `insufficient_credits`, `team_enhance_unavailable`,
 * `embed_key_unavailable`, `enhance_failed`, ...).
 */
import type { EmbedUpdatedGroup } from '../../../components/embedUpdatedGroup';

/** Where a user version is saved (core `RevisionScope`). */
export type EmbedEditScope =
	| { kind: 'chat'; chat_id: string; team_id?: string }
	| { kind: 'project'; project_id: string; team_id?: string };

/** Core `EnhanceJob` (no result: the result never leaves the core). */
export interface EnhanceJob {
	operation_id: string;
	embed_id: string;
	state: 'pending' | 'ready' | 'committed' | 'failed' | 'expired';
	base_version: number;
	target_version: number;
	credits: number;
	charged: boolean;
	created_at: number;
	expires_at: number;
	error_code: string | null;
}

/** Core `EventDelivery`. */
export type EmbedEventDelivery =
	| { state: 'written' }
	| { state: 'already_written' }
	| { state: 'no_chat' }
	| { state: 'deferred'; code: string };

/**
 * Core `EventNotice`: the chat row of a written `embed_updated` event. The
 * server broadcasts it to the user's other devices only, so the saving page
 * shows it from here. `content` is the event JSON (no key material).
 */
export interface EmbedEventNotice {
	chat_id: string;
	message_id: string;
	created_at: number;
	content: string;
}

/** The fields of the core `EmbedRevisionOutcome` the page uses (ciphertext stays in the Worker). */
export interface EmbedRevisionResult {
	version: number;
	base_version: number;
	event: EmbedEventDelivery;
	cache_synchronized: boolean;
	/** SHA-256 of the committed head ciphertext (the server's `current_content_hash`). */
	content_hash: string;
	notice?: EmbedEventNotice;
}

/** Core `ImageEnhanceSaved`, reduced to what the page shows. */
export interface ImageEnhanceResult {
	operation_id: string;
	version: number;
	/** Absent for `already_committed` (saved earlier by this or another device). */
	event?: EmbedEventDelivery;
	notice?: EmbedEventNotice;
}

/** Enhance of `embedId` currently running in this Worker (survives a page reload while the Worker lives). */
export interface RunningEnhance {
	operation_id: string | null;
	scope: EmbedEditScope;
}

/** One decrypted chat-history row as `embed_group_updated_events` reads it. */
export interface EmbedEventRow {
	message_id: string;
	role: string;
	content: string;
}

/** Core chat item of `embed_group_updated_events`. */
export type EmbedChatItem = { kind: 'message'; index: number } | ({ kind: 'embed_updated' } & EmbedUpdatedGroup);

/** Core `NoticeReconcileReport`. */
export interface NoticeReconcileReport {
	written: number;
	already_present: number;
	unresolved: string[];
	deferred?: string;
}

export type EmbedEditProtocol = {
	/** Starts (or joins) the Enhance of the head version and resolves when it is saved as the next version. */
	enhanceImage: { request: { embedId: string; scope: EmbedEditScope }; response: ImageEnhanceResult };
	/** The Enhance of `embedId` running in this Worker, or null. */
	runningEnhance: { request: { embedId: string }; response: RunningEnhance | null };
	/** Forwards one WebSocket frame (`image_enhance_ready` / `image_enhance_failed`); true when it woke a run. */
	enhanceFrame: { request: { type: string; payload: unknown }; response: boolean };
	/**
	 * Saves a user content edit (diagram, slides, sheet, document) made on version
	 * `baseVersion` as the next version; `content` is the new head plaintext (TOON).
	 * The core refuses with `embed_version_conflict` when the head moved meanwhile.
	 */
	commitContentRevision: {
		request: { embedId: string; scope: EmbedEditScope; baseVersion: number; content: string };
		response: EmbedRevisionResult;
	};
	/** Restores version `restoredFrom` as the next version of the embed. */
	restoreVersion: { request: { embedId: string; scope: EmbedEditScope; restoredFrom: number }; response: EmbedRevisionResult };
	/** Writes the chat's pending `embed_updated` events (edits made in the Projects workspace or elsewhere). */
	reconcileNotices: { request: { chatId: string }; response: NoticeReconcileReport };
	/** Folds `embed_updated` system events of a chat history into chat items (pure core function). */
	groupUpdatedEvents: { request: { rows: EmbedEventRow[] }; response: EmbedChatItem[] };
};

export const EMBED_EDIT_UNIT_CLOSE = Object.freeze({ v: 1, type: 'embed_edit_close' });
export function isEmbedEditUnitClose(value: unknown): boolean {
	const data = value as { v?: unknown; type?: unknown } | null;
	return data?.v === 1 && data.type === 'embed_edit_close';
}

/**
 * `embedWrite` unit operations for image versions
 * (`images-generate.revision.same-embed-new-version`,
 * `images-generate.revision.message-shows-its-version`; VITE_OPENMATES_RUST_CORE
 * builds only). Contract: docs/plans/image-edit-as-embed-version/wire-contract.md
 * ("Core API for shells").
 *
 * The Rust core (`BrowserEmbedWriter.prepare_child_revision`,
 * `adopt_child_revision_row`, `embed_version_content`, `cache_version_page`,
 * free functions `embed_versions_by_message`, `embed_pinned_embeds`,
 * `embed_head_version`, `embed_synced_head_regresses`) decides every row, hash, key, version and durability
 * marker. These types only carry its results across the unit port; local rows,
 * entries and key wrappers never leave the Worker.
 */
import type { EncryptedDiffRow, StreamCompletionInput } from '../embedWriteAdapter';

/** Rust `BrowserEmbedWriter` exports of browser_embed_revision.rs. */
export interface ChildRevisionWriterPort {
	prepare_child_revision(payloadJson: string, storedHeadJson: string | undefined, existingRowsJson: string): Promise<unknown>;
	adopt_child_revision_row(localRowJson: string, pageJson: string): string;
	embed_version_content(embedId: string, version: number, headJson: string, rowsJson: string): string;
	cache_version_page(embedId: string, headJson: string, pageJson: string): string;
}

/** Free Rust exports of browser_embed_revision.rs (optional until the wasm build carries them). */
export interface ChildRevisionFunctions {
	embed_versions_by_message?(messagesJson: string, embedId: string): string;
	embed_pinned_embeds?(parentContent: string): string;
	embed_head_version?(storedHeadJson: string): number;
	embed_synced_head_regresses?(storedHeadJson: string, incomingJson: string): boolean;
}

/** A row sync or a server read is about to store over `embed:<embedId>` (only the fields the core compares). */
export interface SyncedHeadCandidate {
	embedId: string;
	incoming: { embed_id: string; parent_embed_id?: string | null; version_number?: number | null };
}

/** One step of `child_revision.steps` as the page sees it (the local half stays in the Worker). */
export type ChildRevisionStepKind = { op: 'store_embed_diff'; role: 'base_snapshot' | 'history'; version: number } | { op: 'store_embed' };

/** What `prepareChildRevision` returns: the ordered step kinds, or a replay that needs no write. */
export interface ChildRevisionPlan {
	already_applied: boolean;
	base_version: number | null;
	/** Null for a replay (nothing to write). */
	version_number: number | null;
	steps: ChildRevisionStepKind[];
}

/** One executed step: its local half is stored; the page sends the server payload. */
export type ChildRevisionStepResult =
	| { op: 'store_embed_diff'; version: number; server_payload: Record<string, unknown> }
	| {
		op: 'store_embed';
		store_payload: Record<string, unknown>;
		embed_ref_registration: { embed_ref: string; embed_id: string; app_id: string | null; type: string; skill_id: string | null } | null;
		child_ref_embed_ids: string[];
		content_ref: string;
	};

/** `[{message_id, parent_contents: [toon]}]` in chat order (core `MessageParents`). */
export interface MessageParentsInput {
	message_id: string;
	parent_contents: string[];
}

/** Core `MessageImageVersion`. */
export interface MessageImageVersion {
	message_id: string;
	version: number;
	pinned_here: boolean;
}

/** Core `PinnedEmbed`. */
export interface PinnedEmbed {
	embed_id: string;
	version: number;
	embed_ref?: string;
	previous_version?: number;
}

export type ChildRevisionProtocol = {
	/** `send_embed_data` with `payload.revision`; the Worker reads the stored head and rows itself. */
	prepareChildRevision: { request: { payload: StreamCompletionInput; normalizedType: string }; response: ChildRevisionPlan };
	/** Stores step `index`'s local value (`local_row`, or the pending `local_entry` + wrappers) and returns what the page sends. */
	runChildRevisionStep: { request: { embedId: string; index: number }; response: ChildRevisionStepResult };
	/** After step `index` was sent successfully: stores its `confirmed_row` / `confirmed_entry`. */
	confirmChildRevisionStep: { request: { embedId: string; index: number }; response: null };
	/** After `embed_diff_conflict` on step `index`: stores the canonical row Rust adopts (`page` = bounded-v1 read). */
	adoptChildRevisionRow: { request: { embedId: string; index: number; page: unknown }; response: EncryptedDiffRow };
	/** Drops the prepared revision (always called, also after a failure). */
	endChildRevision: { request: { embedId: string }; response: null };
	/** Plaintext TOON of version `version` from the stored head and rows. */
	embedVersionContent: { request: { embedId: string; version: number }; response: string };
	/** Validates a fetched bounded-v1 page in Rust and stores the rows it returns; resolves their count. */
	cacheVersionPage: { request: { embedId: string; page: unknown }; response: number };
	/** Stored head's version (core `embed_head_version`) and parent; null when no row is stored. */
	embedHeadVersion: { request: { embedId: string }; response: { version: number; parent_embed_id: string | null } | null };
	/** Ids whose stored child head is newer than the incoming row (core `synced_head_regresses`): keep the stored row. */
	embedSyncedHeadsKept: { request: { rows: SyncedHeadCandidate[] }; response: string[] };
	embedVersionsByMessage: { request: { messages: MessageParentsInput[]; embedId: string }; response: MessageImageVersion[] };
	embedPinnedEmbeds: { request: { parentContent: string }; response: PinnedEmbed[] };
};

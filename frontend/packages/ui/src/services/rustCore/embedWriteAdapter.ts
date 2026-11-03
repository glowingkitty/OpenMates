/**
 * Thin web adapter onto the shared Rust embed write engine
 * (`openmates_sdk::client::embed_write`, WASM export `BrowserEmbedWriter`).
 *
 * Rust owns key choice (HKDF parent keys, inherited child keys), every
 * ciphertext, payload/row shapes, revision-history decisions and status rules.
 * This module only sequences platform IO: retries a child whose parent key is
 * still pending (100..1600 ms, as the legacy handler), reads canonical history
 * over HTTP, writes IndexedDB rows and sends WebSocket payloads.
 *
 * Wiring (coordinator, behind VITE_OPENMATES_RUST_CORE, default off):
 *   1. Construct `BrowserEmbedWriter(masterCryptoKey)` in the production worker.
 *   2. On chat key load, `adopt_chat_key(chatId, encrypted_chat_key)`; on embed
 *      key rows, `adopt_embed_key_wrapper(embedId, chatId, JSON row)`.
 *   3. Finalized `send_embed_data`: `prepareStreamCompletion` ->
 *      `persistPreparedEmbedWrite` (embedWriteIdb) -> `sendStoreEmbed(store_payload,
 *      server_keys)` -> register `embed_ref_registration` / child refs ->
 *      `persistStreamedHistory` for `version_history_rows`.
 *   4. processing->finished `embed_update`: `prepare_processing_update`, same IO.
 * Flag off, none of this runs and the legacy TypeScript path is unchanged.
 */

/** Structural view of the WASM `BrowserEmbedWriter`. Never exposes raw keys. */
export interface EmbedWriterPort {
	adopt_chat_key(chatId: string, encryptedChatKey: string): Promise<unknown>;
	adopt_embed_key_wrapper(embedId: string, chatId: string, rowJson: string): Promise<unknown>;
	adopt_child_embed_key(childId: string, parentId: string, wrappedByParent: string): void;
	has_chat_key(chatId: string): boolean;
	has_embed_key(embedId: string): boolean;
	prepare_stream_completion(payloadJson: string): Promise<unknown>;
	prepare_processing_update(
		existingJson: string,
		chatId: string,
		userId: string | undefined,
		messageId: string | undefined,
		normalizedType: string
	): Promise<unknown>;
	encrypt_history_row(embedId: string, rowJson: string, hashedUserId: string): string | undefined;
	reconcile_sealed_history(embedId: string, rowsJson: string, declaredVersion: number, existingRowsJson: string): string;
	adopt_canonical_row(embedId: string, pageJson: string, rowJson: string): string;
	verify_canonical_head(embedId: string, pageJson: string, rowsJson: string): string;
	prepare_restore(
		embedId: string,
		selectedVersion: number,
		currentVersion: number,
		currentContent: string,
		restoredContent: string
	): string;
	reconstruct_versions(embedId: string, rowsJson: string): string;
	forget_chat(chatId: string): void;
	clear(): void;
}

/** Free WASM functions used by the history sequencing below. */
export interface EmbedWriteFunctions {
	embed_classify_canonical_read(status: number, bodyJson: string | undefined, version: number, durableHead: boolean): string;
	embed_history_head_version(rowsJson: string, embedId: string): number | undefined;
}

export interface EmbedKeyWrapperRow {
	hashed_embed_id: string;
	key_type: 'master' | 'chat';
	hashed_chat_id: string | null;
	encrypted_embed_key: string;
	hashed_user_id: string;
	created_at: number;
}

export interface PreparedEmbedWrite {
	local_entry: Record<string, unknown> & { contentRef: string; type: string };
	local_key_wrappers: EmbedKeyWrapperRow[];
	store_payload: Record<string, unknown> | null;
	server_keys: { keys: EmbedKeyWrapperRow[] } | null;
	key_cache_embed_ids: string[];
	embed_ref_registration: {
		embed_ref: string;
		embed_id: string;
		app_id: string | null;
		type: string;
		skill_id: string | null;
	} | null;
	child_ref_embed_ids: string[];
	sealed_history: boolean;
}

export interface EncryptedDiffRow {
	id: string;
	embed_id: string;
	version_number: number;
	encrypted_snapshot?: string;
	encrypted_patch?: string;
	created_at: number;
}

/** Stable rejection codes from the WASM writer (see browser_embed_write.rs). */
export const PARENT_KEY_PENDING = 'embed_parent_key_pending';
const PARENT_KEY_RETRIES = 5;
const PARENT_KEY_BASE_DELAY_MS = 100;

function rejectionCode(error: unknown): string | undefined {
	if (typeof error === 'string') return error;
	if (error instanceof Error) return error.message;
	return undefined;
}

function parsePrepared(value: unknown): PreparedEmbedWrite {
	if (typeof value !== 'string') throw new Error('embed_write_protocol');
	return JSON.parse(value) as PreparedEmbedWrite;
}

export interface StreamCompletionInput extends Record<string, unknown> {
	embed_id: string;
	chat_id: string;
	message_id: string;
	user_id: string;
	type: string;
	content: string;
	team_id?: string | null;
	local_only?: boolean;
}

/**
 * Finalized streamed write. A child arriving before its parent's key is
 * retried with the legacy exponential backoff, then fails loudly.
 */
export async function prepareStreamCompletion(
	port: EmbedWriterPort,
	payload: StreamCompletionInput,
	sleep: (ms: number) => Promise<void> = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
): Promise<PreparedEmbedWrite> {
	const encoded = JSON.stringify(payload);
	for (let attempt = 0; ; attempt++) {
		try {
			return parsePrepared(await port.prepare_stream_completion(encoded));
		} catch (error) {
			if (rejectionCode(error) !== PARENT_KEY_PENDING || attempt >= PARENT_KEY_RETRIES) throw error;
		}
		await sleep(PARENT_KEY_BASE_DELAY_MS * 2 ** attempt);
	}
}

/** processing->finished `embed_update`; `normalizedType` from the registry. */
export async function prepareProcessingUpdate(
	port: EmbedWriterPort,
	existing: Record<string, unknown>,
	chatId: string,
	userId: string | undefined,
	messageId: string | undefined,
	normalizedType: string
): Promise<PreparedEmbedWrite> {
	return parsePrepared(
		await port.prepare_processing_update(JSON.stringify(existing), chatId, userId, messageId, normalizedType)
	);
}

/** Platform IO for revision history; mirrors streamedEmbedRevisionHistory. */
export interface EmbedHistoryIO {
	/** bounded-v1 `/v1/embeds/{id}/versions/{n}` read (status + parsed JSON body). */
	readCanonical(embedId: string, version: number): Promise<{ status: number; body: unknown }>;
	getLocalDiffs(embedId: string): Promise<EncryptedDiffRow[]>;
	storeDiff(row: EncryptedDiffRow): Promise<void>;
	/** `store_embed_diff`; rejects with `code === 'embed_diff_conflict'` on conflict. */
	sendDiff(payload: Record<string, unknown>): Promise<void>;
}

export interface StreamedHistoryOptions {
	embedId: string;
	declaredVersion: number;
	hashedUserId: string;
	sealedRootRevision: boolean;
	durableHead: boolean;
}

interface StreamedRow {
	embed_id?: unknown;
	version_number?: unknown;
}

function isDiffConflict(error: unknown): boolean {
	return error instanceof Error && (error as Error & { code?: string }).code === 'embed_diff_conflict';
}

/** Port of `persistClientEncryptedEmbedDiffRows`; Rust decides, IO executes. */
export async function persistStreamedHistory(
	port: EmbedWriterPort,
	fns: EmbedWriteFunctions,
	io: EmbedHistoryIO,
	rows: unknown[],
	options: StreamedHistoryOptions
): Promise<void> {
	if (!Array.isArray(rows) || rows.length === 0) return;
	const { embedId } = options;
	if (options.sealedRootRevision) {
		const existing = await io.getLocalDiffs(embedId);
		const reconciled = JSON.parse(
			port.reconcile_sealed_history(embedId, JSON.stringify(rows), options.declaredVersion, JSON.stringify(existing))
		) as EncryptedDiffRow[];
		for (const row of reconciled) await io.storeDiff(row);
		if (!options.durableHead) return;
		const head = fns.embed_history_head_version(JSON.stringify(rows), embedId);
		if (head === undefined) return;
		const read = await io.readCanonical(embedId, head);
		if (fns.embed_classify_canonical_read(read.status, undefined, head, true) === 'absent') return;
		const verified = JSON.parse(
			port.verify_canonical_head(embedId, JSON.stringify(read.body), JSON.stringify(rows))
		) as EncryptedDiffRow[];
		for (const row of verified) await io.storeDiff(row);
		return;
	}
	const adopt = async (row: StreamedRow, version: number): Promise<boolean> => {
		const read = await io.readCanonical(embedId, version);
		const body = read.body === undefined ? undefined : JSON.stringify(read.body);
		if (fns.embed_classify_canonical_read(read.status, body, version, false) === 'absent') return false;
		await io.storeDiff(JSON.parse(port.adopt_canonical_row(embedId, JSON.stringify(read.body), JSON.stringify(row))));
		return true;
	};
	for (const raw of rows) {
		const row = raw as StreamedRow;
		if (!row || !row.embed_id || typeof row.version_number !== 'number') continue;
		const version = row.version_number;
		if (await adopt(row, version)) continue;
		const encrypted = port.encrypt_history_row(embedId, JSON.stringify(row), options.hashedUserId);
		if (encrypted === undefined) continue;
		const { local_row, server_payload } = JSON.parse(encrypted) as {
			local_row: EncryptedDiffRow;
			server_payload: Record<string, unknown>;
		};
		await io.storeDiff(local_row);
		try {
			await io.sendDiff(server_payload);
		} catch (error) {
			if (!isDiffConflict(error) || !(await adopt(row, version))) throw error;
		}
	}
}

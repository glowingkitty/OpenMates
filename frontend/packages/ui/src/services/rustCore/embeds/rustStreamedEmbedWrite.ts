/**
 * Finalized streamed-embed write (`send_embed_data`) through the shared
 * Worker's Rust `embedWrite` unit (U9 slice 2; VITE_OPENMATES_RUST_CORE builds
 * only: chatSyncServiceHandlersAI.ts calls this behind the compile-time flag,
 * inside the per-embed canonical write lease).
 *
 * Order (the legacy finalized branch, keys never on the page):
 *   1. install the page's validated chat key and load stored embed keys of the
 *      parent / the embed itself in the Worker (legacy random-key parents keep
 *      their key instead of an HKDF re-derivation); a parent without stored
 *      wrappers gets its early HKDF key (`deriveEarlyKey`);
 *   2. `prepareStreamCompletion`: Rust chooses the key, encrypts, and the
 *      Worker persists entry + local wrappers atomically;
 *   3. send `store_payload` / `server_keys` under the lease;
 *   4. register `embed_ref_registration`, index child refs, refresh caches;
 *   5. revision history: Rust decides every row (unit history ops), the page
 *      performs the canonical bounded-v1 reads and diff sends;
 *   6. Apps index projection and `embedUpdated` dispatch.
 * Returns false only when the Rust crypto arm is inactive (measurement
 * opt-out): the caller then runs the TS branch. Every other failure rejects
 * (the caller unmarks the embed for retry); there is no TS fallback.
 */
import type { ChatSynchronizationService } from '../../chatSyncService';
import type { CanonicalEmbedWriteLease } from '../../canonicalEmbedWriteCoordinator';
import type { SendEmbedDataPayload, StoreEmbedPayload } from '../../../types/chat';
import { chatDB } from '../../db';
import { chatKeyManager } from '../../encryption/ChatKeyManager';
import { computeSHA256 } from '../../../message_parsing/utils';
import { rustWebCrypto } from '../crypto/webCryptoClient';
import { UnitPortError, type UnitPort } from '../host/unitPort';
import type { StreamCompletionInput } from '../embedWriteAdapter';
import type { EmbedWriteProtocol, PersistedEmbedWrite } from './embedDataProtocol';
import { rustEmbedData } from './embedDataClient';
import { rustEmbedWriter } from './embedWriteSession';
import { childRevisionIO, isChildRevisionEvent, runChildRevision } from './rustChildRevisionWrite';

type EmbedData = SendEmbedDataPayload['payload'];
type WriteUnit = UnitPort<EmbedWriteProtocol>;

/** Bounded-v1 page of `version` of `embedId` (`body` undefined on 404). Also used by recovery receipts. */
export async function readCanonicalVersion(chatId: string, embedId: string, version: number): Promise<{ status: number; body: unknown }> {
	const chat = await chatDB.getChat(chatId);
	const query = new URLSearchParams({ capability: 'bounded-v1', chat_id: chatId });
	if (chat?.team_id) query.set('team_id', chat.team_id);
	const { getApiEndpoint, storageArchiveFetch } = await import('../../../config/api');
	const response = await storageArchiveFetch(getApiEndpoint(
		`/v1/embeds/${encodeURIComponent(embedId)}/versions/${version}?${query}`
	), { credentials: 'include' });
	const body = response.status === 404 ? undefined : ((await response.json()) as unknown);
	return { status: response.status, body };
}

function readCanonical(embedData: EmbedData, version: number): Promise<{ status: number; body: unknown }> {
	return readCanonicalVersion(embedData.chat_id, embedData.embed_id, version);
}

/**
 * Key prelude of every Rust embed write: installs the page's validated chat
 * key and loads the stored keys of `parentId` / `embedId` in the Worker (legacy
 * random-key parents keep their key). A still-processing parent has no stored
 * wrappers yet: its early key is the HKDF(chat key, parent id) every tab agrees
 * on (legacy processing branch); a loaded stored key is kept.
 */
export async function loadEmbedWriteKeys(unit: WriteUnit, chatId: string, embedId: string, parentId: string | null | undefined): Promise<void> {
	const chatKey = chatKeyManager.getKeySync(chatId) || (await chatKeyManager.getKey(chatId));
	if (!chatKey) throw new UnitPortError('embed_write_chat_key_missing');
	await unit.request('adoptPageChatKey', { chatId, key: new Uint8Array(chatKey) });
	const hashedChatId = await computeSHA256(chatId);
	const known = [parentId, embedId].filter((id): id is string => typeof id === 'string' && id.length > 0);
	await unit.request('openStoredRows', { rows: known.map((id) => ({
		embedId: id, hashedChatId, encrypted_content: null, encrypted_type: null, encrypted_text_preview: null
	})) });
	if (parentId) await unit.request('deriveEarlyKey', { embedId: parentId, chatId });
}

function isDiffConflict(error: unknown): boolean {
	return error instanceof Error && (error as Error & { code?: string }).code === 'embed_diff_conflict';
}

/** Async port of embedWriteAdapter `persistStreamedHistory` over the unit (Rust decides, page does IO). */
async function persistHistory(service: ChatSynchronizationService, unit: WriteUnit, embedData: EmbedData, options: {
	hashedUserId: string; sealedRootRevision: boolean; durableHead: boolean;
}): Promise<void> {
	const rows = embedData.version_history_rows;
	if (!Array.isArray(rows) || rows.length === 0) return;
	const embedId = embedData.embed_id;
	if (options.sealedRootRevision) {
		await unit.request('reconcileSealedHistory', { embedId, rows, declaredVersion: Number(embedData.version_number ?? 1) });
		if (!options.durableHead) return;
		const head = await unit.request('historyHeadVersion', { embedId, rows });
		if (head === null) return;
		const read = await readCanonical(embedData, head);
		if ((await unit.request('classifyCanonicalRead', { status: read.status, body: undefined, version: head, durableHead: true })) === 'absent') return;
		await unit.request('verifyCanonicalHead', { embedId, page: read.body, rows });
		return;
	}
	const adopt = async (row: Record<string, unknown>, version: number): Promise<boolean> => {
		const read = await readCanonical(embedData, version);
		if ((await unit.request('classifyCanonicalRead', { status: read.status, body: read.body, version, durableHead: false })) === 'absent') return false;
		await unit.request('adoptCanonicalRow', { embedId, page: read.body, row });
		return true;
	};
	const { sendStoreEmbedDiffImpl } = await import('../../chatSyncServiceSenders');
	for (const raw of rows as unknown[]) {
		const row = raw as Record<string, unknown> | null;
		if (!row || !row.embed_id || typeof row.version_number !== 'number') continue;
		const version = row.version_number;
		if (await adopt(row, version)) continue;
		// The unit stores the encrypted local row itself and returns the server payload.
		const payload = await unit.request('encryptHistoryRow', { embedId, row, hashedUserId: options.hashedUserId });
		if (payload === null) continue;
		try {
			await sendStoreEmbedDiffImpl(service, payload as unknown as Parameters<typeof sendStoreEmbedDiffImpl>[1]);
		} catch (error) {
			if (!isDiffConflict(error) || !(await adopt(row, version))) throw error;
		}
	}
}

type PersistedRefs = Pick<PersistedEmbedWrite, 'embed_ref_registration' | 'child_ref_embed_ids'> & { local_entry: { contentRef: string } };

async function afterPersist(persisted: PersistedRefs): Promise<void> {
	const { embedStore, embedAvailabilityVersion } = await import('../../embedStore');
	const registration = persisted.embed_ref_registration;
	if (registration) {
		embedStore.registerEmbedRef(registration.embed_ref, registration.embed_id, registration.app_id, registration.type, registration.skill_id);
	}
	embedStore.removeFromMemoryCache(persisted.local_entry.contentRef);
	embedStore.clearUploadedFileSearchCache();
	embedAvailabilityVersion.update((version) => version + 1);
	// Child refs resolve through the ordinary (Worker-opened) read of each child.
	for (const childId of persisted.child_ref_embed_ids) await embedStore.get(`embed:${childId}`);
}

/** Legacy step 12: the UI refreshes the finalized embed from stored data. */
function dispatchUpdated(service: ChatSynchronizationService, embedData: EmbedData): void {
	service.dispatchEvent(new CustomEvent('embedUpdated', {
		detail: {
			embed_id: embedData.embed_id,
			type: embedData.type,
			chat_id: embedData.chat_id,
			message_id: embedData.message_id,
			task_id: embedData.task_id,
			status: embedData.status,
			version_number: embedData.version_number ?? 1,
			child_embed_ids: embedData.embed_ids,
			isProcessing: false
		}
	}));
}

/**
 * Writes one finalized streamed embed in Rust and dispatches `embedUpdated`.
 * False when the Rust crypto arm is inactive (the caller runs the TS branch).
 */
export async function writeStreamedEmbedInRust(service: ChatSynchronizationService, embedData: EmbedData,
	lease: CanonicalEmbedWriteLease, localOnly: boolean): Promise<boolean> {
	if (!rustWebCrypto()) return false;
	const { unit } = await rustEmbedWriter();
	// The finalized branch validated this key (ensureChatKeySafeForWrite) before taking the lease.
	await loadEmbedWriteKeys(unit, embedData.chat_id, embedData.embed_id, embedData.parent_embed_id);

	const chat = await chatDB.getChat(embedData.chat_id);
	const { normalizeEmbedType } = await import('../../../data/embedRegistry.generated');
	const input = { ...embedData, team_id: chat?.team_id ?? null, local_only: localOnly } as StreamCompletionInput;
	if (isChildRevisionEvent(embedData)) {
		// Version N+1 of an existing image child: never the stream-completion path.
		const io = await childRevisionIO(service, lease, (version) => readCanonical(embedData, version),
			async ({ registration }) => {
				if (registration.op === 'store_embed') await afterPersist({ embed_ref_registration: registration.embed_ref_registration,
					local_entry: { contentRef: registration.content_ref }, child_ref_embed_ids: registration.child_ref_embed_ids });
			});
		await runChildRevision(unit, input, normalizeEmbedType(embedData.type), io);
		dispatchUpdated(service, embedData);
		return true;
	}
	const persisted = await unit.request('prepareStreamCompletion', { payload: input, normalizedType: normalizeEmbedType(embedData.type) });

	const isChild = Boolean(embedData.parent_embed_id);
	let durableHead = false;
	if (!localOnly && persisted.store_payload) {
		const { sendStoreEmbedImpl } = await import('../../chatSyncServiceSenders');
		durableHead = await sendStoreEmbedImpl(service, persisted.store_payload as unknown as StoreEmbedPayload,
			persisted.server_keys ?? undefined, lease, 'stream-completion');
	}
	await afterPersist(persisted);
	if (!localOnly) {
		await persistHistory(service, unit, embedData, {
			hashedUserId: await computeSHA256(embedData.user_id),
			sealedRootRevision: !isChild && Number(embedData.version_number ?? 1) > 1,
			durableHead
		});
	}
	const registration = persisted.embed_ref_registration;
	if (durableHead && !isChild && registration?.app_id && registration.skill_id) {
		const appId = registration.app_id;
		const skillId = registration.skill_id;
		void import('../../appsWorkspaceResultsService')
			.then(({ indexSyncedAppsEmbed }) => indexSyncedAppsEmbed(embedData.embed_id, embedData.chat_id, appId, skillId, chat?.team_id ?? null))
			// Best-effort projection, as the legacy branch: the endpoint re-verifies on the next sync.
			.catch((error: unknown) => console.warn('[RustEmbedWrite] Apps index projection failed', error));
	}
	dispatchUpdated(service, embedData);
	// Bench counter read by web-rust-core-embeds.spec.ts (proves the streamed write ran in Rust).
	const stats = rustEmbedData()?.stats;
	if (stats) stats.streamedWrites += 1;
	return true;
}

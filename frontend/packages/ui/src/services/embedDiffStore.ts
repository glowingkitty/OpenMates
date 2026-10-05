/**
 * Embed Diff Store — manages version history for diffable embeds in IndexedDB.
 *
 * Stores version snapshots and patches locally for the timeline feature.
 * Diffs are fetched lazily when the user opens the version timeline in fullscreen.
 * Encrypted with the same embed_key as the parent embed (zero-knowledge).
 *
 * Architecture: docs/architecture/messaging/embed-diff-editing.md
 */

import { reconstructVersionRows } from '../utils/embedVersionReconstruction';
import { chatDB } from './db';
import { getApiEndpoint, storageArchiveFetch } from '../config/api';
import { decryptWithEmbedKey, encryptWithEmbedKey } from './encryption/MetadataEncryptor';
import { embedStore } from './embedStore';
import { computeSHA256 } from '../message_parsing/utils';
import type { StoreEmbedPayload } from '../types/chat';

// ─── Types ──────────────────────────────────────────────────────────

export interface EmbedDiffRow {
	id: string; // `${embed_id}_v${version_number}`
	embed_id: string;
	version_number: number;
	encrypted_snapshot?: string; // Full content for v=1 only
	encrypted_patch?: string; // Unified diff for v>1
	created_at: number; // Unix timestamp
}

export interface EmbedVersionMeta {
	version_number: number;
	created_at: number;
	has_snapshot: boolean;
	has_patch: boolean;
	encrypted_snapshot?: string | null;
	encrypted_patch?: string | null;
}

export interface EmbedVersionsResponse {
	embed_id: string;
	current_version: number;
	versions: EmbedVersionMeta[];
	next_cursor?: number | null;
	readonly: boolean;
}

export interface EmbedVersionContentResponse {
	embed_id: string;
	version_number: number;
	current_version: number;
	content?: string;
	rows?: EmbedVersionMeta[];
	readonly: boolean;
}

export interface EmbedVersionRestoreResponse {
	embed_id: string;
	restored_from_version: number;
	version_number: number;
	content_hash: string;
	content: string;
}

export interface EmbedVersionContext {
	chatId?: string;
	projectId?: string;
	teamId?: string | null;
}

export interface RestoreEmbedVersionOptions extends EmbedVersionContext {
	currentVersion: number;
	currentContent: string;
	buildRestoredContent: (restoredContent: string, newVersion: number) => Record<string, unknown>;
}

// ─── Store Operations ───────────────────────────────────────────────

const STORE_NAME = 'embed_diffs';

function embedVersionError(data: unknown, fallback: string): Error {
	if (data && typeof data === 'object') {
		const detail = (data as { detail?: unknown; message?: unknown }).detail;
		const message = (data as { detail?: unknown; message?: unknown }).message;
		if (typeof detail === 'string' && detail.trim()) return new Error(detail);
		if (typeof message === 'string' && message.trim()) return new Error(message);
	}
	return new Error(fallback);
}

async function versionReadScope(context?: string | EmbedVersionContext): Promise<URLSearchParams> {
	const selected = typeof context === 'string' ? { chatId: context } : context;
	const params = new URLSearchParams();
	if (selected?.projectId) {
		if (selected.chatId) throw new Error('Select either Project or chat version context');
		params.set('project_id', selected.projectId);
		if (selected.teamId) params.set('team_id', selected.teamId);
		return params;
	}
	if (!selected?.chatId) {
		if (selected?.teamId) throw new Error('Team version context requires a Project or chat');
		return params;
	}
	params.set('chat_id', selected.chatId);
	const chat = await chatDB.getChat(selected.chatId);
	const teamId = selected.teamId ?? chat?.team_id;
	if (teamId) params.set('team_id', teamId);
	return params;
}

async function readJsonResponse<T>(response: Response, fallback: string): Promise<T> {
	let data: unknown = {};
	try {
		data = await response.json();
	} catch {
		data = {};
	}
	if (!response.ok) throw embedVersionError(data, fallback);
	return data as T;
}

export async function fetchEmbedVersions(
	embedId: string,
	pageOptions?: EmbedVersionContext & { cursor?: number; limit?: number; order?: 'asc' | 'desc' }
): Promise<EmbedVersionsResponse> {
	const path = `/v1/embeds/${encodeURIComponent(embedId)}/versions`;
	const scope = await versionReadScope(pageOptions);
	if (pageOptions) {
		const params = new URLSearchParams(scope);
		params.set('order', pageOptions.order ?? 'desc');
		params.set('limit', String(pageOptions.limit ?? 32));
		if (pageOptions.cursor !== undefined) params.set('cursor', String(pageOptions.cursor));
		const response = await storageArchiveFetch(getApiEndpoint(`${path}?${params}`), { credentials: 'include' });
		return readJsonResponse<EmbedVersionsResponse>(response, `Failed to load embed versions (${response.status})`);
	}
	let cursor: number | null = null;
	let combined: EmbedVersionsResponse | null = null;
	do {
		const params = new URLSearchParams(scope);
		if (cursor !== null) params.set('cursor', String(cursor));
		const response = await storageArchiveFetch(getApiEndpoint(`${path}${params.size ? `?${params}` : ''}`), {
			credentials: 'include'
		});
		const page = await readJsonResponse<EmbedVersionsResponse>(response, `Failed to load embed versions (${response.status})`);
		combined = combined ? { ...page, versions: [...combined.versions, ...page.versions] } : page;
		if (page.next_cursor != null && (page.versions.length === 0 || page.next_cursor <= (cursor ?? 0))) {
			throw new Error('Invalid embed version cursor');
		}
		cursor = page.next_cursor ?? null;
	} while (cursor !== null);
	return combined!;
}

export async function fetchEmbedVersionContent(
	embedId: string,
	versionNumber: number,
	context?: string | EmbedVersionContext
): Promise<EmbedVersionContentResponse> {
	const path = `/v1/embeds/${encodeURIComponent(embedId)}/versions/${versionNumber}`;
	const scope = await versionReadScope(context);
	const bounded = new URLSearchParams(scope);
	bounded.set('capability', 'bounded-v1');
	let response = await storageArchiveFetch(
		getApiEndpoint(`${path}?${bounded}`),
		{ credentials: 'include' }
	);
	// Older histories remain readable while a write-authorized client supplies
	// checkpoints. Their PostgreSQL source payloads cannot be evicted yet.
	if (response.status === 409) {
		response = await storageArchiveFetch(getApiEndpoint(`${path}${scope.size ? `?${scope}` : ''}`), { credentials: 'include' });
	}
	const responseData = await readJsonResponse<EmbedVersionContentResponse>(
		response,
		`Failed to load embed version ${versionNumber} (${response.status})`
	);
	if (responseData.embed_id !== embedId || responseData.version_number !== versionNumber) {
		throw new Error('Version response does not match the selected version');
	}
	if (typeof responseData.content === 'string') return responseData;
	if (!Array.isArray(responseData.rows) || responseData.rows.at(-1)?.version_number !== versionNumber) {
		throw new Error('Version response does not match the selected version');
	}
	const content = await reconstructEncryptedVersion(embedId, responseData.rows);
	if (responseData.rows.length > 32 && responseData.readonly === false) {
		void publishClientSnapshot(embedId, versionNumber, responseData.current_version, content, scope);
	}
	return { ...responseData, content };
}

async function publishClientSnapshot(embedId: string, versionNumber: number, currentVersion: number, content: string, scope: URLSearchParams): Promise<void> {
	try {
		const key = await embedStore.getEmbedKey(embedId);
		if (!key) return;
		const encrypted = await encryptWithEmbedKey(content, key);
		if (!encrypted) return;
		await storageArchiveFetch(getApiEndpoint(`/v1/embeds/${encodeURIComponent(embedId)}/versions/${versionNumber}/snapshot`), {
			method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ encrypted_snapshot: encrypted, expected_revision: currentVersion, operation_id: `snapshot.v${versionNumber}`,
				...(scope.has('project_id') ? { project_id: scope.get('project_id'), ...(scope.has('team_id') ? { team_id: scope.get('team_id') } : {}) } : {}) })
		});
	} catch {
		// A read-only device or concurrent edit cannot publish; the source stays hot.
	}
}

export async function restoreEmbedVersion(
	embedId: string,
	versionNumber: number,
	options?: RestoreEmbedVersionOptions
): Promise<EmbedVersionRestoreResponse> {
	if (!options) {
		throw new Error('Embed version restore requires client-side encrypted restore options');
	}
	if (versionNumber === options.currentVersion) {
		throw new Error('Selected version is already current');
	}

	const response = await fetchEmbedVersionContent(embedId, versionNumber, options);
	if (typeof response.content !== 'string') {
		throw new Error('Version content was not available for restore');
	}

	const restoredContent = response.content;
	const newVersion = options.currentVersion + 1;
	const restoredPayload = options.buildRestoredContent(restoredContent, newVersion);
	const restoredToonContent = await encodeRestoredEmbedContent(restoredPayload);
	const contentHash = await computeSHA256(restoredContent);
	const updateResult = await embedStore.prepareVersionRestoreUpdate(
		embedId,
		restoredToonContent,
		newVersion,
		contentHash
	);
	if (!updateResult.updated || !updateResult.storePayload) {
		throw new Error('Embed is not writable on this device');
	}

	const embedKey = await embedStore.getEmbedKey(embedId);
	if (!embedKey) throw new Error('Embed key not available for version restore');
	const restorePatch = buildUnifiedDiff(options.currentContent, restoredContent, options.currentVersion, newVersion);
	const encryptedPatch = await encryptWithEmbedKey(restorePatch, embedKey);
	if (!encryptedPatch) throw new Error('Failed to encrypt restore patch');
	const encryptedSnapshot = newVersion % 32 === 0
		? await encryptWithEmbedKey(restoredContent, embedKey)
		: null;

	const createdAt = Math.floor(Date.now() / 1000);
	await storeEmbedDiff({
		id: `${embedId}_v${newVersion}`,
		embed_id: embedId,
		version_number: newVersion,
		encrypted_patch: encryptedPatch,
		...(encryptedSnapshot ? { encrypted_snapshot: encryptedSnapshot } : {}),
		created_at: createdAt
	});

	await syncEncryptedRestore(embedId, newVersion, encryptedPatch, encryptedSnapshot, createdAt, updateResult.storePayload);

	return {
		embed_id: embedId,
		restored_from_version: versionNumber,
		version_number: newVersion,
		content_hash: contentHash,
		content: restoredContent
	};
}

async function encodeRestoredEmbedContent(payload: Record<string, unknown>): Promise<string> {
	try {
		const { encode } = await import('@toon-format/toon');
		return encode(payload);
	} catch {
		return JSON.stringify(payload);
	}
}

function buildUnifiedDiff(currentContent: string, restoredContent: string, currentVersion: number, newVersion: number): string {
	const oldLines = currentContent ? currentContent.split('\n') : [];
	const newLines = restoredContent ? restoredContent.split('\n') : [];
	return [
		`--- v${currentVersion}`,
		`+++ v${newVersion}`,
		`@@ -${oldLines.length ? 1 : 0},${oldLines.length} +${newLines.length ? 1 : 0},${newLines.length} @@`,
		...oldLines.map((line) => `-${line}`),
		...newLines.map((line) => `+${line}`)
	].join('\n');
}

async function syncEncryptedRestore(
	embedId: string,
	versionNumber: number,
	encryptedPatch: string,
	encryptedSnapshot: string | null,
	createdAt: number,
	storePayload: StoreEmbedPayload
): Promise<void> {
	const [{ chatSyncService }, sendersModule] = await Promise.all([
		import('./chatSyncService'),
		import('./chatSyncServiceSenders')
	]);
	await sendersModule.sendStoreEmbedImpl(chatSyncService, storePayload);
	await sendersModule.sendStoreEmbedDiffImpl(chatSyncService, {
		embed_id: embedId,
		version_number: versionNumber,
		encrypted_snapshot: encryptedSnapshot,
		encrypted_patch: encryptedPatch,
		hashed_user_id: storePayload.hashed_user_id,
		created_at: createdAt
	});
}

async function reconstructEncryptedVersion(embedId: string, rows: EmbedVersionMeta[]): Promise<string> {
	const embedKey = await embedStore.getEmbedKey(embedId);
	if (!embedKey) throw new Error('Embed key not available for version history');
	return reconstructEncryptedVersionRows(rows, embedKey);
}

export async function reconstructEncryptedVersionRows(rows: EmbedVersionMeta[], embedKey: Uint8Array): Promise<string> {
	return reconstructVersionRows(rows, (ciphertext) => decryptWithEmbedKey(ciphertext, embedKey));
}

/**
 * Store a diff row in IndexedDB (called when receiving embed_diff_created WS event).
 */
export async function storeEmbedDiff(diff: EmbedDiffRow): Promise<void> {
	await chatDB.init();
	const idb = chatDB.db;
	if (!idb) return;

	const tx = idb.transaction(STORE_NAME, 'readwrite');
	const store = tx.objectStore(STORE_NAME);
	await new Promise<void>((resolve, reject) => {
		const req = store.put(diff);
		req.onsuccess = () => resolve();
		req.onerror = () => reject(req.error);
	});
}

/**
 * Get all version history for an embed (for timeline rendering).
 * Returns rows sorted by version_number ascending.
 */
export async function getEmbedDiffs(embedId: string): Promise<EmbedDiffRow[]> {
	await chatDB.init();
	const idb = chatDB.db;
	if (!idb) return [];

	const tx = idb.transaction(STORE_NAME, 'readonly');
	const store = tx.objectStore(STORE_NAME);
	const index = store.index('embed_id');

	return new Promise<EmbedDiffRow[]>((resolve, reject) => {
		const req = index.getAll(embedId);
		req.onsuccess = () => {
			const rows = (req.result as EmbedDiffRow[]) || [];
			rows.sort((a, b) => a.version_number - b.version_number);
			resolve(rows);
		};
		req.onerror = () => reject(req.error);
	});
}

/**
 * Check if version history exists locally for an embed.
 */
export async function hasLocalDiffs(embedId: string): Promise<boolean> {
	const diffs = await getEmbedDiffs(embedId);
	return diffs.length > 0;
}

/**
 * Delete all diffs for an embed (called on embed deletion).
 */
export async function deleteEmbedDiffs(embedId: string): Promise<void> {
	await chatDB.init();
	const idb = chatDB.db;
	if (!idb) return;

	const tx = idb.transaction(STORE_NAME, 'readwrite');
	const store = tx.objectStore(STORE_NAME);
	const index = store.index('embed_id');

	const req = index.getAllKeys(embedId);
	await new Promise<void>((resolve, reject) => {
		req.onsuccess = () => {
			const keys = req.result;
			for (const key of keys) {
				store.delete(key);
			}
			resolve();
		};
		req.onerror = () => reject(req.error);
	});
}

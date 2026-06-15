/**
 * Embed Diff Store — manages version history for diffable embeds in IndexedDB.
 *
 * Stores version snapshots and patches locally for the timeline feature.
 * Diffs are fetched lazily when the user opens the version timeline in fullscreen.
 * Encrypted with the same embed_key as the parent embed (zero-knowledge).
 *
 * Architecture: docs/architecture/messaging/embed-diff-editing.md
 */

import { chatDB } from './db';
import { getApiEndpoint } from '../config/api';
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

export interface RestoreEmbedVersionOptions {
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

export async function fetchEmbedVersions(embedId: string): Promise<EmbedVersionsResponse> {
	const response = await fetch(getApiEndpoint(`/v1/embeds/${encodeURIComponent(embedId)}/versions`), {
		credentials: 'include'
	});
	return readJsonResponse<EmbedVersionsResponse>(response, `Failed to load embed versions (${response.status})`);
}

export async function fetchEmbedVersionContent(
	embedId: string,
	versionNumber: number
): Promise<EmbedVersionContentResponse> {
	const response = await fetch(
		getApiEndpoint(`/v1/embeds/${encodeURIComponent(embedId)}/versions/${versionNumber}`),
		{ credentials: 'include' }
	);
	const responseData = await readJsonResponse<EmbedVersionContentResponse>(
		response,
		`Failed to load embed version ${versionNumber} (${response.status})`
	);
	if (typeof responseData.content === 'string') return responseData;
	if (!Array.isArray(responseData.rows)) return responseData;
	const content = await reconstructEncryptedVersion(embedId, responseData.rows);
	return { ...responseData, content };
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

	const response = await fetchEmbedVersionContent(embedId, versionNumber);
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

	const createdAt = Math.floor(Date.now() / 1000);
	await storeEmbedDiff({
		id: `${embedId}_v${newVersion}`,
		embed_id: embedId,
		version_number: newVersion,
		encrypted_patch: encryptedPatch,
		created_at: createdAt
	});

	await syncEncryptedRestore(embedId, newVersion, encryptedPatch, createdAt, updateResult.storePayload);

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
	return [
		`--- v${currentVersion}`,
		`+++ v${newVersion}`,
		`@@ -1,${Math.max(1, currentContent.split('\n').length)} +1,${Math.max(1, restoredContent.split('\n').length)} @@`,
		...currentContent.split('\n').map((line) => `-${line}`),
		...restoredContent.split('\n').map((line) => `+${line}`)
	].join('\n');
}

async function syncEncryptedRestore(
	embedId: string,
	versionNumber: number,
	encryptedPatch: string,
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
		encrypted_snapshot: null,
		encrypted_patch: encryptedPatch,
		hashed_user_id: storePayload.hashed_user_id,
		created_at: createdAt
	});
}

async function reconstructEncryptedVersion(embedId: string, rows: EmbedVersionMeta[]): Promise<string> {
	const embedKey = await embedStore.getEmbedKey(embedId);
	if (!embedKey) throw new Error('Embed key not available for version history');
	const sortedRows = [...rows].sort((a, b) => a.version_number - b.version_number);
	let content: string | null = null;
	for (const row of sortedRows) {
		if (row.encrypted_snapshot) {
			content = await decryptWithEmbedKey(row.encrypted_snapshot, embedKey);
			continue;
		}
		if (row.encrypted_patch && content !== null) {
			const patch = await decryptWithEmbedKey(row.encrypted_patch, embedKey);
			content = applyUnifiedDiff(content, patch || '');
		}
	}
	if (content === null) throw new Error('Version history is missing the initial snapshot');
	return content;
}

function applyUnifiedDiff(content: string, patch: string): string {
	const contentLines = content.split('\n');
	const lines = patch.split('\n');
	const hunks: Array<{ start: number; oldLines: string[]; newLines: string[] }> = [];
	let current: { start: number; oldLines: string[]; newLines: string[] } | null = null;
	for (const line of lines) {
		const match = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(line);
		if (match) {
			if (current) hunks.push(current);
			current = { start: Number(match[1]) - 1, oldLines: [], newLines: [] };
			continue;
		}
		if (!current) continue;
		if (line.startsWith(' ')) {
			current.oldLines.push(line.slice(1));
			current.newLines.push(line.slice(1));
		} else if (line.startsWith('-')) {
			current.oldLines.push(line.slice(1));
		} else if (line.startsWith('+')) {
			current.newLines.push(line.slice(1));
		}
	}
	if (current) hunks.push(current);
	for (const hunk of hunks.sort((a, b) => b.start - a.start)) {
		const actual = contentLines.slice(hunk.start, hunk.start + hunk.oldLines.length);
		if (actual.join('\n') !== hunk.oldLines.join('\n')) {
			throw new Error('Version patch context does not match local content');
		}
		contentLines.splice(hunk.start, hunk.oldLines.length, ...hunk.newLines);
	}
	return contentLines.join('\n');
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

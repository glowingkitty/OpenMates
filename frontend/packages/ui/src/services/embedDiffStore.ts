/**
 * Embed Diff Store — manages version history for diffable embeds in IndexedDB.
 *
 * Stores version snapshots and patches locally for the timeline feature.
 * Diffs are fetched lazily when the user opens the version timeline in fullscreen.
 * Encrypted with the same embed_key as the parent embed (zero-knowledge).
 *
 * Architecture: docs/architecture/messaging/embed-diff-editing.md
 */

import { ChatDatabase } from './db';

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
}

// ─── Store Operations ───────────────────────────────────────────────

const STORE_NAME = 'embed_diffs';

/**
 * Store a diff row in IndexedDB (called when receiving embed_diff_created WS event).
 */
export async function storeEmbedDiff(diff: EmbedDiffRow): Promise<void> {
	const db = ChatDatabase.getInstance();
	const idb = await db.getDB();
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
	const db = ChatDatabase.getInstance();
	const idb = await db.getDB();
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
	const db = ChatDatabase.getInstance();
	const idb = await db.getDB();
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

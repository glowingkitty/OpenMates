/**
 * Typing mirror glue shared by the live editors: a local Y.Doc that only exchanges
 * opaque update bytes with the core, plus an Awareness that renders the core's peers.
 * It makes no decisions: the core merges, seals and decides access.
 */
import * as Y from 'yjs';
import { Awareness } from 'y-protocols/awareness';
import type { LiveItemClient, LivePeer, LiveItemKind } from './liveItemTypes';

/** Origin of updates that came from the core; never echoed back. */
export const REMOTE_ORIGIN = 'remote';

/** Stable numeric awareness id for a peer (rendering key only). */
export function peerClientId(userId: string): number {
	let h = 2166136261;
	for (let i = 0; i < userId.length; i++) h = Math.imul(h ^ userId.charCodeAt(i), 16777619);
	return (h >>> 0) || 1;
}

export interface LiveMirror {
	doc: Y.Doc;
	awareness: Awareness;
	destroy(): void;
}

/** Opens the item in the core and binds `doc` to it; returns the doc, awareness and a teardown. */
export function bindLiveMirror(
	client: LiveItemClient, itemId: string, kind: LiveItemKind, self: Pick<LivePeer, 'display_name' | 'color'>,
	onStatus?: (status: import('./liveItemTypes').LiveStatus) => void,
	onPeers?: (peers: LivePeer[]) => void,
	projectId?: string,
	teamId?: string,
): LiveMirror {
	const doc = new Y.Doc();
	const awareness = new Awareness(doc);
	awareness.setLocalStateField('user', { name: self.display_name, color: self.color });
	const remote = new Map<number, string>();

	// The core refuses mirror updates until it holds the item (open waits for the
	// session and the key), so typing before the core's first full state would be
	// dropped. Hold local updates until that state arrives, then send them merged;
	// Yjs merges them with the stored content, so nothing typed is lost.
	let synced = false;
	let held: Uint8Array[] = [];
	const onDocUpdate = (update: Uint8Array, origin: unknown) => {
		if (origin === REMOTE_ORIGIN) return;
		if (!synced) { held.push(update); return; }
		void client.liveApplyMirrorUpdate(itemId, update);
	};
	const onCoreState = (bytes: Uint8Array) => {
		Y.applyUpdate(doc, bytes, REMOTE_ORIGIN);
		if (synced) return;
		synced = true;
		if (held.length) void client.liveApplyMirrorUpdate(itemId, Y.mergeUpdates(held));
		held = [];
	};
	doc.on('update', onDocUpdate);

	const onAwareness = (_changes: unknown, origin: unknown) => {
		if (origin === REMOTE_ORIGIN) return;
		const state = awareness.getLocalState();
		// The core adds who this is (hashed user id, colour); the page adds only the visible name.
		void client.liveSetPresence(itemId, { kind_cursor: state?.cursor ?? null, display_name: self.display_name });
	};
	awareness.on('change', onAwareness);

	const stops = [
		client.on('liveRemoteUpdate', (e) => { if (e.itemId === itemId) onCoreState(e.bytes); }),
		client.on('livePresence', (e) => {
			if (e.itemId !== itemId) return;
			const states = awareness.getStates();
			const next = new Map<number, string>(e.peers.map((p) => [peerClientId(p.user_id), p.user_id]));
			const removed: number[] = [];
			for (const id of remote.keys()) if (!next.has(id)) { states.delete(id); removed.push(id); }
			const added: number[] = [];
			const updated: number[] = [];
			for (const p of e.peers) {
				const id = peerClientId(p.user_id);
				(remote.has(id) ? updated : added).push(id);
				states.set(id, { user: { name: p.mate_name ?? p.mate ?? p.display_name, color: p.color, mate: p.mate_name ?? p.mate ?? null }, cursor: p.kind_cursor ?? null });
			}
			remote.clear();
			for (const [id, user] of next) remote.set(id, user);
			awareness.emit('change', [{ added, updated, removed }, REMOTE_ORIGIN]);
			onPeers?.(e.peers);
		}),
		client.on('liveStatus', (e) => { if (e.itemId === itemId) onStatus?.(e.status); }),
	];
	client.liveOpen(itemId, kind, projectId, teamId).catch((error: unknown) => {
		console.warn('[live] open failed', itemId, error);
		// The core never opened the item: show it as offline instead of spinning on "saving".
		onStatus?.('offline');
	});

	return {
		doc,
		awareness,
		destroy() {
			for (const stop of stops) stop();
			doc.off('update', onDocUpdate);
			awareness.off('change', onAwareness);
			awareness.destroy();
			doc.destroy();
			void client.liveClose(itemId);
		},
	};
}

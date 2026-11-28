/**
 * Preview/test fake: two page clients joined directly, as if the core relayed
 * mirror updates and presence between two people. No sealing, no server.
 */
import * as Y from 'yjs';
import type { LiveEventName, LiveEvents, LiveItemClient, LivePeer } from './liveItemTypes';

export interface FakeLiveEndpoint { client: LiveItemClient; peer: LivePeer }

function endpoint(peer: LivePeer): { client: LiveItemClient; emit: <E extends LiveEventName>(e: E, p: LiveEvents[E]) => void; peer: LivePeer; sendTo?: (p: LivePeer) => void } {
	const listeners = new Map<LiveEventName, Set<(payload: never) => void>>();
	return {
		peer,
		emit(event, payload) { for (const l of [...(listeners.get(event) ?? [])]) l(payload as never); },
		client: {
			async liveOpen() {}, async liveApplyMirrorUpdate() {}, async liveApplyOp() {}, async liveSetPresence() {}, async liveClose() {},
			on(event, listener) {
				const set = listeners.get(event) ?? new Set();
				set.add(listener as (payload: never) => void);
				listeners.set(event, set);
				return () => { set.delete(listener as (payload: never) => void); };
			},
		},
	};
}

/** Two clients; an update or presence set on one reaches the other. */
export function createFakeLiveLink(a: LivePeer, b: LivePeer, seed?: Uint8Array): [FakeLiveEndpoint, FakeLiveEndpoint] {
	const ea = endpoint(a);
	const eb = endpoint(b);
	if (!seed) {
		const empty = new Y.Doc();
		seed = Y.encodeStateAsUpdate(empty);
		empty.destroy();
	}
	const initial = seed;
	// The mirror waits for the initial state even when the document is empty.
	for (const e of [ea, eb]) {
		e.client.liveOpen = async (itemId) => { queueMicrotask(() => e.emit('liveRemoteUpdate', { itemId, bytes: initial })); };
	}
	const wire = (from: typeof ea, to: typeof ea) => {
		from.client.liveApplyMirrorUpdate = async (itemId, bytes) => { to.emit('liveRemoteUpdate', { itemId, bytes }); };
		from.client.liveSetPresence = async (itemId, presence) => {
			to.emit('livePresence', { itemId, peers: [{ ...from.peer, kind_cursor: presence.kind_cursor }] });
		};
	};
	wire(ea, eb);
	wire(eb, ea);
	return [{ client: ea.client, peer: a }, { client: eb.client, peer: b }];
}

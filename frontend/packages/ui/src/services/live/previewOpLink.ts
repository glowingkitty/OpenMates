/**
 * PREVIEW-ONLY fake of the core for sheets and decks: two page clients share a tiny
 * in-memory model that applies typed ops, so component specs can show two editors
 * converging and each other's presence. The real model, merge and sealing live only
 * in the Rust core; this file must never be imported by production components.
 */
import type { LiveEventName, LiveEvents, LiveItemClient, LivePeer } from './liveItemTypes';

export interface PreviewEndpoint { client: LiveItemClient; peer: LivePeer }

export function createPreviewOpLink<V>(a: LivePeer, b: LivePeer, initial: V, applyOp: (view: V, op: unknown) => V): [PreviewEndpoint, PreviewEndpoint] {
	let model = initial;
	const sinks: Array<Map<LiveEventName, Set<(payload: never) => void>>> = [new Map(), new Map()];
	const emit = <E extends LiveEventName>(side: number, event: E, payload: LiveEvents[E]) => {
		for (const l of [...(sinks[side].get(event) ?? [])]) l(payload as never);
	};
	const make = (side: number, peer: LivePeer): PreviewEndpoint => ({
		peer,
		client: {
			async liveOpen(itemId) { queueMicrotask(() => emit(side, 'liveView', { itemId, view: model })); },
			async liveApplyMirrorUpdate() {},
			async liveApplyOp(itemId, op) {
				model = applyOp(model, op);
				queueMicrotask(() => { emit(0, 'liveView', { itemId, view: model }); emit(1, 'liveView', { itemId, view: model }); });
			},
			async liveSetPresence(itemId, presence) {
				emit(1 - side, 'livePresence', { itemId, peers: [{ ...peer, cursor: presence.cursor }] });
			},
			async liveClose() {},
			on(event, listener) {
				const set = sinks[side].get(event) ?? new Set();
				set.add(listener as (payload: never) => void);
				sinks[side].set(event, set);
				return () => { set.delete(listener as (payload: never) => void); };
			},
		},
	});
	return [make(0, a), make(1, b)];
}

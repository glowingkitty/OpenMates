// TS-generated parity vectors for the shared Rust offline-outbox decisions.
// The committed JSON (packages/openmates-rust/src/web_send_prep/ts_vectors.json)
// holds inputs plus the outcomes of orderOfflineChanges (offlineChangeOrder.ts)
// and decideOfflineBatchReceipt (offlineBatchReceipt.ts). This test fails if the
// TypeScript behaviour drifts from the vectors; web_send_prep/tests.rs replays
// the same file against Rust. It also checks the Worker handlers' marshalling.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { modelRoutingRestrictionsForTurn } from '../../modelRoutingRestrictions';
import { orderOfflineChanges } from '../../offlineChangeOrder';
import { decideOfflineBatchReceipt } from '../../offlineBatchReceipt';
import { createSendPrepHandlers } from '../send/sendPrepUnit';
import { isSendPrepBinding, type SendPrepBinding } from '../send/sendPrepProtocol';
import type { OfflineChange } from '../../../types/chat';

const vectors = JSON.parse(readFileSync(resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_send_prep/ts_vectors.json'), 'utf8'));

const routingVectors = JSON.parse(readFileSync(resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_send_prep/ts_routing_vectors.json'), 'utf8'));

describe('offline outbox vectors', () => {
	// contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
	it('order equals the TypeScript service', () => {
		for (const c of vectors.order) {
			const changes = c.changes as OfflineChange[];
			const result = orderOfflineChanges(changes);
			expect(result.ready.map((x) => changes.indexOf(x)), c.name).toEqual(c.ready);
			expect(result.retainedCount, c.name).toBe(c.retained);
		}
	});
	// contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
	it('receipt equals the TypeScript service', () => {
		for (const c of vectors.receipt) {
			const result = decideOfflineBatchReceipt(c.ids, c.term, c.ok, c.counts);
			expect(result.accepted, c.name).toEqual(c.accepted);
			expect(result.retiredConflictIds, c.name).toEqual(c.retired);
		}
	});
});

describe('routing restriction vectors', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('equal the TypeScript service', () => {
		for (const c of routingVectors) {
			if (c.ok) expect(modelRoutingRestrictionsForTurn(c.profile), c.name).toEqual(c.restrictions);
			else expect(() => modelRoutingRestrictionsForTurn(c.profile), c.name).toThrow('Invalid model routing restrictions');
		}
	});
});

describe('sendPrep handlers', () => {
	const binding: SendPrepBinding = {
		send_prep_routing_restrictions: () => JSON.stringify({ ok: false }),
		send_prep_order_offline: (input) => JSON.stringify({ ready: [JSON.parse(input).rows.length - 1], retained: 0 }),
		send_prep_offline_receipt: () => { throw 'protocol'; },
	};
	// contract-test: supporting surface=gui.web assertions=chats.message.identity-idempotent
	it('forwards JSON text and maps binding rejection to protocol', async () => {
		expect(isSendPrepBinding(binding)).toBe(true);
		expect(isSendPrepBinding({})).toBe(false);
		const handlers = createSendPrepHandlers(binding);
		const order = await handlers.orderOffline({ rows: [{ chat_id: 'a', type: 'draft' }, { chat_id: 'b', type: 'draft' }] }, undefined as never);
		expect(order).toEqual({ ready: [1], retained: 0 });
		expect(await handlers.routingRestrictions({}, undefined as never)).toEqual({ ok: false });
		await expect(Promise.resolve().then(() => handlers.offlineReceipt({ changeIds: [], terminalConflictDeleteIds: [], successfulIds: [], counts: null }, undefined as never)))
			.rejects.toMatchObject({ code: 'protocol' });
		await expect(Promise.resolve().then(() => handlers.orderOffline('x' as never, undefined as never))).rejects.toMatchObject({ code: 'protocol' });
	});
});

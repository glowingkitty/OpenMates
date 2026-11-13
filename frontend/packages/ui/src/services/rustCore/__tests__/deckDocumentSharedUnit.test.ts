// contract-test-file: tooling
// spec: specifications/features/live-collaboration#live-collab.core.one-shared-model
// `deckDocument` unit of the shared Rust core Worker: the real router, installer and page
// client over a scripted `DeckDocumentTable` (the deck behaviour itself is proven by
// deck_handles_tests.rs). Checks marshalling only: JSON and bytes pass through unchanged,
// the core's error code reaches the page, malformed requests answer `protocol`, and the
// table is freed when the unit is disposed.
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createSharedCoreClient, registerSharedRustCore, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter } from '../host/sharedWorkerProtocol';
import { UnitPortError } from '../host/unitPort';
import { createDeckDocumentHandlers, installDeckDocumentUnit } from '../deckDocument/deckDocumentUnit';
import type { DeckDocumentTable } from '../deckDocument/deckDocumentProtocol';
import {
	applyDeckOperation, closeDeckDocument, deckApplyUpdate, deckEncodeUpdateSince, deckStateVector, deckToMarkup, openDeckDocument,
	redoDeck, rustDeckDocumentStats, undoDeck,
} from '../deckDocument/deckDocumentClient';
import type { DeckView } from '../deckDocument/deckDocumentTypes';

const VIEW: DeckView = {
	title: 'T', aspect: '16:9', template: 'builtin:plain', canvas_width: 1920, canvas_height: 1080,
	slides: [{ id: 's1', layout: null, transition: null, notes: '', elements: [] }], can_undo: false, can_redo: false,
};

const calls: string[] = [];
const tables: ScriptedTable[] = [];

class ScriptedTable implements DeckDocumentTable {
	freed = false;
	size = 0;
	constructor() { tables.push(this); }
	open(markup: string) {
		calls.push(`open ${markup}`);
		if (markup === 'bad') throw 'slides_markup_not_normalised';
		return JSON.stringify({ handle: 1, view: VIEW });
	}
	apply(handle: number, operationJson: string) {
		calls.push(`apply ${handle} ${operationJson}`);
		if (handle !== 1) throw 'shared_item_unknown_handle';
		return JSON.stringify({ outcome: { outcome: 'applied' }, view: { ...VIEW, can_undo: true } });
	}
	undo(handle: number) { calls.push(`undo ${handle}`); return JSON.stringify({ changed: true, view: VIEW }); }
	redo(handle: number) { calls.push(`redo ${handle}`); return JSON.stringify({ changed: false, view: VIEW }); }
	view(handle: number) { calls.push(`view ${handle}`); return JSON.stringify({ view: VIEW }); }
	toMarkup(handle: number) { calls.push(`toMarkup ${handle}`); return '<deck/>'; }
	stateVector(handle: number) { calls.push(`stateVector ${handle}`); return new Uint8Array([1, 2]); }
	encodeUpdateSince(handle: number, stateVector: Uint8Array) {
		calls.push(`encode ${handle} ${[...stateVector]}`);
		return new Uint8Array([9, ...stateVector]);
	}
	applyUpdate(handle: number, update: Uint8Array) {
		calls.push(`applyUpdate ${handle} ${[...update]}`);
		if (update.length === 0) throw new Error('internal text never crosses');
		return JSON.stringify({ view: VIEW });
	}
	close(handle: number) { calls.push(`close ${handle}`); return handle === 1; }
	free() { this.freed = true; }
}

const binding = { DeckDocumentTable: ScriptedTable };

function fakeWorker() {
	const listeners: Record<string, ((event: Event) => void)[]> = { message: [], error: [], messageerror: [] };
	const router = createSharedWorkerRouter({
		installers: { deckDocument: installDeckDocumentUnit },
		loadBinding: async () => binding,
		reply: (reply) => queueMicrotask(() => { for (const l of listeners.message) l({ data: reply } as MessageEvent); }),
	});
	const endpoint: SharedWorkerEndpoint = {
		postMessage(message, transfer) { void router.handle(message, transfer as MessagePort[]); },
		addEventListener(type, listener) { listeners[type].push(listener); },
		terminate() {},
	};
	return endpoint;
}

async function code(promise: Promise<unknown>): Promise<string> {
	try {
		await promise;
	} catch (error) {
		expect(error).toBeInstanceOf(UnitPortError);
		return (error as UnitPortError).code;
	}
	throw new Error('expected a refusal');
}

let unregister: (() => void) | null = null;
beforeEach(() => {
	calls.length = 0;
	unregister = registerSharedRustCore(createSharedCoreClient(fakeWorker));
});
afterEach(() => { unregister?.(); });

describe('shared deckDocument unit', () => {
	// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model
	it('refuses a binding without the DeckDocumentTable export', () => {
		const channel = new MessageChannel();
		expect(() => installDeckDocumentUnit({ binding: {}, ports: [channel.port2], generation: null, principal: null, signal: new AbortController().signal }))
			.toThrow('unavailable');
	});

	// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model
	it('passes operations, views and update bytes through the Rust table', async () => {
		const before = rustDeckDocumentStats.calls;
		await expect(openDeckDocument('<deck>')).resolves.toEqual({ handle: 1, view: VIEW });
		const applied = await applyDeckOperation(1, { op: 'set_geometry', slide_id: 's1', element_id: 'e1', x: 1, y: 2, w: 3, h: 4 });
		expect(applied).toEqual({ outcome: { outcome: 'applied' }, view: { ...VIEW, can_undo: true } });
		await expect(undoDeck(1)).resolves.toEqual({ changed: true, view: VIEW });
		await expect(redoDeck(1)).resolves.toEqual({ changed: false, view: VIEW });
		await expect(deckToMarkup(1)).resolves.toBe('<deck/>');
		expect([...await deckStateVector(1)]).toEqual([1, 2]);
		expect([...await deckEncodeUpdateSince(1, new Uint8Array([5]))]).toEqual([9, 5]);
		await expect(deckApplyUpdate(1, new Uint8Array([7]))).resolves.toEqual({ view: VIEW });
		await expect(closeDeckDocument(1)).resolves.toBe(true);
		expect(calls).toEqual([
			'open <deck>',
			'apply 1 {"op":"set_geometry","slide_id":"s1","element_id":"e1","x":1,"y":2,"w":3,"h":4}',
			'undo 1', 'redo 1', 'toMarkup 1', 'stateVector 1', 'encode 1 5', 'applyUpdate 1 7', 'close 1',
		]);
		expect(rustDeckDocumentStats.calls - before).toBe(9);
	});

	// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model
	it('answers the core error code, and protocol for malformed requests or internal errors', async () => {
		await expect(code(openDeckDocument('bad'))).resolves.toBe('slides_markup_not_normalised');
		await expect(code(applyDeckOperation(2, { op: 'clear_all_interactive' }))).resolves.toBe('shared_item_unknown_handle');
		await expect(code(undoDeck(0))).resolves.toBe('protocol');
		await expect(code(undoDeck(1.5))).resolves.toBe('protocol');
		await expect(code(deckApplyUpdate(1, new Uint8Array([])))).resolves.toBe('protocol');
		expect(calls).toEqual(['open bad', 'apply 2 {"op":"clear_all_interactive"}', 'applyUpdate 1 ']);
	});

	// contract-test: supporting surface=gui.web assertions=live-collab.core.one-shared-model
	it('refuses non-object operations and frees the table when the unit is disposed', () => {
		const table = new ScriptedTable();
		const handlers = createDeckDocumentHandlers(table);
		const signal = new AbortController().signal;
		expect(() => handlers.apply({ handle: 1, operation: 'x' as never }, signal)).toThrow('protocol');
		expect(() => handlers.encodeUpdateSince({ handle: 1, stateVector: [1] as never }, signal)).toThrow('protocol');
		const channel = new MessageChannel();
		const controller = new AbortController();
		const created = tables.length;
		const dispose = installDeckDocumentUnit({ binding, ports: [channel.port2], generation: null, principal: null, signal: controller.signal });
		const installed = tables[created];
		expect(installed.freed).toBe(false);
		controller.abort();
		expect(installed.freed).toBe(true);
		dispose();
		channel.port1.close();
	});
});

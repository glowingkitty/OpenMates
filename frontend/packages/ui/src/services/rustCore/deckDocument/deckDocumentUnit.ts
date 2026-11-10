/**
 * `deckDocument` namespace installer of the shared Rust core Worker.
 *
 * Each install owns one Rust `DeckDocumentTable` (the open deck replicas of that unit
 * port) and frees it when the port is disposed (unbind, crash recovery or Worker
 * teardown), so replicas never outlive their page connection. Marshalling only: the
 * handlers forward to the table and parse its JSON; every decision is Rust's. A binding
 * refusal answers the core's stable code; a malformed request answers `protocol`.
 */
import { serveUnitPort, UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { UnitInstallContext } from '../host/sharedWorkerProtocol';
import {
	isDeckDocumentBinding,
	type DeckDocumentBinding,
	type DeckDocumentTable,
	type DeckDocumentUnitProtocol,
} from './deckDocumentProtocol';

const CODE = /^[a-z][a-z0-9_]{0,63}$/;

function record(payload: unknown): Record<string, unknown> {
	if (typeof payload !== 'object' || payload === null || Array.isArray(payload)) throw new UnitRefusal('protocol');
	return payload as Record<string, unknown>;
}

function handleOf(payload: unknown): number {
	const handle = record(payload).handle;
	if (typeof handle !== 'number' || !Number.isInteger(handle) || handle < 1 || handle > 0xffff_ffff) throw new UnitRefusal('protocol');
	return handle;
}

function bytesOf(payload: unknown, field: string): Uint8Array {
	const value = record(payload)[field];
	// Tag check instead of `instanceof`: structured clone may hand over another realm's Uint8Array.
	if (Object.prototype.toString.call(value) !== '[object Uint8Array]') throw new UnitRefusal('protocol');
	return value as Uint8Array;
}

function stringOf(payload: unknown, field: string): string {
	const value = record(payload)[field];
	if (typeof value !== 'string') throw new UnitRefusal('protocol');
	return value;
}

/** Runs one table call; the binding throws the core's code string on refusal. */
function call<T>(run: () => T): T {
	try {
		return run();
	} catch (error) {
		throw new UnitRefusal(typeof error === 'string' && CODE.test(error) ? error : 'protocol');
	}
}

export function createDeckDocumentHandlers(table: DeckDocumentTable): UnitHandlers<DeckDocumentUnitProtocol> {
	const json = <T>(run: () => string): T => JSON.parse(call(run)) as T;
	return {
		open: (p) => json(() => table.open(stringOf(p, 'markup'))),
		apply: (p) => {
			const handle = handleOf(p);
			const operation = record(p).operation;
			if (typeof operation !== 'object' || operation === null || Array.isArray(operation)) throw new UnitRefusal('protocol');
			return json(() => table.apply(handle, JSON.stringify(operation)));
		},
		undo: (p) => json(() => table.undo(handleOf(p))),
		redo: (p) => json(() => table.redo(handleOf(p))),
		view: (p) => json(() => table.view(handleOf(p))),
		toMarkup: (p) => call(() => table.toMarkup(handleOf(p))),
		stateVector: (p) => call(() => table.stateVector(handleOf(p))),
		encodeUpdateSince: (p) => call(() => table.encodeUpdateSince(handleOf(p), bytesOf(p, 'stateVector'))),
		applyUpdate: (p) => json(() => table.applyUpdate(handleOf(p), bytesOf(p, 'update'))),
		close: (p) => call(() => table.close(handleOf(p))),
	};
}

export function installDeckDocumentUnit(context: UnitInstallContext): () => void {
	if (context.ports.length !== 1 || !isDeckDocumentBinding(context.binding)) throw new Error('unavailable');
	const binding: DeckDocumentBinding = context.binding;
	const table = new binding.DeckDocumentTable();
	const port = context.ports[0];
	const stop = serveUnitPort<DeckDocumentUnitProtocol>(port, createDeckDocumentHandlers(table));
	let disposed = false;
	const dispose = () => {
		if (disposed) return;
		disposed = true;
		stop();
		port.close();
		table.free();
	};
	context.signal.addEventListener('abort', dispose, { once: true });
	return dispose;
}

/**
 * Page side of the shared Rust core Worker `deckDocument` unit (thin typed client).
 *
 * Opens the namespace lazily, bound to the current generation when one exists (logout
 * then closes the port and the Worker frees every replica) and unbound otherwise. A
 * generation change or Worker crash ends the port; its handles are gone with it, so the
 * editor reopens its deck from markup. Every call holds a registry lease so idle
 * retirement never cuts an in-flight call. No TypeScript fallback: a refusal rejects
 * with a `UnitPortError` whose `code` is the core's stable code (`DeckErrorCode`).
 */
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, type UnitPort, type UnitRequestOptions } from '../host/unitPort';
import type { DeckDocumentUnitProtocol } from './deckDocumentProtocol';
import type { DeckOperation, DeckOutcome, DeckView } from './deckDocumentTypes';

/** Read-only diagnostics (E2E asserts the unit served the flow). */
export const rustDeckDocumentStats = { calls: 0, failures: 0, opens: 0, ops: {} as Record<string, number> };
// Test-only read hook: installed only under browser automation (Playwright sets
// navigator.webdriver), so user sessions never expose it.
if (typeof navigator !== 'undefined' && navigator.webdriver) {
	(globalThis as { __openmatesRustDeckDocumentStats?: () => typeof rustDeckDocumentStats }).__openmatesRustDeckDocumentStats = () => ({
		...rustDeckDocumentStats,
		ops: { ...rustDeckDocumentStats.ops },
	});
}

interface OpenUnit { core: SharedRustCore; port: UnitPort<DeckDocumentUnitProtocol>; generation: number | null }

let unit: OpenUnit | null = null;
let opening: Promise<OpenUnit> | null = null;
let stopCrashWatch: (() => void) | null = null;

async function open(core: SharedRustCore): Promise<OpenUnit> {
	const generation = core.generation;
	const port = createUnitPort<DeckDocumentUnitProtocol>(await core.openUnit('deckDocument', { unbound: generation === null }));
	const opened: OpenUnit = { core, port, generation };
	stopCrashWatch?.();
	stopCrashWatch = core.onCrash(() => {
		port.close();
		if (unit === opened) unit = null;
	});
	unit = opened;
	rustDeckDocumentStats.opens++;
	return opened;
}

function current(core: SharedRustCore): Promise<OpenUnit> {
	if (unit && (unit.port.closed || unit.core !== core || unit.core.generation !== unit.generation)) {
		unit.port.close();
		unit = null;
	}
	if (unit) return Promise.resolve(unit);
	opening ??= open(core).finally(() => { opening = null; });
	return opening;
}

async function deckCall<K extends keyof DeckDocumentUnitProtocol & string>(
	op: K, payload: DeckDocumentUnitProtocol[K]['request'], options?: UnitRequestOptions,
): Promise<DeckDocumentUnitProtocol[K]['response']> {
	const core = await whenSharedRustCore();
	const release = core.hold();
	rustDeckDocumentStats.calls++;
	rustDeckDocumentStats.ops[op] = (rustDeckDocumentStats.ops[op] ?? 0) + 1;
	try {
		return await (await current(core)).port.request(op, payload, options);
	} catch (error) {
		rustDeckDocumentStats.failures++;
		throw error;
	} finally {
		release();
	}
}

/** Hydrates a replica from normalised slides markup. */
export function openDeckDocument(markup: string): Promise<{ handle: number; view: DeckView }> {
	return deckCall('open', { markup });
}

/** Applies one typed operation as one undo step. */
export function applyDeckOperation(handle: number, operation: DeckOperation): Promise<{ outcome: DeckOutcome; view: DeckView }> {
	return deckCall('apply', { handle, operation });
}

export function undoDeck(handle: number): Promise<{ changed: boolean; view: DeckView }> {
	return deckCall('undo', { handle });
}

export function redoDeck(handle: number): Promise<{ changed: boolean; view: DeckView }> {
	return deckCall('redo', { handle });
}

export function deckView(handle: number): Promise<{ view: DeckView }> {
	return deckCall('view', { handle });
}

/** Normalised slides markup to save as the deck's next version. */
export function deckToMarkup(handle: number): Promise<string> {
	return deckCall('toMarkup', { handle });
}

/** Yjs v1 state vector. */
export function deckStateVector(handle: number): Promise<Uint8Array> {
	return deckCall('stateVector', { handle });
}

/** Yjs v1 update with everything the holder of `stateVector` lacks. */
export function deckEncodeUpdateSince(handle: number, stateVector: Uint8Array): Promise<Uint8Array> {
	return deckCall('encodeUpdateSince', { handle, stateVector });
}

/** Applies Yjs v1 update bytes from a peer or the rich-text mirror. */
export function deckApplyUpdate(handle: number, update: Uint8Array): Promise<{ view: DeckView }> {
	return deckCall('applyUpdate', { handle, update });
}

/** Drops the replica; `false` when the handle was not open. */
export function closeDeckDocument(handle: number): Promise<boolean> {
	return deckCall('close', { handle });
}

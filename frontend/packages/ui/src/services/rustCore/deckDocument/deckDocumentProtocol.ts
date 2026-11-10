/**
 * `deckDocument` unit protocol of the shared Rust core Worker (unitPort.ts wire v1).
 *
 * The core's authoritative deck replicas (packages/openmates-rust/src/client/shared_items/
 * deck_handles.rs) live in the Worker, one table per unit port, addressed by numeric
 * handle. The slides editor sends typed operations and renders the returned DeckView;
 * structure, validation, undo/redo, markup and Yjs bytes stay in Rust
 * (live-collab.core.one-shared-model). Refusals carry the core's stable code
 * (`DeckErrorCode`), or `protocol` for a malformed request.
 */
import type { UnitProtocol } from '../host/unitPort';
import type { DeckOperation, DeckOutcome, DeckView } from './deckDocumentTypes';

export interface DeckHandleRequest { handle: number }

export interface DeckDocumentUnitProtocol extends UnitProtocol {
	open: { request: { markup: string }; response: { handle: number; view: DeckView } };
	apply: { request: { handle: number; operation: DeckOperation }; response: { outcome: DeckOutcome; view: DeckView } };
	undo: { request: DeckHandleRequest; response: { changed: boolean; view: DeckView } };
	redo: { request: DeckHandleRequest; response: { changed: boolean; view: DeckView } };
	view: { request: DeckHandleRequest; response: { view: DeckView } };
	toMarkup: { request: DeckHandleRequest; response: string };
	stateVector: { request: DeckHandleRequest; response: Uint8Array };
	encodeUpdateSince: { request: { handle: number; stateVector: Uint8Array }; response: Uint8Array };
	applyUpdate: { request: { handle: number; update: Uint8Array }; response: { view: DeckView } };
	close: { request: DeckHandleRequest; response: boolean };
}

/** One `DeckDocumentTable` instance (browser_deck_document.rs); methods throw the code string. */
export interface DeckDocumentTable {
	open(markup: string): string;
	apply(handle: number, operationJson: string): string;
	undo(handle: number): string;
	redo(handle: number): string;
	view(handle: number): string;
	toMarkup(handle: number): string;
	stateVector(handle: number): Uint8Array;
	encodeUpdateSince(handle: number, stateVector: Uint8Array): Uint8Array;
	applyUpdate(handle: number, update: Uint8Array): string;
	close(handle: number): boolean;
	readonly size: number;
	free(): void;
}

/** Worker module export of browser_deck_document.rs. */
export interface DeckDocumentBinding {
	DeckDocumentTable: new () => DeckDocumentTable;
}

export function isDeckDocumentBinding(value: unknown): value is DeckDocumentBinding {
	if (typeof value !== 'object' || value === null) return false;
	return typeof (value as Record<string, unknown>).DeckDocumentTable === 'function';
}

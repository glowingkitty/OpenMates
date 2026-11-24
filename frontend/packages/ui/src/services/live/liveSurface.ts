/**
 * Read-only helpers for rendering peers on the sheet grid and the slides editor.
 * Display only: the core relays presence; nothing here decides or merges anything.
 */
import type { LivePeer } from './liveItemTypes';

export interface SheetCursor { row_id: string; col_id: string }
export interface DeckCursor { slide_id: string; element_id?: string | null }

/** Name of the assistant when the peer is one ("<mate> is editing here"), else null. */
export function peerMate(peer: LivePeer): string | null {
	return peer.mate_name ?? peer.mate ?? null;
}

function cursorOf(peer: Pick<LivePeer, 'cursor' | 'kind_cursor'>): Record<string, unknown> | null {
	const raw = peer.cursor ?? peer.kind_cursor;
	return raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : null;
}

export function sheetCursor(peer: Pick<LivePeer, 'cursor' | 'kind_cursor'>): SheetCursor | null {
	const c = cursorOf(peer);
	return c && typeof c.row_id === 'string' && typeof c.col_id === 'string' ? { row_id: c.row_id, col_id: c.col_id } : null;
}

export function deckCursor(peer: LivePeer): DeckCursor | null {
	const c = cursorOf(peer);
	if (!c || typeof c.slide_id !== 'string') return null;
	return { slide_id: c.slide_id, element_id: typeof c.element_id === 'string' ? c.element_id : null };
}

/** Spreadsheet column label for a zero-based position (A, B, ... Z, AA). */
export function columnLabel(index: number): string {
	let n = index;
	let out = '';
	do { out = String.fromCharCode(65 + (n % 26)) + out; n = Math.floor(n / 26) - 1; } while (n >= 0);
	return out;
}

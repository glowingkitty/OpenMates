/**
 * Unit protocol of the shared Rust core Worker's `search` namespace
 * (unitPort.ts request/response, one port per page).
 *
 * One `search` request carries the whole query: chats the page dropped
 * (`removes`), chats whose entries changed since they were last sent (`sets`),
 * then the query over `handles` in the page's chat order. The Worker answers
 * with flat `rows` (see packages/openmates-rust/src/web_search_chats.rs):
 *   per matching chat  [position, snippetCount, embedCount]
 *   per snippet        [entry, from, to, flags, snippetMatchStart]   flags: 1 = "... " prefix, 2 = " ..." suffix
 *   per embed          [entry]
 * Rows never carry text; the page slices the snippet out of the entry content
 * it already holds. `clear` drops every chat (logout); `close` also frees the
 * index and ends the unit.
 */
import type { UnitProtocol } from '../host/unitPort';

/** Entries of one chat in index order (column arrays keep the structured clone small). */
export interface SearchChatSet {
	handle: number;
	messageIds: string[];
	contents: string[];
	/** '' for message text. */
	embedIds: string[];
	/** 1 when the entry is an embed with a non-empty title (`embedId && embedTitle`). */
	embedTitled: Uint8Array;
}

export interface SearchRequest {
	removes: number[];
	sets: SearchChatSet[];
	query: string;
	handles: Uint32Array;
	includeEmbeds: boolean;
}

export interface SearchUnitProtocol extends UnitProtocol {
	search: { request: SearchRequest; response: { rows: Uint32Array } };
	clear: { request: Record<string, never>; response: { chats: number } };
	/** Frees the index and closes the unit after replying (the page reopens under a new generation). */
	close: { request: Record<string, never>; response: { chats: number } };
}

export const SEARCH_HEADER_WORDS = 3;
export const SEARCH_SNIPPET_WORDS = 5;
export const SEARCH_FLAG_FRONT_ELLIPSIS = 1;
export const SEARCH_FLAG_BACK_ELLIPSIS = 2;

function isStringArray(value: unknown, length: number): value is string[] {
	return Array.isArray(value) && value.length === length && value.every((item) => typeof item === 'string');
}
/** Tag check instead of `instanceof`, which fails for typed arrays cloned from another realm. */
function isTyped(value: unknown, tag: 'Uint8Array' | 'Uint32Array'): boolean {
	return ArrayBuffer.isView(value) && Object.prototype.toString.call(value) === `[object ${tag}]`;
}
function isHandle(value: unknown): value is number {
	return typeof value === 'number' && Number.isInteger(value) && value > 0 && value <= 0xffffffff;
}

/** Worker-side strict validation; anything else is refused as `protocol`. */
export function isSearchChatSet(value: unknown): value is SearchChatSet {
	if (typeof value !== 'object' || value === null) return false;
	const set = value as Record<string, unknown>;
	if (!isHandle(set.handle) || !Array.isArray(set.messageIds) || !isTyped(set.embedTitled, 'Uint8Array')) return false;
	const length = set.messageIds.length;
	return isStringArray(set.messageIds, length) && isStringArray(set.contents, length) && isStringArray(set.embedIds, length)
		&& (set.embedTitled as Uint8Array).length === length;
}

export function isSearchRequest(value: unknown): value is SearchRequest {
	if (typeof value !== 'object' || value === null) return false;
	const request = value as Record<string, unknown>;
	return Array.isArray(request.removes) && request.removes.every(isHandle)
		&& Array.isArray(request.sets) && request.sets.every(isSearchChatSet)
		&& typeof request.query === 'string' && isTyped(request.handles, 'Uint32Array')
		&& typeof request.includeEmbeds === 'boolean';
}

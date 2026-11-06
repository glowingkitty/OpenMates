/**
 * Unit protocol of the shared Rust core Worker's `search` namespace
 * (unitPort.ts request/response, one port per page).
 *
 * The Worker owns the chat message index; the page keeps no copy.
 * - `ingest` transfers ONE chat's freshly built entries (column arrays) once per
 *   (re)index and returns the handles the index budget evicted.
 * - `query` carries one complete search: the page's per-chat metadata in chat
 *   order plus the translated settings/app catalogs; the Worker answers with flat
 *   rows + a text table (layout: packages/openmates-rust/src/web_search_query.rs
 *   `EncodedOutcome`), decoded on the page by rustChatSearch.ts.
 * Both requests first drop the chats in `removes` (page invalidations).
 * `clear` drops every chat (logout); `close` also frees the index and ends the unit.
 */
import type { UnitProtocol } from '../host/unitPort';

/** Optional entry fields in wire order (bit i of a meta mask = field i present). */
export const META_FIELDS = [
	'embedSourceLabel', 'embedId', 'embedType', 'embedTitle', 'embedSubtitle',
	'embedAppId', 'embedSkillId', 'embedFocusId', 'embedFocusModeName',
] as const;

/** One chat's entries in any order (the Worker sorts newest first). */
export interface SearchIngestChat {
	handle: number;
	messageIds: string[];
	contents: string[];
	createdAt: Float64Array;
	/** Entries that carry embed fields, with their field mask and present values in order. */
	metaEntries: Uint32Array;
	metaMasks: Uint16Array;
	metaValues: string[];
}

/** Query flags. */
export const QUERY_FLAG_INCLUDE_EMBEDS = 1;
export const QUERY_FLAG_AUTHENTICATED = 2;
export const QUERY_FLAG_ADMIN = 4;
/** Chat mask bits; present values follow in this order, tags last (`tagCounts`). */
export const CHAT_TITLE = 1;
export const CHAT_FOCUS = 2;
export const CHAT_SUMMARY = 4;
export const CHAT_DRAFT = 8;
export const CHAT_TAGS = 16;
/** Catalog flags: bits 0-1 access, bit 2 app catalog entry. */
export const CATALOG_ACCESS = { public: 0, authenticated: 1, admin: 2 } as const;
export const CATALOG_APP = 4;

export interface SearchQueryRequest {
	removes: number[];
	query: string;
	flags: number;
	/** Per chat; 0 = no message search (metadata-only or not indexed). */
	handles: Uint32Array;
	chatMasks: Uint8Array;
	chatValues: string[];
	tagCounts: Uint32Array;
	lastEdited: Float64Array;
	catalogFlags: Uint8Array;
	catalogLabels: string[];
	catalogKeywordCounts: Uint32Array;
	catalogKeywords: string[];
}

export interface SearchQueryReply { rows: Uint32Array; texts: string[]; numbers: Float64Array }

export interface SearchUnitProtocol extends UnitProtocol {
	ingest: { request: { removes: number[]; chat: SearchIngestChat }; response: { evicted: Uint32Array } };
	query: { request: SearchQueryRequest; response: SearchQueryReply };
	clear: { request: Record<string, never>; response: { chats: number } };
	/** Frees the index and closes the unit after replying (the page reopens under a new generation). */
	close: { request: Record<string, never>; response: { chats: number } };
}

/** Rows layout constants (web_search_query.rs). */
export const NO_TEXT = 0xffffffff;
export const MESSAGE_SNIPPET_WORDS = 12;
export const METADATA_SNIPPET_WORDS = 4;
export const EMBED_WORDS = 7;
export const FOCUS_ACTIVE = 1;
export const FOCUS_NONE = 2;

function isStringArray(value: unknown, length?: number): value is string[] {
	return Array.isArray(value) && (length === undefined || value.length === length) && value.every((item) => typeof item === 'string');
}
type TypedTag = 'Uint8Array' | 'Uint16Array' | 'Uint32Array' | 'Float64Array';
/** Tag check instead of `instanceof`, which fails for typed arrays cloned from another realm. */
function isTyped(value: unknown, tag: TypedTag, length?: number): boolean {
	return ArrayBuffer.isView(value) && Object.prototype.toString.call(value) === `[object ${tag}]`
		&& (length === undefined || (value as unknown as ArrayLike<number>).length === length);
}
function isHandle(value: unknown): value is number {
	return typeof value === 'number' && Number.isInteger(value) && value > 0 && value <= 0xffffffff;
}
function isRemoves(value: unknown): value is number[] {
	return Array.isArray(value) && value.every(isHandle);
}

/** Worker-side shape validation; anything else is refused as `protocol` (Rust re-checks the column contract). */
export function isIngestRequest(value: unknown): value is SearchUnitProtocol['ingest']['request'] {
	if (typeof value !== 'object' || value === null) return false;
	const { removes, chat } = value as Record<string, unknown>;
	if (!isRemoves(removes) || typeof chat !== 'object' || chat === null) return false;
	const set = chat as Record<string, unknown>;
	if (!isHandle(set.handle) || !Array.isArray(set.messageIds)) return false;
	const length = set.messageIds.length;
	return isStringArray(set.messageIds, length) && isStringArray(set.contents, length) && isTyped(set.createdAt, 'Float64Array', length)
		&& isTyped(set.metaEntries, 'Uint32Array') && isTyped(set.metaMasks, 'Uint16Array') && isStringArray(set.metaValues);
}

export function isQueryRequest(value: unknown): value is SearchQueryRequest {
	if (typeof value !== 'object' || value === null) return false;
	const request = value as Record<string, unknown>;
	return isRemoves(request.removes) && typeof request.query === 'string' && typeof request.flags === 'number'
		&& isTyped(request.handles, 'Uint32Array') && isTyped(request.chatMasks, 'Uint8Array') && isStringArray(request.chatValues)
		&& isTyped(request.tagCounts, 'Uint32Array') && isTyped(request.lastEdited, 'Float64Array')
		&& isTyped(request.catalogFlags, 'Uint8Array') && isStringArray(request.catalogLabels)
		&& isTyped(request.catalogKeywordCounts, 'Uint32Array') && isStringArray(request.catalogKeywords);
}

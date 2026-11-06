/**
 * Page side of the shared Rust core Worker's `search` unit (Rust-core builds
 * only; searchService.ts reaches it through a flag-guarded dynamic import, so
 * default builds never bundle it).
 *
 * The page keeps building the decrypted index exactly as before (it is the
 * ingest source and the measurement baseline). Each chat's entries cross to the
 * Worker once per index version; a query then crosses as text plus chat
 * handles in ONE request, and only flat `Uint32Array` rows come back. Snippet
 * strings are rebuilt here from the Rust slice plan over the entry content
 * the page already holds, so no text crosses back and nothing is JSON parsed.
 *
 * Failures are not hidden: a refused open, a crashed Worker or a unit error
 * rejects the search (Chats.svelte reports it); the next search reopens the
 * unit and resends the index. There is no TypeScript fallback.
 */
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, UnitPortError, type UnitPort } from '../host/unitPort';
import type { EmbedSearchResult, MessageMatchSnippet } from '../../searchService';
import {
	SEARCH_FLAG_BACK_ELLIPSIS,
	SEARCH_FLAG_FRONT_ELLIPSIS,
	SEARCH_HEADER_WORDS,
	SEARCH_SNIPPET_WORDS,
	type SearchChatSet,
	type SearchUnitProtocol,
} from './searchUnitProtocol';

/** Measurement-only opt-out (`'ts'`): the paired bench runs the TypeScript search in the same build. */
export const SEARCH_OPT_OUT_KEY = 'openmates_rust_core_search';
const OPEN_TIMEOUT_MS = 10_000;

/** The fields of a searchService index entry this adapter reads. */
export interface RustSearchEntry {
	messageId: string;
	content: string;
	createdAt: number;
	embedSourceLabel?: string;
	embedId?: string;
	embedType?: string;
	embedTitle?: string;
	embedSubtitle?: string;
	embedAppId?: string;
	embedSkillId?: string;
	embedFocusId?: string;
	embedFocusModeName?: string;
}

export interface RustSearchChat { chatId: string; entries: readonly RustSearchEntry[] | undefined }

export interface RustMessageHits {
	/** The chat's matches in `searchMessagesInChat` shape; empty for chats without hits. */
	take(chatId: string, activeFocusId: string | null): { snippets: MessageMatchSnippet[]; embeds: EmbedSearchResult[] };
}

interface Sent { handle: number; entries: readonly RustSearchEntry[] }
interface Unit { core: SharedRustCore; port: UnitPort<SearchUnitProtocol>; generation: number | null; stopCrashWatch: () => void }

let unit: Unit | null = null;
let opening: Promise<Unit> | null = null;
const sent = new Map<string, Sent>();
let nextHandle = 1;
let served = 0;

export function rustChatSearchSelected(): boolean {
	return typeof localStorage === 'undefined' || localStorage.getItem(SEARCH_OPT_OUT_KEY) !== 'ts';
}

/**
 * Forgets `current` (and what was sent to it). With `freeRemote` the unit is
 * first told to free its index; the page port closes right after, so that
 * request's own `unit_closed` rejection is expected and anything else is logged.
 */
function dropUnit(current: Unit, freeRemote = false): void {
	if (unit === current) {
		unit = null;
		sent.clear();
	}
	current.stopCrashWatch();
	if (freeRemote && !current.port.closed) {
		current.port.request('close', {}).catch((error: unknown) => {
			if (error instanceof UnitPortError && error.code === 'unit_closed') return;
			console.warn('[RustSearch] freeing the search unit failed:', error instanceof Error ? error.message : 'unknown');
		});
	}
	current.port.close();
}

async function openUnit(): Promise<Unit> {
	const core = await whenSharedRustCore({ timeoutMs: OPEN_TIMEOUT_MS });
	const generation = core.generation;
	const raw = await core.openUnit('search', { unbound: generation === null });
	const opened: Unit = { core, port: createUnitPort<SearchUnitProtocol>(raw), generation, stopCrashWatch: () => undefined };
	opened.stopCrashWatch = core.onCrash(() => dropUnit(opened));
	sent.clear();
	return opened;
}

/**
 * Opens (or reuses) the Worker search unit ahead of the first query, so the
 * unit's Worker-side load overlaps the page's index gathering. Callers await the
 * returned promise; a failure rejects exactly like the search itself would.
 */
export async function prepareRustChatSearch(): Promise<void> {
	await currentUnit();
}

/** The open unit for the current generation; a generation change reopens it (the old index is freed). */
async function currentUnit(): Promise<Unit> {
	if (unit && unit.core.generation !== unit.generation) dropUnit(unit, true);
	if (unit) return unit;
	opening ??= openUnit().finally(() => { opening = null; });
	const opened = await opening;
	unit ??= opened;
	return unit;
}

function columns(handle: number, entries: readonly RustSearchEntry[]): SearchChatSet {
	const length = entries.length;
	const set: SearchChatSet = { handle, messageIds: new Array(length), contents: new Array(length), embedIds: new Array(length), embedTitled: new Uint8Array(length) };
	for (let index = 0; index < length; index++) {
		const entry = entries[index];
		set.messageIds[index] = entry.messageId;
		set.contents[index] = entry.content;
		set.embedIds[index] = entry.embedId || '';
		set.embedTitled[index] = entry.embedId && entry.embedTitle ? 1 : 0;
	}
	return set;
}

interface ChatHits { chatId: string; entries: readonly RustSearchEntry[]; snippets: number[]; embeds: number[] }

/** Decodes Worker rows against the entry snapshots that were searched (exported for unit tests). */
export function decodeSearchRows(rows: Uint32Array, chats: readonly { chatId: string; entries: readonly RustSearchEntry[] }[]): Map<string, ChatHits> {
	const out = new Map<string, ChatHits>();
	let at = 0;
	while (at < rows.length) {
		const chat = chats[rows[at]];
		const snippetCount = rows[at + 1];
		const embedCount = rows[at + 2];
		const end = at + SEARCH_HEADER_WORDS + snippetCount * SEARCH_SNIPPET_WORDS + embedCount;
		if (!chat || end > rows.length) throw new Error('rust_search_bad_rows');
		const snippets = Array.from(rows.subarray(at + SEARCH_HEADER_WORDS, at + SEARCH_HEADER_WORDS + snippetCount * SEARCH_SNIPPET_WORDS));
		const embeds = Array.from(rows.subarray(end - embedCount, end));
		out.set(chat.chatId, { chatId: chat.chatId, entries: chat.entries, snippets, embeds });
		at = end;
	}
	return out;
}

/** Builds `searchMessagesInChat` results from decoded rows (exported for unit tests). */
export function materializeHits(hits: ChatHits | undefined, matchLength: number, activeFocusId: string | null) {
	const snippets: MessageMatchSnippet[] = [];
	const embeds: EmbedSearchResult[] = [];
	if (!hits) return { snippets, embeds };
	for (let at = 0; at < hits.snippets.length; at += SEARCH_SNIPPET_WORDS) {
		const entry = hits.entries[hits.snippets[at]];
		const flags = hits.snippets[at + 3];
		if (!entry) throw new Error('rust_search_bad_rows');
		const body = entry.content.slice(hits.snippets[at + 1], hits.snippets[at + 2]);
		snippets.push({
			messageId: entry.messageId,
			chatId: hits.chatId,
			snippet: (flags & SEARCH_FLAG_FRONT_ELLIPSIS ? '... ' : '') + body + (flags & SEARCH_FLAG_BACK_ELLIPSIS ? ' ...' : ''),
			matchStart: hits.snippets[at + 4],
			matchLength,
			embedSourceLabel: entry.embedSourceLabel,
			embedId: entry.embedId,
			embedType: entry.embedType,
			embedAppId: entry.embedAppId,
			embedSkillId: entry.embedSkillId,
			embedFocusId: entry.embedFocusId,
			embedFocusModeName: entry.embedFocusModeName,
			embedFocusIsActive: entry.embedType === 'focus-mode-activation' && entry.embedFocusId ? entry.embedFocusId === activeFocusId : undefined,
		});
	}
	for (const index of hits.embeds) {
		const entry = hits.entries[index];
		if (!entry?.embedId || !entry.embedTitle) throw new Error('rust_search_bad_rows');
		embeds.push({
			embedId: entry.embedId,
			embedType: entry.embedType || '',
			chatId: hits.chatId,
			messageId: entry.messageId,
			title: entry.embedTitle,
			subtitle: entry.embedSubtitle || entry.embedSourceLabel || 'Embed',
			appId: entry.embedAppId,
			createdAt: entry.createdAt,
		});
	}
	return { snippets, embeds };
}

/**
 * One Worker query for every chat in `chats` (chats without an index entry
 * have no message hits, as in `searchMessagesInChat`). `isIndexed` tells which
 * previously sent chats the page still indexes; the rest are dropped.
 */
export async function searchRustChatMessages(
	query: string,
	chats: readonly RustSearchChat[],
	includeEmbeds: boolean,
	isIndexed: (chatId: string) => boolean,
	signal?: AbortSignal,
): Promise<RustMessageHits> {
	const target = await currentUnit();
	signal?.throwIfAborted();
	const removes: number[] = [];
	for (const [chatId, entry] of sent) {
		if (isIndexed(chatId)) continue;
		removes.push(entry.handle);
		sent.delete(chatId);
	}
	const searched: { chatId: string; entries: readonly RustSearchEntry[] }[] = [];
	const sets: SearchChatSet[] = [];
	for (const chat of chats) {
		if (!chat.entries) continue;
		let known = sent.get(chat.chatId);
		if (!known || known.entries !== chat.entries) {
			known = { handle: known?.handle ?? nextHandle++, entries: chat.entries };
			sent.set(chat.chatId, known);
			sets.push(columns(known.handle, chat.entries));
		}
		searched.push({ chatId: chat.chatId, entries: chat.entries });
	}
	const handles = new Uint32Array(searched.length);
	for (let index = 0; index < searched.length; index++) handles[index] = sent.get(searched[index].chatId)!.handle;
	performance.mark('openmates:rust:search-start');
	let rows: Uint32Array;
	try {
		({ rows } = await target.port.request('search', { removes, sets, query, handles, includeEmbeds }, { signal, transfer: [handles.buffer] }));
	} catch (error) {
		// An abort only drops the reply: the unit still applies the request in port order.
		// Any other failure leaves its state unknown, so the next search reopens and resends.
		if (!(error instanceof UnitPortError && error.code === 'unit_aborted')) dropUnit(target);
		throw error;
	}
	const decoded = decodeSearchRows(rows, searched);
	served += 1;
	performance.measure('openmates:rust:search', 'openmates:rust:search-start');
	if (typeof document !== 'undefined') document.documentElement.dataset.rustCoreSearch = `rust:${served}`;
	return { take: (chatId, activeFocusId) => materializeHits(decoded.get(chatId), query.length, activeFocusId) };
}

/** Logout: drop the Worker index and the page's record of what was sent. */
export function clearRustChatSearch(): void {
	sent.clear();
	if (unit) dropUnit(unit, true);
}

if (typeof window !== 'undefined') window.addEventListener('userLoggingOut', clearRustChatSearch);

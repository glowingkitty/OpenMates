/**
 * Page side of the shared Rust core Worker's `search` unit (searchService.ts
 * reaches it through a dynamic import, so
 * default builds never bundle it).
 *
 * The Worker owns the chat message index. searchService.ts builds a chat's
 * entries from its source (decrypted IndexedDB rows, or in-memory public
 * chats) and `ingestRustChat` transfers them once; the page keeps only
 * chatId -> handle. A query sends the page's per-chat metadata and the
 * translated catalogs; the Worker returns flat rows that `decodeSearchReply`
 * turns into searchService result objects.
 *
 * Crash recovery: a crashed Worker (or a generation change) drops the unit and
 * every handle, so the next search re-indexes each chat from its source, never
 * from a page copy. Failures are not hidden: a refused open, a crash or a unit
 * error rejects the search (Chats.svelte reports it). There is no TypeScript
 * fallback; the TS opt-out below is measurement-only.
 */
import { whenSharedRustCore, type SharedRustCore } from '../host/sharedCoreRegistry';
import { createUnitPort, UnitPortError, type UnitPort } from '../host/unitPort';
import type { EmbedSearchResult, MessageMatchSnippet, MetadataMatchSnippet } from '../../searchService';
import {
	CATALOG_ACCESS, CATALOG_APP, CHAT_DRAFT, CHAT_FOCUS, CHAT_SUMMARY, CHAT_TAGS, CHAT_TITLE, EMBED_WORDS, FOCUS_ACTIVE, FOCUS_NONE,
	MESSAGE_SNIPPET_WORDS, META_FIELDS, METADATA_SNIPPET_WORDS, NO_TEXT, QUERY_FLAG_ADMIN, QUERY_FLAG_AUTHENTICATED, QUERY_FLAG_INCLUDE_EMBEDS,
	type SearchIngestChat, type SearchQueryReply, type SearchQueryRequest, type SearchUnitProtocol,
} from './searchUnitProtocol';

const OPEN_TIMEOUT_MS = 10_000;

/** The fields of a searchService index entry the Worker index stores. */
export type RustSearchEntry = {
	messageId: string;
	content: string;
	createdAt: number;
} & { [K in (typeof META_FIELDS)[number]]?: string };

/** Page data of one searchable chat (searchService.ts resolves it like the TS loop). */
export interface RustQueryChat {
	chatId: string;
	/** Search messages (false for metadata-only chats). */
	messages: boolean;
	title: string | null;
	activeFocusId: string | null;
	summary: string | null;
	tags: string[] | null;
	draft: string | null;
	lastEdited: number;
}

export interface RustCatalogEntry { label: string; keywords: readonly string[]; access?: 'public' | 'authenticated' | 'admin' }

export interface RustQueryInput {
	query: string;
	includeEmbeds: boolean;
	isAuthenticated: boolean;
	isAdmin: boolean;
	chats: readonly RustQueryChat[];
	settings: readonly RustCatalogEntry[];
	apps: readonly RustCatalogEntry[];
}

export interface RustChatHit {
	position: number;
	titleMatchRanges: Array<{ start: number; length: number }>;
	messageSnippets: MessageMatchSnippet[];
	metadataSnippets: MetadataMatchSnippet[];
}

export interface RustSearchResult {
	/** In display order. */
	chats: RustChatHit[];
	embeds: EmbedSearchResult[];
	/** Indices into `settings` / `apps` of the request. */
	settings: number[];
	apps: number[];
}

interface Unit { core: SharedRustCore; port: UnitPort<SearchUnitProtocol>; generation: number | null; stopCrashWatch: () => void }

let unit: Unit | null = null;
let opening: Promise<Unit> | null = null;
const indexed = new Map<string, number>();
const chatOfHandle = new Map<number, string>();
const epochs = new Map<string, number>();
let removes: number[] = [];
let nextHandle = 1;
let served = 0;

/** Whether the Worker index currently holds `chatId`. */
export function isRustChatIndexed(chatId: string): boolean {
	return indexed.has(chatId);
}

/** Invalidation counter of `chatId`; an ingest built before a later invalidation is discarded. */
export function rustChatEpoch(chatId: string): number {
	return epochs.get(chatId) ?? 0;
}

function forget(chatId: string): void {
	const handle = indexed.get(chatId);
	if (handle === undefined) return;
	indexed.delete(chatId);
	chatOfHandle.delete(handle);
	removes.push(handle);
}

/** The chat's messages changed: the Worker drops it with the next request; the next search re-indexes it. */
export function invalidateRustChat(chatId: string): void {
	epochs.set(chatId, rustChatEpoch(chatId) + 1);
	forget(chatId);
}

/** Forgets `current`; a crashed or replaced unit took its index with it, so every handle is dropped. */
function dropUnit(current: Unit, freeRemote = false): void {
	if (unit === current) {
		unit = null;
		indexed.clear();
		chatOfHandle.clear();
		removes = [];
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
	return opened;
}

/** Opens (or reuses) the Worker search unit, so its load overlaps the page's metadata and index work. */
export async function prepareRustChatSearch(): Promise<void> {
	await currentUnit();
}

/** The open unit for the current generation; a generation change reopens it (the old index is freed). */
async function currentUnit(): Promise<Unit> {
	if (unit && unit.core.generation !== unit.generation) dropUnit(unit, true);
	if (unit) return unit;
	opening ??= openUnit().finally(() => { opening = null; });
	const opened = await opening;
	if (!unit) {
		unit = opened;
		indexed.clear();
		chatOfHandle.clear();
		removes = [];
	}
	return unit;
}

/** Runs one request; any failure but an abort leaves the unit state unknown, so it is dropped. */
async function send<K extends 'ingest' | 'query'>(target: Unit, op: K, payload: SearchUnitProtocol[K]['request'], options: { signal?: AbortSignal; transfer: Transferable[] }) {
	try {
		return await target.port.request(op, payload, options);
	} catch (error) {
		// An abort only drops the reply: the unit still applies the request in port order.
		if (!(error instanceof UnitPortError && error.code === 'unit_aborted')) dropUnit(target);
		throw error;
	}
}

function takeRemoves(): number[] {
	const taken = removes;
	removes = [];
	return taken;
}

/** Column form of one chat's entries (exported for unit tests). */
export function ingestColumns(handle: number, entries: readonly RustSearchEntry[]): SearchIngestChat {
	const length = entries.length;
	const messageIds: string[] = new Array(length);
	const contents: string[] = new Array(length);
	const createdAt = new Float64Array(length);
	const metaEntries: number[] = [];
	const metaMasks: number[] = [];
	const metaValues: string[] = [];
	for (let index = 0; index < length; index++) {
		const entry = entries[index];
		messageIds[index] = entry.messageId;
		contents[index] = entry.content;
		createdAt[index] = entry.createdAt;
		let mask = 0;
		for (let field = 0; field < META_FIELDS.length; field++) {
			const value = entry[META_FIELDS[field]];
			if (value === undefined) continue;
			mask |= 1 << field;
			metaValues.push(value);
		}
		if (mask !== 0) {
			metaEntries.push(index);
			metaMasks.push(mask);
		}
	}
	return { handle, messageIds, contents, createdAt, metaEntries: Uint32Array.from(metaEntries), metaMasks: Uint16Array.from(metaMasks), metaValues };
}

/** Replies of ingests posted but not yet answered; `settleRustIngests` waits for them. */
const inflightIngests = new Set<Promise<void>>();
let ingestFailure: unknown = null;

/** Records one search phase as a performance measure (read by the paired bench; no behavior). */
function recordPhase(name: string, start: number, end: number, detail: Record<string, number>): void {
	performance.measure(`openmates:rust:search:${name}`, { start, end, detail });
}

/**
 * Posts `chatId`'s freshly built entries to the Worker index (the page keeps no
 * copy) and returns once the request is on the port, not when the Worker has
 * answered: the next chat's page-side build overlaps the Worker's ingest instead
 * of waiting a round trip per warm-up batch. Requests on one port are served in
 * order, so a later query always sees the ingest; `queryRustSearch` still settles
 * every reply first, so budget evictions are known before it names handles.
 * Skipped when the chat was invalidated after `epoch` was read.
 */
export async function ingestRustChat(chatId: string, entries: readonly RustSearchEntry[], epoch: number): Promise<void> {
	if (rustChatEpoch(chatId) !== epoch) return;
	const target = await currentUnit();
	if (rustChatEpoch(chatId) !== epoch) return;
	forget(chatId);
	const handle = nextHandle++;
	const started = performance.now();
	const chat = ingestColumns(handle, entries);
	const posted = performance.now();
	indexed.set(chatId, handle);
	chatOfHandle.set(handle, chatId);
	const reply = send(target, 'ingest', { removes: takeRemoves(), chat }, { transfer: [chat.createdAt.buffer, chat.metaEntries.buffer, chat.metaMasks.buffer] })
		.then(({ evicted, workerMs }) => {
			recordPhase('ingest', started, performance.now(), { entries: entries.length, columnsMs: posted - started, workerMs: workerMs ?? 0 });
			if (unit !== target) return;
			for (const gone of evicted) {
				const evictedChat = chatOfHandle.get(gone);
				if (evictedChat !== undefined) { indexed.delete(evictedChat); chatOfHandle.delete(gone); }
			}
		})
		.catch((error: unknown) => {
			ingestFailure ??= error;
			console.warn('[RustSearch] indexing a chat in the search unit failed:', error instanceof Error ? error.message : 'unknown');
		})
		.finally(() => { inflightIngests.delete(reply); });
	inflightIngests.add(reply);
}

/** Waits for every posted ingest and rethrows the first ingest failure (the search must not run on an unknown index). */
export async function settleRustIngests(): Promise<void> {
	while (inflightIngests.size > 0) await Promise.all([...inflightIngests]);
	if (ingestFailure !== null) {
		const failure = ingestFailure;
		ingestFailure = null;
		throw failure;
	}
}

/** Request columns of one search (exported for unit tests). */
export function queryColumns(input: RustQueryInput, handleOf: (chatId: string) => number): Omit<SearchQueryRequest, 'removes'> {
	const count = input.chats.length;
	const handles = new Uint32Array(count);
	const chatMasks = new Uint8Array(count);
	const tagCounts = new Uint32Array(count);
	const lastEdited = new Float64Array(count);
	const chatValues: string[] = [];
	for (let index = 0; index < count; index++) {
		const chat = input.chats[index];
		handles[index] = chat.messages ? handleOf(chat.chatId) : 0;
		lastEdited[index] = chat.lastEdited;
		let mask = 0;
		const add = (bit: number, value: string | null) => {
			if (value === null) return;
			mask |= bit;
			chatValues.push(value);
		};
		add(CHAT_TITLE, chat.title);
		add(CHAT_FOCUS, chat.activeFocusId);
		add(CHAT_SUMMARY, chat.summary);
		add(CHAT_DRAFT, chat.draft);
		if (chat.tags) {
			mask |= CHAT_TAGS;
			tagCounts[index] = chat.tags.length;
			for (const tag of chat.tags) chatValues.push(tag);
		}
		chatMasks[index] = mask;
	}
	const catalog = [...input.settings, ...input.apps];
	const catalogFlags = new Uint8Array(catalog.length);
	const catalogKeywordCounts = new Uint32Array(catalog.length);
	const catalogLabels: string[] = new Array(catalog.length);
	const catalogKeywords: string[] = [];
	for (let index = 0; index < catalog.length; index++) {
		const entry = catalog[index];
		catalogFlags[index] = CATALOG_ACCESS[entry.access ?? 'public'] | (index >= input.settings.length ? CATALOG_APP : 0);
		catalogLabels[index] = entry.label;
		catalogKeywordCounts[index] = entry.keywords.length;
		for (const keyword of entry.keywords) catalogKeywords.push(keyword);
	}
	const flags = (input.includeEmbeds ? QUERY_FLAG_INCLUDE_EMBEDS : 0) | (input.isAuthenticated ? QUERY_FLAG_AUTHENTICATED : 0) | (input.isAdmin ? QUERY_FLAG_ADMIN : 0);
	return { query: input.query, flags, handles, chatMasks, chatValues, tagCounts, lastEdited, catalogFlags, catalogLabels, catalogKeywordCounts, catalogKeywords };
}

const METADATA_SOURCES = ['summary', 'tags', 'draft'] as const;

/** Decodes Worker rows (web_search_query.rs `EncodedOutcome`) into result objects (exported for unit tests). */
export function decodeSearchReply(reply: SearchQueryReply, chatIds: readonly string[], settingsCount: number): RustSearchResult {
	const { rows, texts, numbers } = reply;
	const bad = (): never => { throw new Error('rust_search_bad_rows'); };
	let at = 0;
	const word = () => (at < rows.length ? rows[at++] : bad());
	const text = () => { const cell = word(); return cell === NO_TEXT ? undefined : texts[cell] ?? bad(); };
	const required = () => text() ?? bad();
	const [chatCount, embedCount, settingsHits, appHits] = [word(), word(), word(), word()];
	const result: RustSearchResult = { chats: [], embeds: [], settings: [], apps: [] };
	for (let chat = 0; chat < chatCount; chat++) {
		const position = word();
		const chatId = chatIds[position] ?? bad();
		const [ranges, messages, metadata] = [word(), word(), word()];
		if (at + ranges * 2 + messages * MESSAGE_SNIPPET_WORDS + metadata * METADATA_SNIPPET_WORDS > rows.length) bad();
		const hit: RustChatHit = { position, titleMatchRanges: [], messageSnippets: [], metadataSnippets: [] };
		for (let range = 0; range < ranges; range++) hit.titleMatchRanges.push({ start: word(), length: word() });
		for (let snippet = 0; snippet < messages; snippet++) {
			const body = required();
			const matchStart = word();
			const matchLength = word();
			const messageId = required();
			const [embedSourceLabel, embedId, embedType, embedAppId, embedSkillId, embedFocusId, embedFocusModeName] = [text(), text(), text(), text(), text(), text(), text()];
			const focus = word();
			hit.messageSnippets.push({
				messageId, chatId, snippet: body, matchStart, matchLength,
				embedSourceLabel, embedId, embedType, embedAppId, embedSkillId, embedFocusId, embedFocusModeName,
				embedFocusIsActive: focus === FOCUS_NONE ? undefined : focus === FOCUS_ACTIVE,
			});
		}
		for (let snippet = 0; snippet < metadata; snippet++) {
			const body = required();
			const matchStart = word();
			const matchLength = word();
			const matchSource = METADATA_SOURCES[word()] ?? bad();
			hit.metadataSnippets.push({ chatId, snippet: body, matchStart, matchLength, matchSource });
		}
		result.chats.push(hit);
	}
	if (numbers.length !== embedCount) bad();
	for (let embed = 0; embed < embedCount; embed++) {
		if (at + EMBED_WORDS > rows.length) bad();
		const chatId = chatIds[word()] ?? bad();
		const [embedId, embedType, messageId, title, subtitle] = [required(), text() ?? bad(), required(), required(), required()];
		const appId = text();
		result.embeds.push({ embedId, embedType, chatId, messageId, title, subtitle, appId, createdAt: numbers[embed] });
	}
	for (let hit = 0; hit < settingsHits; hit++) result.settings.push(word());
	for (let hit = 0; hit < appHits; hit++) result.apps.push(word() - settingsCount);
	if (at !== rows.length) bad();
	return result;
}

/** One complete search in the Worker; chats not indexed (yet) get no message hits. */
export async function queryRustSearch(input: RustQueryInput, signal?: AbortSignal): Promise<RustSearchResult> {
	const target = await currentUnit();
	signal?.throwIfAborted();
	await settleRustIngests();
	signal?.throwIfAborted();
	const columnsStart = performance.now();
	const columns = queryColumns(input, (chatId) => indexed.get(chatId) ?? 0);
	performance.mark('openmates:rust:search-start');
	const sent = performance.now();
	const reply = await send(target, 'query', { removes: takeRemoves(), ...columns }, {
		signal,
		transfer: [columns.handles.buffer, columns.chatMasks.buffer, columns.tagCounts.buffer, columns.lastEdited.buffer, columns.catalogFlags.buffer, columns.catalogKeywordCounts.buffer],
	});
	const replied = performance.now();
	const decoded = decodeSearchReply(reply, input.chats.map((chat) => chat.chatId), input.settings.length);
	recordPhase('query', columnsStart, performance.now(), { columnsMs: sent - columnsStart, roundTripMs: replied - sent, workerMs: reply.workerMs ?? 0, decodeMs: performance.now() - replied, chats: input.chats.length });
	served += 1;
	performance.measure('openmates:rust:search', 'openmates:rust:search-start');
	if (typeof document !== 'undefined') document.documentElement.dataset.rustCoreSearch = `rust:${served}`;
	return decoded;
}

/** Logout: drop the Worker index and the page's handles. */
export function clearRustChatSearch(): void {
	epochs.clear();
	ingestFailure = null;
	if (unit) dropUnit(unit, true);
	indexed.clear();
	chatOfHandle.clear();
	removes = [];
}

if (typeof window !== 'undefined') window.addEventListener('userLoggingOut', clearRustChatSearch);

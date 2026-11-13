/**
 * Which version of an image embed a chat message shows, and that version's
 * content (`images-generate.revision.message-shows-its-version`; wire contract
 * "How a client reads version K of an image"). VITE_OPENMATES_RUST_CORE builds
 * only: in other builds every function answers "no version scope" and cards
 * render the stored head exactly as before.
 *
 * The rule itself (latest `pinned_embeds` entry up to the message, else 1,
 * then the user-made versions after it until the next assistant-made one;
 * head vs `embed_diffs` snapshot; parent key) runs in the Rust core through the
 * Worker's `embedWrite` unit. This module is shell glue only:
 *   - ChatHistory publishes the chat's message order (`publishChatMessageOrder`);
 *   - each message's `app_skill_use` parent ids come from its rendered content,
 *     their decrypted contents from the ordinary embed read (`resolveEmbed`);
 *   - a version the device does not hold is fetched as the bounded-v1 page and
 *     handed to the core unchanged, which validates it and returns the rows the
 *     Worker stores (the page never opens ciphertext).
 */
import { writable } from 'svelte/store';
import { UnitPortError } from '../host/unitPort';
import type { MessageParentsInput, PinnedEmbed, SyncedHeadCandidate } from './childRevisionProtocol';
import type { StoredRowResult } from './embedDataProtocol';
import { appSkillParentIds, type OrderedMessage } from './messageParentIds';

export const EMBED_VERSIONS_ENABLED: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

/** The version a message shows, next to the stored head's version. */
export interface MessageEmbedVersion {
	version: number;
	headVersion: number;
	pinnedHere: boolean;
}

/** Bumped when the message order or a parent's pins may have changed: cards re-resolve. */
export const embedVersionGeneration = writable(0);

const REFRESH_DEBOUNCE_MS = 200;
const CONTENT_CACHE_LIMIT = 64;

let order: { chatId: string | null; messages: OrderedMessage[] } = { chatId: null, messages: [] };
let parentsByMessage: Map<string, string[]> = new Map();
let generation = 0;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let listening = false;
const parentContents = new Map<string, Promise<string | null>>();
/** Versions are immutable once stored, so a version's plaintext can be reused (bounded, in memory only). */
const versionContents = new Map<string, Promise<string>>();
const keysLoaded = new WeakMap<object, Set<string>>();
/**
 * Embeds a card shows at a pinned version newer than this device's head
 * (`waitingForHead`), with the highest version waited for. The head arrives
 * later through a write or sync that need not dispatch `embedUpdated` for this
 * card, so every stored-embed change re-reads these heads (core rule) and
 * cards re-resolve once one reached its version.
 */
const waitingHeads = new Map<string, number>();
let headCheckTimer: ReturnType<typeof setTimeout> | null = null;

function bump(): void {
	generation += 1;
	embedVersionGeneration.set(generation);
}

function scheduleRefresh(): void {
	if (refreshTimer) clearTimeout(refreshTimer);
	refreshTimer = setTimeout(() => {
		refreshTimer = null;
		const next = new Map(order.messages.map((message) => [message.id, appSkillParentIds(message)] as const));
		const changed = next.size !== parentsByMessage.size
			|| [...next].some(([id, parents]) => parentsByMessage.get(id)?.join(',') !== parents.join(','));
		parentsByMessage = next;
		if (changed) bump();
	}, REFRESH_DEBOUNCE_MS);
}

/** Re-reads the heads cards wait for; bumps once any reached its pinned version. */
async function recheckWaitingHeads(): Promise<void> {
	let reached = false;
	for (const [embedId, wanted] of [...waitingHeads]) {
		const head = await embedHead(embedId);
		if (head && head.version >= wanted && waitingHeads.get(embedId) === wanted) {
			waitingHeads.delete(embedId);
			reached = true;
		}
	}
	if (reached) bump();
}

function scheduleHeadCheck(): void {
	if (waitingHeads.size === 0 || headCheckTimer) return;
	headCheckTimer = setTimeout(() => {
		headCheckTimer = null;
		recheckWaitingHeads().catch((error: unknown) => {
			console.error('[messageEmbedVersion] Waiting head unreadable:', (error as { code?: unknown })?.code ?? error);
		});
	}, REFRESH_DEBOUNCE_MS);
}

async function listenForEmbedUpdates(): Promise<void> {
	if (listening) return;
	listening = true;
	const { embedAvailabilityVersion } = await import('../../embedStore');
	embedAvailabilityVersion.subscribe(scheduleHeadCheck);
	const { chatSyncService } = await import('../../chatSyncService');
	chatSyncService.addEventListener('embedUpdated', (event: Event) => {
		const detail = (event as CustomEvent<{ embed_id?: unknown; status?: unknown }>).detail;
		if (typeof detail?.embed_id !== 'string' || detail.status === 'processing') return;
		parentContents.delete(detail.embed_id);
		bump();
	});
}

/**
 * Called by ChatHistory with its message list (chat order). Only the array is
 * read synchronously; parent ids are extracted after a short debounce.
 */
export function publishChatMessageOrder(chatId: string | null | undefined, messages: readonly OrderedMessage[]): void {
	if (!EMBED_VERSIONS_ENABLED) return;
	const chat = chatId ?? null;
	if (chat !== order.chatId) {
		parentContents.clear();
		parentsByMessage = new Map();
	}
	order = { chatId: chat, messages: messages.slice() };
	void listenForEmbedUpdates();
	scheduleRefresh();
}

/** The message a rendered card sits in (`data-message-id` of its ChatHistory wrapper). */
export function messageIdOf(element: Element | null | undefined): string | null {
	return element?.closest('[data-message-id]')?.getAttribute('data-message-id') ?? null;
}

let closeHookInstalled = false;
async function writer() {
	const { rustEmbedWriter, onRustEmbedWriterClosed } = await import('./embedWriteSession');
	if (!closeHookInstalled) {
		closeHookInstalled = true;
		onRustEmbedWriterClosed(clearEmbedVersionCaches);
	}
	return rustEmbedWriter();
}

async function parentContent(chatId: string, parentId: string): Promise<string | null> {
	let pending = parentContents.get(parentId);
	if (!pending) {
		pending = (async () => {
			const { resolveEmbed } = await import('../../embedResolver');
			const parent = await resolveEmbed(parentId, { chatId });
			const content = typeof parent?.content === 'string' ? parent.content : null;
			// A parent without the field has no pins; the core still reads every parent that has it.
			return content && content.includes('pinned_embeds') ? content : null;
		})();
		parentContents.set(parentId, pending);
		// A parent not synced yet (or without pins so far) is read again next time.
		pending.then((content) => { if (content === null) parentContents.delete(parentId); }, () => parentContents.delete(parentId));
	}
	return pending;
}

async function messagesInput(chatId: string, upTo: number): Promise<MessageParentsInput[]> {
	const out: MessageParentsInput[] = [];
	for (const message of order.messages.slice(0, upTo + 1)) {
		const ids = parentsByMessage.get(message.id) ?? appSkillParentIds(message);
		const contents = (await Promise.all(ids.map((id) => parentContent(chatId, id)))).filter((c): c is string => c !== null);
		out.push({ message_id: message.id, parent_contents: contents });
	}
	return out;
}

/** Stored head version and parent of `embedId` (null when this device holds no row). */
export async function embedHead(embedId: string): Promise<{ version: number; parent_embed_id: string | null } | null> {
	if (!EMBED_VERSIONS_ENABLED) return null;
	return (await writer()).unit.request('embedHeadVersion', { embedId });
}

const VERSION_PAGE_LIMIT = 100;
/** Version metadata pages by `chat:embed:head` (no ciphertext; refetched once the head moves). */
const provenancePages = new Map<string, Promise<{ versions: unknown[] }>>();

/**
 * The embed's version list (`version_number`, `revision_origin`, `revision_action`)
 * as one page for the core's display rule; the core validates it.
 */
function versionProvenance(chatId: string, embedId: string, headVersion: number): Promise<{ versions: unknown[] }> {
	const cacheKey = `${chatId}:${embedId}:${headVersion}`;
	let pending = provenancePages.get(cacheKey);
	if (!pending) {
		pending = (async () => {
			const { fetchEmbedVersions } = await import('../../embedDiffStore');
			const versions: unknown[] = [];
			let cursor: number | undefined;
			for (;;) {
				const page = await fetchEmbedVersions(embedId, { chatId, order: 'asc', limit: VERSION_PAGE_LIMIT, cursor });
				versions.push(...page.versions);
				if (page.next_cursor == null || page.next_cursor <= (cursor ?? 0)) return { versions };
				cursor = page.next_cursor;
			}
		})();
		provenancePages.set(cacheKey, pending);
		pending.catch(() => provenancePages.delete(cacheKey));
		if (provenancePages.size > CONTENT_CACHE_LIMIT) provenancePages.delete(provenancePages.keys().next().value as string);
	}
	return pending;
}

/**
 * The version of `embedId` that message `messageId` shows, or null when the
 * message is not part of the published chat (no version scope: show the head).
 */
export async function embedVersionForMessage(messageId: string, embedId: string): Promise<MessageEmbedVersion | null> {
	if (!EMBED_VERSIONS_ENABLED || !order.chatId) return null;
	const at = order.messages.findIndex((message) => message.id === messageId);
	if (at < 0) return null;
	const chatId = order.chatId;
	const { unit } = await writer();
	const messages = await messagesInput(chatId, at);
	const head = await unit.request('embedHeadVersion', { embedId });
	const headVersion = head?.version ?? 1;
	// One version: nothing to follow. Otherwise the core also needs which versions the user made.
	const versionsPage = headVersion > 1 ? await versionProvenance(chatId, embedId, headVersion) : undefined;
	const versions = await unit.request('embedVersionsByMessage', { messages, embedId, versionsPage });
	const own = versions.find((entry) => entry.message_id === messageId);
	if (!own) throw new UnitPortError('embed_version_message_missing');
	if (own.version > headVersion) {
		waitingHeads.set(embedId, Math.max(own.version, waitingHeads.get(embedId) ?? 0));
		console.debug('[messageEmbedVersion] Card waits for head', { embedId, messageId, pinned: own.version, head: head?.version ?? null });
		scheduleHeadCheck();
	}
	return { version: own.version, headVersion, pinnedHere: own.pinned_here };
}

/**
 * Of rows sync or a server read is about to store over local child heads, the
 * ids whose stored head the core keeps because the row would lower its
 * version (`synced_head_regresses`). Empty in builds without the core.
 */
export async function keptStoredHeads(rows: SyncedHeadCandidate[]): Promise<Set<string>> {
	if (!EMBED_VERSIONS_ENABLED || rows.length === 0) return new Set();
	return new Set(await (await writer()).unit.request('embedSyncedHeadsKept', { rows }));
}

/** Pins of one decrypted parent content (empty in builds without the core or without pins). */
export async function pinnedEmbedsOf(content: Record<string, unknown> | null | undefined): Promise<PinnedEmbed[]> {
	if (!EMBED_VERSIONS_ENABLED || !content || content.pinned_embeds === undefined || content.pinned_embeds === null) return [];
	return (await writer()).unit.request('embedPinnedEmbeds', { parentContent: JSON.stringify(content) });
}

/** Loads the child's and its parent's keys into the Worker session (as the write path does). */
async function ensureKeys(client: Awaited<ReturnType<typeof writer>>, chatId: string, embedId: string, parentId: string | null): Promise<void> {
	let loaded = keysLoaded.get(client);
	if (!loaded) keysLoaded.set(client, (loaded = new Set()));
	const key = `${chatId}:${embedId}`;
	if (loaded.has(key)) return;
	const { chatKeyManager } = await import('../../encryption/ChatKeyManager');
	const { computeSHA256 } = await import('../../../message_parsing/utils');
	const chatKey = chatKeyManager.getKeySync(chatId) || (await chatKeyManager.getKey(chatId));
	if (!chatKey) throw new UnitPortError('embed_version_chat_key_missing');
	await client.unit.request('adoptPageChatKey', { chatId, key: new Uint8Array(chatKey) });
	const hashedChatId = await computeSHA256(chatId);
	const ids = [parentId, embedId].filter((id): id is string => typeof id === 'string' && id.length > 0);
	const results = await client.unit.request('openStoredRows', { rows: ids.map((id) => ({
		embedId: id, hashedChatId, encrypted_content: null, encrypted_type: null, encrypted_text_preview: null
	})) });
	const failed = results.find((result): result is Extract<StoredRowResult, { ok: false }> => !result.ok);
	if (failed) throw new UnitPortError(failed.code);
	loaded.add(key);
}

async function fetchVersionPage(chatId: string, embedId: string, version: number): Promise<unknown | null> {
	const { chatDB } = await import('../../db');
	const chat = await chatDB.getChat(chatId);
	const query = new URLSearchParams({ capability: 'bounded-v1', chat_id: chatId });
	if (chat?.team_id) query.set('team_id', chat.team_id);
	const { getApiEndpoint, storageArchiveFetch } = await import('../../../config/api');
	const response = await storageArchiveFetch(getApiEndpoint(
		`/v1/embeds/${encodeURIComponent(embedId)}/versions/${version}?${query}`), { credentials: 'include' });
	if (!response.ok) return null;
	return response.json();
}

async function openVersion(chatId: string, embedId: string, version: number): Promise<string> {
	const client = await writer();
	const head = await client.unit.request('embedHeadVersion', { embedId });
	if (!head) throw new UnitPortError('embed_version_unavailable');
	await ensureKeys(client, chatId, embedId, head.parent_embed_id);
	try {
		return await client.unit.request('embedVersionContent', { embedId, version });
	} catch (error) {
		if (!(error instanceof UnitPortError) || error.code !== 'embed_version_unavailable' || version > head.version) throw error;
		// Row K is not on this device (other device, cleared cache): the core validates the
		// canonical page, the Worker stores its rows, and the read runs again.
		const page = await fetchVersionPage(chatId, embedId, version);
		if (!page) throw error;
		await client.unit.request('cacheVersionPage', { embedId, page });
		return client.unit.request('embedVersionContent', { embedId, version });
	}
}

/** Plaintext TOON of version `version` of `embedId` (the head's own content when it is the head). */
export function embedContentAtVersion(chatId: string, embedId: string, version: number): Promise<string> {
	if (!EMBED_VERSIONS_ENABLED) return Promise.reject(new UnitPortError('embed_versions_unavailable'));
	const cacheKey = `${chatId}:${embedId}:${version}`;
	let pending = versionContents.get(cacheKey);
	if (!pending) {
		pending = openVersion(chatId, embedId, version);
		versionContents.set(cacheKey, pending);
		pending.catch(() => versionContents.delete(cacheKey));
		if (versionContents.size > CONTENT_CACHE_LIMIT) versionContents.delete(versionContents.keys().next().value as string);
	}
	return pending;
}

/**
 * A user-made version of `embedId` was saved on this device (Enhance, restore):
 * its head moved, so cards re-resolve which version their message shows.
 */
export function noteEmbedHeadChanged(embedId: string): void {
	if (!EMBED_VERSIONS_ENABLED) return;
	parentContents.delete(embedId);
	bump();
}

/** Chat of the published message order (the card's lookup chat when it has none of its own). */
export function publishedChatId(): string | null {
	return order.chatId;
}

/** Forget every cached version and parent (logout, account switch). */
export function clearEmbedVersionCaches(): void {
	versionContents.clear();
	provenancePages.clear();
	parentContents.clear();
	waitingHeads.clear();
	order = { chatId: null, messages: [] };
	parentsByMessage = new Map();
}

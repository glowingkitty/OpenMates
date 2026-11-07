/**
 * Builds the bookmark and highlight TS parity vectors from the real flag-off
 * TypeScript services (messageBookmarks, handlersMessageHighlights,
 * sendersMessageHighlights). The dependencies the services import (stores,
 * crypto, IndexedDB, socket) are replaced by the recording stubs of
 * `vectorState`, which both the generator script and the vitest drift test
 * install. The Rust side replays the same file
 * (packages/openmates-rust/src/chat_state/bookmark_highlight_vector_tests.rs).
 */
import { accountCases, decodeCases, deviceCases, highlightRows, inboundCases } from './bookmarkHighlightCases';

/** State shared with the stub modules (globalThis.__bhVectors). */
export interface VectorState {
	plaintexts: Map<string, string>;
	encryptedPlain: string[];
	fetchBodies: string[];
	payloads: string[];
	frames: { type: string; payload: Record<string, unknown> }[];
	stored: unknown[];
	cached: unknown[];
	decrypted: unknown;
}

export interface VectorDeps {
	state: VectorState;
	get<T>(store: { subscribe: (run: (value: T) => void) => () => void }): T;
	resetBookmarks(settings: string | null): void;
	bookmarks: {
		messageBookmarksStore: { subscribe: (run: (value: { account: { bookmarks: Map<string, Set<string>> } | null }) => void) => () => void };
		loadMessageBookmarks(chat: string, mode: 'account' | 'device' | 'transient'): Promise<void>;
		toggleMessageBookmark(chat: string, message: string, mode: 'account' | 'device' | 'transient', legacy: string[]): Promise<void>;
	};
	storage: { getItem(key: string): string | null; setItem(key: string, value: string): void; clear(): void };
	handlers: {
		handleMessageHighlightAddedImpl(payload: unknown): Promise<void>;
		handleMessageHighlightUpdatedImpl(payload: unknown): Promise<void>;
	};
	senders: {
		sendAddMessageHighlightImpl(row: never): Promise<void>;
		sendUpdateMessageHighlightImpl(row: never): Promise<void>;
		sendRemoveMessageHighlightImpl(chat: string, message: string, id: string): Promise<void>;
	};
}

const DEVICE_PREFIX = 'openmates:message-bookmarks:v1:';
const NOW_SECONDS = 1790000500;

const message = (error: unknown): string => (error instanceof Error ? error.message : String(error));
const entries = (map: Map<string, Set<string>> | undefined): [string, string[]][] => [...(map ?? [])].map(([chat, ids]) => [chat, [...ids]]);
const clean = <T>(value: T): T => JSON.parse(JSON.stringify(value));

export async function buildBookmarkHighlightVectors(deps: VectorDeps) {
	const { state } = deps;
	const snapshot = () => entries(deps.get(deps.bookmarks.messageBookmarksStore).account?.bookmarks);

	const account = [];
	for (const item of accountCases) {
		deps.resetBookmarks(item.settings);
		state.encryptedPlain.length = 0;
		let out: Record<string, unknown>;
		try {
			await deps.bookmarks.toggleMessageBookmark(item.chat, item.message, 'account', item.legacy);
			out = { ok: true, plaintext: state.encryptedPlain.at(-1), chats: snapshot() };
		} catch (error) {
			out = { ok: false, error: message(error) };
		}
		account.push({ name: item.name, settings: item.settings, chat: item.chat, message: item.message, legacy: item.legacy, out });
	}

	const decode = [];
	for (const item of decodeCases) {
		deps.resetBookmarks(item.settings);
		let out: Record<string, unknown>;
		try {
			await deps.bookmarks.loadMessageBookmarks(item.chat, 'account');
			out = { ok: true, chats: snapshot() };
		} catch (error) {
			out = { ok: false, error: message(error) };
		}
		decode.push({ name: item.name, settings: item.settings, chat: item.chat, out });
	}

	const device = [];
	for (const item of deviceCases) {
		deps.resetBookmarks(null);
		deps.storage.clear();
		if (item.stored !== null) deps.storage.setItem(DEVICE_PREFIX + item.chat, item.stored);
		let out: Record<string, unknown>;
		try {
			await deps.bookmarks.toggleMessageBookmark(item.chat, item.message, 'device', item.legacy);
			out = { ok: true, stored: deps.storage.getItem(DEVICE_PREFIX + item.chat) };
		} catch (error) {
			out = { ok: false, error: message(error) };
		}
		device.push({ name: item.name, stored: item.stored, chat: item.chat, message: item.message, legacy: item.legacy, out });
	}

	const inbound = [];
	for (const item of inboundCases) {
		state.stored.length = 0;
		state.cached.length = 0;
		state.decrypted = item.plain;
		if (item.cached) state.cached.push(item.cached);
		const payload = { ...item.frame, encrypted_payload: 'ciphertext' };
		if (item.kind === 'added') await deps.handlers.handleMessageHighlightAddedImpl(payload);
		else await deps.handlers.handleMessageHighlightUpdatedImpl(payload);
		inbound.push({ name: item.name, kind: item.kind, plain: item.plain, frame: item.frame, cached: item.cached, row: clean(state.stored.at(0) ?? null) });
	}

	const realNow = Date.now;
	Date.now = () => NOW_SECONDS * 1000 + 321;
	const outbound = [];
	try {
		for (const row of highlightRows) {
			for (const operation of ['add', 'update'] as const) {
				state.stored.length = 0;
				state.payloads.length = 0;
				state.frames.length = 0;
				if (operation === 'add') await deps.senders.sendAddMessageHighlightImpl(row as never);
				else await deps.senders.sendUpdateMessageHighlightImpl(row as never);
				const sent = state.frames[0];
				const { encrypted_payload: _ciphertext, ...frame } = sent.payload;
				outbound.push({
					operation, record: row, nowSeconds: NOW_SECONDS, plaintext: state.payloads[0], frameType: sent.type,
					frame: clean(frame), row: clean(state.stored[0]),
				});
			}
		}
		state.frames.length = 0;
		await deps.senders.sendRemoveMessageHighlightImpl('c', 'm', 'h1');
		outbound.push({ operation: 'remove', ids: ['c', 'm', 'h1'], frameType: state.frames[0].type, frame: clean(state.frames[0].payload) });
	} finally {
		Date.now = realNow;
	}

	return { account, decode, device, inbound, outbound };
}

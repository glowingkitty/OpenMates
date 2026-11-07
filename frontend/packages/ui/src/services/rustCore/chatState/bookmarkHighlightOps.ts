/**
 * Worker-side bookmark and highlight operations of the `chatState` unit (spec:
 * specifications/architecture/sync#sync.client.shared-rust-policy). Stateless
 * wrappers over the `chat_state_bookmarks_*` and `chat_state_highlight_*` exports
 * of the realm's single WASM binding: Rust decides the transition and does the
 * master-key (account bookmarks) or chat-key (highlights) crypto; the page keeps
 * every IO. The fixed Rust bookmark messages become stable refusal codes
 * (BookmarkCode); any other binding rejection answers its own stable code or
 * `protocol`, never message text.
 */
import { UnitRefusal, type UnitHandlers } from '../host/unitPort';
import type { BookmarkHighlightUnitProtocol, BookmarkCode } from './bookmarkHighlightProtocol';
import { bindingCode, type ChatStateBinding } from './chatStateBinding';

type Binding = Pick<ChatStateBinding,
	'chat_state_bookmarks_toggle_account' | 'chat_state_bookmarks_read_account' | 'chat_state_bookmarks_toggle_device'
	| 'chat_state_bookmarks_decode_device' | 'chat_state_highlight_add' | 'chat_state_highlight_update'
	| 'chat_state_highlight_remove' | 'chat_state_highlight_decode_added' | 'chat_state_highlight_decode_updated'
	| 'chat_state_bookmarks_identity'>;

const MESSAGE_CODES: Readonly<Record<string, BookmarkCode>> = Object.freeze({
	'Bookmark settings unavailable': 'bookmark_unavailable',
	'Bookmark limit reached': 'bookmark_limit',
	'Bookmark identity unavailable': 'bookmark_identity',
});
const STABLE_CODE = /^[a-z][a-z0-9_]{0,63}$/;

function refusal(reason: unknown): UnitRefusal {
	const code = bindingCode(reason);
	return new UnitRefusal(MESSAGE_CODES[code] ?? (STABLE_CODE.test(code) ? code : 'protocol'));
}

function guarded<T>(run: () => T): T {
	try {
		return run();
	} catch (reason) {
		throw refusal(reason);
	}
}

async function guardedAsync<T>(run: () => Promise<T>): Promise<T> {
	try {
		return await run();
	} catch (reason) {
		throw refusal(reason);
	}
}

function need<K extends keyof Binding>(binding: Binding, name: K): Binding[K] {
	if (typeof binding[name] !== 'function') throw new UnitRefusal('protocol');
	return (binding[name] as (...args: never[]) => unknown).bind(binding) as Binding[K];
}

function bytes(value: unknown): Uint8Array {
	if (!(value instanceof Uint8Array)) throw new UnitRefusal('protocol');
	return value;
}

function masterKey(value: unknown): CryptoKey {
	if (typeof value !== 'object' || value === null) throw new UnitRefusal('protocol');
	return value as CryptoKey;
}

export function createBookmarkHighlightHandlers(raw: object): UnitHandlers<BookmarkHighlightUnitProtocol> {
	const binding = raw as Binding;
	return {
		bookmarkIdentity: ({ values }) => ({ valid: need(binding, 'chat_state_bookmarks_identity')(values) }),
		bookmarkReadAccount: ({ masterKey: key, encryptedSettings }) =>
			guardedAsync(async () => ({ index: JSON.parse(await need(binding, 'chat_state_bookmarks_read_account')(masterKey(key), encryptedSettings ?? undefined)) })),
		bookmarkToggleAccount: ({ masterKey: key, encryptedSettings, chatId, messageId, legacyIds }) =>
			guardedAsync(async () => JSON.parse(await need(binding, 'chat_state_bookmarks_toggle_account')(masterKey(key), encryptedSettings ?? undefined, chatId, messageId, legacyIds))),
		bookmarkDecodeDevice: ({ stored }) => ({ ids: guarded(() => need(binding, 'chat_state_bookmarks_decode_device')(stored ?? undefined)) }),
		bookmarkToggleDevice: ({ stored, chatId, messageId, legacyIds }) =>
			({ stored: guarded(() => need(binding, 'chat_state_bookmarks_toggle_device')(stored ?? undefined, chatId, messageId, legacyIds)) }),
		highlightAdd: ({ record, chatKey }) => guarded(() => JSON.parse(need(binding, 'chat_state_highlight_add')(JSON.stringify(record), bytes(chatKey)))),
		highlightUpdate: ({ record, chatKey, nowSeconds }) =>
			guarded(() => JSON.parse(need(binding, 'chat_state_highlight_update')(JSON.stringify(record), bytes(chatKey), nowSeconds))),
		highlightRemove: ({ chatId, messageId, id }) => guarded(() => JSON.parse(need(binding, 'chat_state_highlight_remove')(chatId, messageId, id))),
		highlightDecodeAdded: ({ payload, chatKey }) =>
			guarded(() => JSON.parse(need(binding, 'chat_state_highlight_decode_added')(JSON.stringify(payload), bytes(chatKey)))),
		highlightDecodeUpdated: ({ payload, chatKey, cached }) =>
			guarded(() => JSON.parse(need(binding, 'chat_state_highlight_decode_updated')(JSON.stringify(payload), bytes(chatKey), cached ? JSON.stringify(cached) : undefined))),
	};
}

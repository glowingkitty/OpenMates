/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) private message bookmarks: the page adapter
 * over the shared Rust core Worker `chatState` bookmark operations. Loaded only by
 * the guarded branches of messageBookmarks.ts, so default builds never bundle it.
 * Rust (packages/openmates-rust/src/chat_state/bookmarks.rs) validates identities,
 * decrypts and decodes the account settings, applies the alias-aware toggle, enforces
 * the 10 000 limit and re-encrypts; the page keeps the settings POST, the
 * owner/epoch/ciphertext scope fences, localStorage and the store. There is no
 * TypeScript fallback: a refused call rejects with the web error message.
 */
import { getKeyFromStorage } from '../../cryptoService';
import { UnitPortError } from '../host/unitPort';
import { chatStateCall } from './chatListUnitClient';
import type { BookmarkCode, BookmarkIndexReply } from './bookmarkHighlightProtocol';

const MESSAGES: Readonly<Record<BookmarkCode, string>> = Object.freeze({
	bookmark_unavailable: 'Bookmark settings unavailable',
	bookmark_limit: 'Bookmark limit reached',
	bookmark_identity: 'Bookmark identity unavailable',
});

/** Maps a unit refusal to the exact Error text messageBookmarks.ts threw before. */
async function web<T>(run: () => Promise<T>): Promise<T> {
	try {
		return await run();
	} catch (error) {
		if (error instanceof UnitPortError && error.code in MESSAGES) throw new Error(MESSAGES[error.code as BookmarkCode]);
		throw error;
	}
}

const toMap = (index: BookmarkIndexReply): Map<string, Set<string>> =>
	new Map(Object.entries(index).map(([chat, ids]) => [chat, new Set(ids)]));

async function master(): Promise<CryptoKey> {
	const key = await getKeyFromStorage();
	if (!key) throw new Error(MESSAGES.bookmark_unavailable);
	return key;
}

/** `identity()` for every value. */
export async function rustBookmarkIdentity(...values: string[]): Promise<boolean> {
	return (await chatStateCall('bookmarkIdentity', { values })).valid;
}

/** Device-mode ids of one chat from its localStorage value. */
export const rustDecodeDeviceBookmarks = (stored: string | null): Promise<Set<string>> =>
	web(async () => new Set((await chatStateCall('bookmarkDecodeDevice', { stored })).ids));

/** Account bookmarks of the current `encrypted_settings`. */
export const rustReadAccountBookmarks = (encryptedSettings: string | null): Promise<Map<string, Set<string>>> =>
	web(async () => toMap((await chatStateCall('bookmarkReadAccount', { masterKey: await master(), encryptedSettings })).index));

/** Device/transient toggle over the chat's current ids; `stored` is the JSON array to persist. */
export const rustToggleLocalBookmark = (ids: ReadonlySet<string>, chatId: string, messageId: string, legacyIds: readonly string[]): Promise<{ stored: string; ids: Set<string> }> =>
	web(async () => {
		const { stored } = await chatStateCall('bookmarkToggleDevice', { stored: JSON.stringify([...ids]), chatId, messageId, legacyIds: [...legacyIds] });
		return { stored, ids: new Set<string>(JSON.parse(stored)) };
	});

/** Account toggle: the new encrypted settings to POST and the resulting index. */
export const rustToggleAccountBookmark = (encryptedSettings: string | null, chatId: string, messageId: string, legacyIds: readonly string[]): Promise<{ encrypted: string; bookmarks: Map<string, Set<string>> }> =>
	web(async () => {
		const reply = await chatStateCall('bookmarkToggleAccount', { masterKey: await master(), encryptedSettings, chatId, messageId, legacyIds: [...legacyIds] });
		return { encrypted: reply.encryptedSettings, bookmarks: toMap(reply.index) };
	});

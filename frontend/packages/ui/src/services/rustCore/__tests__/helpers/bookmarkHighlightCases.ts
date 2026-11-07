/** Input cases of the bookmark and highlight TS parity vectors (bookmarkHighlightBuild.ts). */
export interface AccountCase { name: string; settings: string | null; chat: string; message: string; legacy: string[] }
export interface DecodeCase { name: string; settings: string | null; chat: string }
export interface DeviceCase { name: string; stored: string | null; chat: string; message: string; legacy: string[] }

const many = (count: number, prefix = 'm'): string[] => Array.from({ length: count }, (_, index) => `${prefix}${index}`);
const bookmarks = (chats: Record<string, string[]>): string => JSON.stringify({ message_bookmarks: { version: 1, chats } });
const emoji = (count: number): string => '\u{1F600}'.repeat(count);

export const accountCases: AccountCase[] = [
	{ name: 'no settings yet', settings: null, chat: 'chat', message: 'question', legacy: [] },
	{ name: 'keeps unrelated settings verbatim', settings: JSON.stringify({ unrelated: { theme: 'dark', n: 1.5 }, list: [1, 2] }), chat: 'chat', message: 'q', legacy: [] },
	{ name: 'appends to an existing chat', settings: bookmarks({ chat: ['a'] }), chat: 'chat', message: 'b', legacy: [] },
	{ name: 'removes when saved', settings: bookmarks({ chat: ['a', 'b'] }), chat: 'chat', message: 'a', legacy: [] },
	{ name: 'removing the last id deletes the chat', settings: bookmarks({ chat: ['a'], other: ['x'] }), chat: 'chat', message: 'a', legacy: [] },
	{ name: 'legacy alias removes every alias', settings: bookmarks({ chat: ['old', 'a'] }), chat: 'chat', message: 'new', legacy: ['old'] },
	{ name: 'legacy alias saved under current id', settings: bookmarks({ chat: ['a'] }), chat: 'chat', message: 'new', legacy: ['old'] },
	{ name: 'two legacy aliases', settings: bookmarks({ chat: ['o2'] }), chat: 'chat', message: 'n', legacy: ['o1', 'o2'] },
	{ name: 'three legacy aliases refused', settings: null, chat: 'chat', message: 'n', legacy: ['a', 'b', 'c'] },
	{ name: 'integer-like chat ids keep JavaScript object order', settings: JSON.stringify({ message_bookmarks: { version: 1, chats: { b: ['x'], 2: ['y'], 1: ['z'] } }, tail: true }), chat: '10', message: 'm', legacy: [] },
	{ name: 'settings key order is preserved', settings: JSON.stringify({ a: 1, message_bookmarks: { version: 1, chats: {} }, z: 2 }), chat: 'c', message: 'm', legacy: [] },
	{ name: 'empty message id refused', settings: null, chat: 'chat', message: '', legacy: [] },
	{ name: 'empty chat id refused', settings: null, chat: '', message: 'm', legacy: [] },
	{ name: 'control character in id refused', settings: null, chat: 'chat', message: 'a\u0001b', legacy: [] },
	{ name: 'unit separator is refused', settings: null, chat: 'chat', message: 'a\u001fb', legacy: [] },
	{ name: 'space boundary is accepted', settings: null, chat: 'chat', message: 'a b', legacy: [] },
	{ name: 'non-ascii ids', settings: null, chat: 'cät', message: 'ü☃', legacy: [] },
	{ name: '256 UTF-16 units accepted', settings: null, chat: 'chat', message: emoji(128), legacy: [] },
	{ name: '258 UTF-16 units refused', settings: null, chat: 'chat', message: emoji(129), legacy: [] },
	{ name: 'limit reached', settings: bookmarks({ chat: many(10000) }), chat: 'chat', message: 'extra', legacy: [] },
	{ name: 'limit toggles off', settings: bookmarks({ chat: many(10000) }), chat: 'chat', message: 'm0', legacy: [] },
	{ name: 'limit counts all chats', settings: bookmarks({ one: many(5000), two: many(5000) }), chat: 'three', message: 'x', legacy: [] },
	{ name: 'settings are not JSON', settings: 'not json', chat: 'chat', message: 'm', legacy: [] },
	{ name: 'settings are an array', settings: '[]', chat: 'chat', message: 'm', legacy: [] },
	{ name: 'bookmarks are not an object', settings: JSON.stringify({ message_bookmarks: [] }), chat: 'chat', message: 'm', legacy: [] },
	{ name: 'unsupported version', settings: JSON.stringify({ message_bookmarks: { version: 2, chats: {} } }), chat: 'chat', message: 'm', legacy: [] },
	{ name: 'chats is an array', settings: JSON.stringify({ message_bookmarks: { version: 1, chats: [] } }), chat: 'chat', message: 'm', legacy: [] },
	{ name: 'ids are not strings', settings: JSON.stringify({ message_bookmarks: { version: 1, chats: { chat: [1] } } }), chat: 'chat', message: 'm', legacy: [] },
	{ name: 'a saved id fails the identity rule', settings: JSON.stringify({ message_bookmarks: { version: 1, chats: { chat: [''] } } }), chat: 'chat', message: 'm', legacy: [] },
	{ name: 'duplicate saved ids collapse', settings: JSON.stringify({ message_bookmarks: { version: 1, chats: { chat: ['a', 'a', 'b'] } } }), chat: 'chat', message: 'c', legacy: [] },
];

export const decodeCases: DecodeCase[] = [
	{ name: 'no settings', settings: null, chat: 'chat' },
	{ name: 'settings without bookmarks', settings: JSON.stringify({ theme: 'dark' }), chat: 'chat' },
	{ name: 'two chats', settings: bookmarks({ a: ['1', '2'], b: ['3'] }), chat: 'a' },
	{ name: 'integer-like chats are ordered first', settings: JSON.stringify({ message_bookmarks: { version: 1, chats: { z: ['a'], 5: ['b'], 3: ['c'] } } }), chat: 'z' },
	{ name: 'over the limit', settings: bookmarks({ chat: many(10001) }), chat: 'chat' },
	{ name: 'at the limit', settings: bookmarks({ chat: many(10000) }), chat: 'chat' },
	{ name: 'corrupt chats', settings: JSON.stringify({ message_bookmarks: { version: 1, chats: { chat: 'a' } } }), chat: 'chat' },
	{ name: 'invalid chat id to load', settings: null, chat: '' },
	{ name: 'not json', settings: '{', chat: 'chat' },
];

export const deviceCases: DeviceCase[] = [
	{ name: 'nothing stored', stored: null, chat: 'chat', message: 'a', legacy: [] },
	{ name: 'toggle on', stored: JSON.stringify(['a']), chat: 'chat', message: 'b', legacy: [] },
	{ name: 'toggle off', stored: JSON.stringify(['a', 'b']), chat: 'chat', message: 'a', legacy: [] },
	{ name: 'alias removal', stored: JSON.stringify(['old']), chat: 'chat', message: 'new', legacy: ['old'] },
	{ name: 'stored value is not JSON', stored: 'oops', chat: 'chat', message: 'a', legacy: [] },
	{ name: 'stored value is an object', stored: '{}', chat: 'chat', message: 'a', legacy: [] },
	{ name: 'stored ids fail identity', stored: JSON.stringify(['ok', '']), chat: 'chat', message: 'a', legacy: [] },
	{ name: 'stored over the limit', stored: JSON.stringify(many(10001)), chat: 'chat', message: 'a', legacy: [] },
	{ name: 'limit reached', stored: JSON.stringify(many(10000)), chat: 'chat', message: 'extra', legacy: [] },
	{ name: 'invalid message id', stored: null, chat: 'chat', message: 'a\u0002', legacy: [] },
	{ name: 'duplicate stored ids collapse', stored: JSON.stringify(['a', 'a']), chat: 'chat', message: 'b', legacy: [] },
	{ name: 'non-ascii ids round-trip', stored: JSON.stringify(['ü']), chat: 'chat', message: '☃', legacy: [] },
];

export interface InboundCase {
	name: string;
	kind: 'added' | 'updated';
	/** Decrypted payload object; `null` = the ciphertext does not decrypt. */
	plain: unknown;
	frame: { chat_id: string; message_id: string; id: string; author_user_id?: string; created_at?: number; updated_at?: number; key_version?: number | null };
	cached: Record<string, unknown> | null;
}

const frame = (extra: Partial<InboundCase['frame']> = {}): InboundCase['frame'] =>
	({ chat_id: 'c', message_id: 'm', id: 'h1', author_user_id: 'u', created_at: 1790000000, key_version: 3, ...extra });
const text = (extra: Record<string, unknown> = {}): Record<string, unknown> =>
	({ kind: 'text', anchor: { exact: 'quote', prefix: 'pre ', suffix: ' post' }, comment: 'note', author_display_name: 'Ada', created_at: 1790000000, ...extra });
const cachedRow = { id: 'h1', kind: 'text', chat_id: 'c', message_id: 'm', anchor: { exact: 'old', prefix: '', suffix: '' }, author_user_id: 'cached-user', created_at: 1780000000, key_version: 7 };

export const inboundCases: InboundCase[] = [
	{ name: 'text highlight', kind: 'added', plain: text(), frame: frame(), cached: null },
	{ name: 'text highlight without key version', kind: 'added', plain: text(), frame: frame({ key_version: undefined }), cached: null },
	{ name: 'text highlight null key version', kind: 'added', plain: text(), frame: frame({ key_version: null }), cached: null },
	{ name: 'text highlight without prefix or suffix', kind: 'added', plain: text({ anchor: { exact: 'only' } }), frame: frame(), cached: null },
	{ name: 'non-string prefix is blanked', kind: 'added', plain: text({ anchor: { exact: 'x', prefix: 3, suffix: null } }), frame: frame(), cached: null },
	{ name: 'embed highlight', kind: 'added', plain: { kind: 'embed', embed_id: 'e1', comment: 'c', created_at: 1 }, frame: frame(), cached: null },
	{ name: 'whitespace comment is dropped from the row', kind: 'added', plain: text({ comment: '   \n' }), frame: frame(), cached: null },
	{ name: 'non-string comment is ignored', kind: 'added', plain: text({ comment: 5 }), frame: frame(), cached: null },
	{ name: 'comment keeps inner whitespace', kind: 'added', plain: text({ comment: ' padded ' }), frame: frame(), cached: null },
	{ name: 'non-string display name is ignored', kind: 'added', plain: text({ author_display_name: 9 }), frame: frame(), cached: null },
	{ name: 'text without anchor is dropped', kind: 'added', plain: { kind: 'text', comment: 'x' }, frame: frame(), cached: null },
	{ name: 'legacy offset-only text is dropped', kind: 'added', plain: { kind: 'text', start: 1, end: 4 }, frame: frame(), cached: null },
	{ name: 'anchor exact must be a string', kind: 'added', plain: text({ anchor: { exact: 4 } }), frame: frame(), cached: null },
	{ name: 'anchor array is dropped', kind: 'added', plain: text({ anchor: ['exact'] }), frame: frame(), cached: null },
	{ name: 'embed without id is dropped', kind: 'added', plain: { kind: 'embed' }, frame: frame(), cached: null },
	{ name: 'embed with empty id is dropped', kind: 'added', plain: { kind: 'embed', embed_id: '' }, frame: frame(), cached: null },
	{ name: 'unknown kind is dropped', kind: 'added', plain: { kind: 'image', embed_id: 'e' }, frame: frame(), cached: null },
	{ name: 'missing kind is dropped', kind: 'added', plain: { anchor: { exact: 'x' } }, frame: frame(), cached: null },
	{ name: 'undecryptable payload is dropped', kind: 'added', plain: null, frame: frame(), cached: null },
	{ name: 'update merges the cached row', kind: 'updated', plain: text({ updated_at: 1790000100 }), frame: { chat_id: 'c', message_id: 'm', id: 'h1', updated_at: 1790000100 }, cached: cachedRow },
	{ name: 'update without a cached row', kind: 'updated', plain: text(), frame: { chat_id: 'c', message_id: 'm', id: 'h1', updated_at: 1790000100 }, cached: null },
	{ name: 'update with a null cached key version', kind: 'updated', plain: text(), frame: { chat_id: 'c', message_id: 'm', id: 'h1', updated_at: 5 }, cached: { ...cachedRow, key_version: null } },
	{ name: 'update of an embed', kind: 'updated', plain: { kind: 'embed', embed_id: 'e2', comment: '  ' }, frame: { chat_id: 'c', message_id: 'm', id: 'h1', updated_at: 8 }, cached: { ...cachedRow, kind: 'embed', embed_id: 'e1' } },
	{ name: 'update that is undecryptable', kind: 'updated', plain: null, frame: { chat_id: 'c', message_id: 'm', id: 'h1', updated_at: 8 }, cached: cachedRow },
];

export const highlightRows: Record<string, unknown>[] = [
	{ id: 'h1', kind: 'text', chat_id: 'c', message_id: 'm', anchor: { exact: 'quote', prefix: 'pre ', suffix: ' post' }, start: 3, end: 8, author_user_id: 'u', author_display_name: 'Ada', comment: 'note', created_at: 1790000000, key_version: 2 },
	{ id: 'h2', kind: 'text', chat_id: 'c', message_id: 'm', anchor: { exact: 'q', prefix: '', suffix: '' }, author_user_id: 'u', created_at: 5 },
	{ id: 'h3', kind: 'embed', chat_id: 'c', message_id: 'm', embed_id: 'e1', author_user_id: 'u', comment: 'look', created_at: 6, updated_at: 7, key_version: null },
	{ id: 'h4', kind: 'embed', chat_id: 'c', message_id: 'm', embed_id: 'e1', author_user_id: 'u', author_display_name: 'Béa', created_at: 6 },
];

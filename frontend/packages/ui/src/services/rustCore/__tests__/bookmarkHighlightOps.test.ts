// Worker-side bookmark and highlight operations of the chatState unit: the fixed Rust
// bookmark messages become stable refusal codes, the page adapter maps them back to the
// web error text, and the ops hand the binding exactly the arguments it consumes.
import { describe, expect, it, vi } from 'vitest';
import { createBookmarkHighlightHandlers } from '../chatState/bookmarkHighlightOps';
import { UnitRefusal } from '../host/unitPort';

const key = new Uint8Array(32).fill(1);

function binding(overrides: Record<string, unknown> = {}) {
	return {
		chat_state_bookmarks_identity: vi.fn(() => true),
		chat_state_bookmarks_read_account: vi.fn(async () => '{"c":["m"]}'),
		chat_state_bookmarks_toggle_account: vi.fn(async () => '{"encryptedSettings":"enc","index":{"c":["m"]}}'),
		chat_state_bookmarks_toggle_device: vi.fn(() => '["m"]'),
		chat_state_bookmarks_decode_device: vi.fn(() => ['m']),
		chat_state_highlight_add: vi.fn(() => '{"type":"add_message_highlight","payload":{},"record":null}'),
		chat_state_highlight_update: vi.fn(() => '{"type":"update_message_highlight","payload":{},"record":null}'),
		chat_state_highlight_remove: vi.fn(() => '{"type":"remove_message_highlight","payload":{},"record":null}'),
		chat_state_highlight_decode_added: vi.fn(() => '{"drop":"undecryptable"}'),
		chat_state_highlight_decode_updated: vi.fn(() => '{"drop":"unknown_kind"}'),
		...overrides,
	};
}

describe('chatState bookmark and highlight handlers', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('passes null settings as absent and parses the binding answers', async () => {
		const b = binding();
		const handlers = createBookmarkHighlightHandlers(b);
		expect(await handlers.bookmarkReadAccount({ masterKey: {} as CryptoKey, encryptedSettings: null }, new AbortController().signal)).toEqual({ index: { c: ['m'] } });
		expect(b.chat_state_bookmarks_read_account).toHaveBeenCalledWith(expect.anything(), undefined);
		expect(handlers.bookmarkDecodeDevice({ stored: null }, new AbortController().signal)).toEqual({ ids: ['m'] });
		expect(b.chat_state_bookmarks_decode_device).toHaveBeenCalledWith(undefined);
		expect(handlers.bookmarkToggleDevice({ stored: '[]', chatId: 'c', messageId: 'm', legacyIds: [] }, new AbortController().signal)).toEqual({ stored: '["m"]' });
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('answers the fixed bookmark messages as stable codes and never leaks other text', async () => {
		const failing = (reason: unknown) => createBookmarkHighlightHandlers(binding({
			chat_state_bookmarks_toggle_device: () => { throw reason; },
			chat_state_bookmarks_toggle_account: async () => { throw reason; },
		}));
		const request = { stored: null, chatId: 'c', messageId: 'm', legacyIds: [] };
		const signal = new AbortController().signal;
		for (const [message, code] of [
			['Bookmark settings unavailable', 'bookmark_unavailable'],
			['Bookmark limit reached', 'bookmark_limit'],
			['Bookmark identity unavailable', 'bookmark_identity'],
			['locked', 'locked'],
			['free text with spaces', 'protocol'],
		]) {
			expect(() => failing(message).bookmarkToggleDevice(request, signal)).toThrow(new UnitRefusal(code));
			await expect(failing(message).bookmarkToggleAccount({ masterKey: {} as CryptoKey, encryptedSettings: null, chatId: 'c', messageId: 'm', legacyIds: [] }, signal)).rejects.toThrow(new UnitRefusal(code));
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses a chat key that is not bytes and a missing binding export', () => {
		const signal = new AbortController().signal;
		const handlers = createBookmarkHighlightHandlers(binding());
		expect(() => handlers.highlightAdd({ record: {} as never, chatKey: 'key' as unknown as Uint8Array }, signal)).toThrow(new UnitRefusal('protocol'));
		expect(handlers.highlightDecodeAdded({ payload: { id: 'h' }, chatKey: key }, signal)).toEqual({ drop: 'undecryptable' });
		expect(() => createBookmarkHighlightHandlers({}).bookmarkIdentity({ values: ['c'] }, signal)).toThrow(new UnitRefusal('protocol'));
	});
});

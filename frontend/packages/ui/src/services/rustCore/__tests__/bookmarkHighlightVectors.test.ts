// TS-generated parity vectors for the shared Rust chatState bookmark and highlight
// operations. The committed JSON (packages/openmates-rust/src/chat_state/
// bookmark_highlight_ts_vectors.json) is written by helpers/generateBookmarkHighlightVectors.mjs
// from the real flag-off TypeScript services. This test rebuilds it from the real modules
// (stores, crypto, IndexedDB and socket replaced by helpers/vectorStubs.ts) and fails when
// they drift. chat_state/bookmark_highlight_vector_tests.rs replays the same file against Rust.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it, vi } from 'vitest';

const stubs = vi.hoisted(() => ({ load: () => import('./helpers/vectorStubs') }));
vi.mock('../../../stores/authState', async () => ({ authStore: (await stubs.load()).authStore }));
vi.mock('../../../stores/userProfile', async () => {
	const m = await stubs.load();
	return { userProfile: m.userProfile, updateProfile: m.updateProfile };
});
vi.mock('../../../config/api', async () => ({ getApiEndpoint: (await stubs.load()).getApiEndpoint }));
vi.mock('../../encryption/MetadataEncryptor', async () => {
	const m = await stubs.load();
	return { decryptWithMasterKey: m.decryptWithMasterKey, encryptWithMasterKey: m.encryptWithMasterKey };
});
vi.mock('../../db', async () => ({ chatDB: (await stubs.load()).chatDB }));
vi.mock('../../websocketService', async () => ({ webSocketService: (await stubs.load()).webSocketService }));
vi.mock('../../encryption/ChatKeyManager', async () => ({ chatKeyManager: (await stubs.load()).chatKeyManager }));
vi.mock('../../encryption/MessageEncryptor', async () => {
	const m = await stubs.load();
	return { encryptHighlightPayload: m.encryptHighlightPayload, decryptHighlightPayload: m.decryptHighlightPayload };
});
vi.mock('../../db/messageHighlights', async () => {
	const m = await stubs.load();
	return { upsertHighlight: m.upsertHighlightIdb, deleteHighlightById: m.deleteHighlightById, getHighlightsForMessage: m.getHighlightsForMessage };
});
vi.mock('../../../stores/messageHighlightsStore', async () => {
	const m = await stubs.load();
	return { upsertHighlight: m.upsertHighlightStore, removeHighlight: m.removeHighlightStore, markHighlightAsMine: m.markHighlightAsMine };
});

import * as bookmarks from '../../messageBookmarks';
import * as handlers from '../../handlersMessageHighlights';
import * as senders from '../../sendersMessageHighlights';
import { invalidateWorkspaceCaches } from '../../workspaceCacheLifecycle';
import { buildBookmarkHighlightVectors } from './helpers/bookmarkHighlightBuild';
import { get, installFetch, resetBookmarkAccount, state } from './helpers/vectorStubs';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/chat_state/bookmark_highlight_ts_vectors.json');

describe('bookmark and highlight parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('the TypeScript bookmark and highlight services match the committed vectors', async () => {
		installFetch();
		const fresh = await buildBookmarkHighlightVectors({
			state, get, bookmarks,
			resetBookmarks: (settings) => { invalidateWorkspaceCaches(); resetBookmarkAccount(settings); localStorage.clear(); },
			storage: localStorage,
			handlers, senders: senders as never,
		});
		expect(JSON.parse(JSON.stringify(fresh))).toEqual(JSON.parse(readFileSync(VECTORS, 'utf8')));
	});
});

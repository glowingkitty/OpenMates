// TS-generated parity vectors for the shared Rust chatState view ops: active-chat
// selection plans, unread bookkeeping, the read gate and shared sub-chat metadata.
// The committed JSON (packages/openmates-rust/src/web_chat_state/view_ts_vectors.json)
// is written by helpers/generateChatViewVectors.mjs from the existing TypeScript
// code (flag off). This test rebuilds it from the real modules, including the real
// unreadMessagesStore and chatReadState.hasUnread, and fails when they drift.
// web_chat_state/view_tests.rs replays the same file against Rust.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { get } from 'svelte/store';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../../db', () => ({ chatDB: {} }));
vi.mock('../../chatSyncService', () => ({ chatSyncService: {} }));

import { planUrlUpdate } from '../../../stores/activeChatUrlPlan';
import { planGlobalSelected, skipDraftActivation } from '../../../components/chats/utils/chatSelectionPlan';
import { sharedSubChatToChat } from '../../../components/chats/utils/sharedSubChatChat';
import { readGateAllows } from '../../readGate';
import { unreadMessagesStore as store } from '../../../stores/unreadMessagesStore';
import { hasUnread } from '../../chatReadState';
import { buildChatViewVectors } from './helpers/chatViewBuild';
import * as cases from './helpers/chatViewCases';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_chat_state/view_ts_vectors.json');

describe('chat view parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('the TypeScript selection, unread, read-gate and metadata code matches the committed vectors', () => {
		const fresh = buildChatViewVectors({
			cases,
			planUrlUpdate, planGlobalSelected, skipDraftActivation, readGateAllows, sharedSubChatToChat,
			unread: {
				apply: (e) => {
					if (e.type === 'increment') store.incrementUnread(e.chat, e.messageId);
					else if (e.type === 'set') store.setUnread(e.chat, e.count, e.messageId);
					else if (e.type === 'clear') store.clearUnread(e.chat);
					else if (e.type === 'mark_manual') store.markManuallyUnread(e.chat);
					else if (e.type === 'release_manual') store.releaseManualUnread(e.chat);
					else store.clearAll();
				},
				counts: () => [...get(store).unreadCounts.entries()],
				isManual: (chat) => store.isManuallyUnread(chat),
				count: (chat) => store.getUnreadCount(chat),
				hasUnread,
			},
		});
		expect(fresh).toEqual(JSON.parse(readFileSync(VECTORS, 'utf8')));
	});
});

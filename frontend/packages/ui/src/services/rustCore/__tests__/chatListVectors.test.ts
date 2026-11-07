// TS-generated parity vectors for the shared Rust chat-list policy.
// The committed JSON (packages/openmates-rust/src/web_chat_state/ts_vectors.json)
// holds inputs plus the outcomes of the existing TypeScript chat-list code
// (flag off): sortChats and groupChats. This test fails if that TypeScript
// behaviour drifts from the vectors, or if the page-side input builders stop
// producing the vectors' Rust inputs; web_chat_state/tests.rs replays the same
// file against Rust.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { VECTOR_TIME_ZONE } from './helpers/chatListCases';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_chat_state/ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));
const json = (value: unknown) => JSON.parse(JSON.stringify(value));

import { buildGroupInput, buildSortInput } from '../../../components/chats/utils/chatListInput';
import { groupChats } from '../../../components/chats/utils/chatGroupUtils';
import { sortChats } from '../../../components/chats/utils/chatSortUtils';
import type { Chat } from '../../../types/chat';

beforeAll(() => {
	process.env.TZ = VECTOR_TIME_ZONE;
	expect(Intl.DateTimeFormat().resolvedOptions().timeZone, 'vectors need their generation time zone').toBe(VECTOR_TIME_ZONE);
});
beforeEach(() => {
	vi.useFakeTimers({ toFake: ['Date'] });
	vi.setSystemTime(vectors.nowMs);
});
afterEach(() => vi.useRealTimers());

const indexed = (chats: Record<string, unknown>[]) => chats.map((chat, index) => ({ ...chat, __index: index })) as unknown as Chat[];
const indexOf = (chats: Chat[]) => chats.map((chat) => (chat as unknown as { __index: number }).__index);

describe('chat list parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('sortChats and the page sort input match the committed vectors', () => {
		for (const c of vectors.sort) {
			expect(json(buildSortInput(c.chats, c.serverOrder)), c.name).toEqual(c.input);
			expect(indexOf(sortChats(indexed(c.chats), c.serverOrder)), c.name).toEqual(c.out);
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('groupChats and the page group input match the committed vectors', () => {
		for (const c of vectors.group) {
			expect(json(buildGroupInput(c.chats)), c.name).toEqual(c.input);
			const grouped = groupChats(indexed(c.chats));
			expect(Object.entries(grouped).map(([key, chats]) => [key, indexOf(chats)]), c.name).toEqual(c.out);
		}
	});
});

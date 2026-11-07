// `chatState` unit of the shared Rust core Worker: the real router and installer
// over a binding that answers the committed Rust outcomes
// (web_chat_state/ts_vectors.json; the Rust decisions themselves are proven by
// web_chat_state/tests.rs), and the flag-on page adapter (rustChatList.ts)
// returning exactly the TypeScript sort and grouping, with no TS fallback.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { VECTOR_TIME_ZONE } from './helpers/chatListCases';
import { createSharedCoreClient, registerSharedRustCore, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter } from '../host/sharedWorkerProtocol';
import { installChatStateUnit } from '../chatState/chatListUnit';
import { prepareChatStateUnit, rustChatStateStats } from '../chatState/chatListUnitClient';
import type { ChatListBinding } from '../chatState/chatListProtocol';
import { TRANSITION_OPS, type TransitionBinding } from '../chatState/transitionProtocol';
import { rustGroupChats, rustSortChats } from '../chatState/rustChatList';
import { buildGroupInput, buildSortInput } from '../../../components/chats/utils/chatListInput';
import type { Chat } from '../../../types/chat';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_chat_state/ts_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));
const key = (value: unknown) => JSON.stringify(value);

const sortOut = new Map<string, number[]>(vectors.sort.map((c: { input: unknown; out: number[] }) => [key(c.input), c.out]));
const groupOut = new Map<string, unknown>(vectors.group.map((c: { input: unknown; out: unknown }) => [key(c.input), c.out]));
const ops: string[] = [];
/** The transition exports are covered by transitionVectors.test.ts; here they only have to exist. */
const transitionStubs = Object.fromEntries(Object.values(TRANSITION_OPS).map((name) => [name, () => { throw new Error('protocol'); }])) as unknown as TransitionBinding;
// The view ops (selection, unread, metadata) are proven in chatViewVectors.test.ts.
const unusedView = () => { throw new Error('protocol'); };
const binding: ChatListBinding = {
	...transitionStubs,
	chat_state_selection_url_plan: unusedView,
	chat_state_selection_global_selected: unusedView,
	chat_state_selection_draft_activation: unusedView,
	chat_state_unread_reduce: unusedView,
	chat_state_unread_query: unusedView,
	chat_state_unread_read_gate: unusedView,
	chat_state_metadata_shared_sub_chat: unusedView,
	chat_state_sort: (input) => {
		ops.push('sort');
		const out = sortOut.get(key(JSON.parse(input)));
		if (!out) throw new Error('protocol');
		return JSON.stringify(out);
	},
	chat_state_group: (input) => {
		ops.push('group');
		const out = groupOut.get(key(JSON.parse(input)));
		if (!out) throw new Error('protocol');
		return JSON.stringify(out);
	},
};

function fakeWorker() {
	const listeners: Record<string, ((event: Event) => void)[]> = { message: [], error: [], messageerror: [] };
	const router = createSharedWorkerRouter({
		installers: { chatState: installChatStateUnit },
		loadBinding: async () => binding,
		reply: (reply) => queueMicrotask(() => { for (const l of listeners.message) l({ data: reply } as MessageEvent); }),
	});
	const endpoint: SharedWorkerEndpoint = {
		postMessage(message, transfer) { void router.handle(message, transfer as MessagePort[]); },
		addEventListener(type, listener) { listeners[type].push(listener); },
		terminate() {},
	};
	return endpoint;
}

let unregister: (() => void) | null = null;
beforeAll(() => {
	process.env.TZ = VECTOR_TIME_ZONE;
	expect(Intl.DateTimeFormat().resolvedOptions().timeZone, 'vectors need their generation time zone').toBe(VECTOR_TIME_ZONE);
});
beforeEach(() => {
	ops.length = 0;
	unregister = registerSharedRustCore(createSharedCoreClient(fakeWorker));
});
afterEach(() => unregister?.());

describe('shared chatState unit', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('refuses a binding without the chat-state exports', () => {
		const channel = new MessageChannel();
		expect(() => installChatStateUnit({ binding: {}, ports: [channel.port2], generation: null, principal: null, signal: new AbortController().signal }))
			.toThrow('unavailable');
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('orders every vector chat list exactly like the TypeScript sort', async () => {
		for (const c of vectors.sort) {
			const chats = c.chats.map((chat: Record<string, unknown>, index: number) => ({ ...chat, __index: index })) as unknown as Chat[];
			const sorted = await rustSortChats(chats, buildSortInput(chats, c.serverOrder));
			expect(sorted.map((chat) => (chat as unknown as { __index: number }).__index), c.name).toEqual(c.out);
		}
		expect(ops.filter((op) => op === 'sort')).toHaveLength(vectors.sort.length);
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('groups every vector chat list like the TypeScript grouping, key order included', async () => {
		for (const c of vectors.group) {
			const chats = c.chats.map((chat: Record<string, unknown>, index: number) => ({ ...chat, __index: index })) as unknown as Chat[];
			const input = { ...buildGroupInput(chats, new Date(vectors.nowMs)) };
			const grouped = await rustGroupChats(chats, input);
			const got = Object.entries(grouped).map(([k, list]) => [k, list.map((chat) => (chat as unknown as { __index: number }).__index)]);
			// Integer-like keys are ordered first by every JS object, exactly like the TypeScript grouping.
			expect(got, c.name).toEqual(Object.entries(Object.fromEntries(c.out)));
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('rejects with the fixed protocol code instead of falling back to TypeScript', async () => {
		const before = rustChatStateStats.failures;
		await expect(rustSortChats([], { chats: [], serverOrder: ['unknown-request'] })).rejects.toMatchObject({ code: 'protocol' });
		expect(rustChatStateStats.failures).toBe(before + 1);
	});

	// contract-test: supporting surface=gui.web assertions=sync.client.shared-rust-policy
	it('prepares the unit ahead of the first decision and records the phase marks', async () => {
		await prepareChatStateUnit();
		const opens = rustChatStateStats.opens;
		expect(rustChatStateStats.phases).toMatchObject({ prepareStart: expect.any(Number), coreReady: expect.any(Number), opened: expect.any(Number) });
		await rustSortChats([], { chats: [], serverOrder: [] }).catch(() => undefined);
		expect(rustChatStateStats.opens, 'the first call reuses the prepared port').toBe(opens);
	});
});

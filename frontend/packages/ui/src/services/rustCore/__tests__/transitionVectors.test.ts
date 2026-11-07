// TS-generated parity vectors for the shared Rust message-list, activity and
// indicator policies. The committed JSON (packages/openmates-rust/src/web_chat_state/
// transition_vectors.json) holds inputs plus the outcomes of the flag-off
// TypeScript (messageWindowPruning, chatTimeline, chatActivity, indicatorReference).
// This test fails if that TypeScript drifts from the vectors or the page input
// builders stop producing the vectors' Rust inputs, and runs the flag-on adapter
// over the shared Worker unit with the vector answers; web_chat_state/transition_tests.rs
// replays the same file against Rust.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { createSharedCoreClient, registerSharedRustCore, type SharedWorkerEndpoint } from '../host/sharedCoreRegistry';
import { createSharedWorkerRouter } from '../host/sharedWorkerProtocol';
import { installChatStateUnit } from '../chatState/chatListUnit';
import type { ChatListBinding } from '../chatState/chatListProtocol';
import { TRANSITION_OPS } from '../chatState/transitionProtocol';
import { CHAT_VIEW_OPS } from '../chatState/chatViewProtocol';
import {
	rustAggregateRunningChats, rustComposerIndicator, rustMergeTimelineEntries, rustPairTimelineExchange, rustPreserveExpandedWindow,
	rustProcessingAncestorIds, rustPruneWindow, rustTimelineExchangeIndex, rustTimelineResponseId, rustTitleIndicator,
} from '../chatState/rustTransitions';
import { buildComposerIndicatorInput, buildPruneInput, buildTitleIndicatorInput, messageIds, timelineRows } from '../chatState/transitionInput';
import { pruneDecryptedMessageWindow, shouldPreserveExpandedMessageWindow } from '../../../utils/messageWindowPruning';
import { buildTimelineExchangeIndex, mergeTimelineEntries, pairTimelineExchange, timelineResponseId } from '../../../utils/chatTimeline';
import { aggregateRunningChats, processingAncestorIds } from '../../../utils/chatActivity';
import { referenceComposer, referenceTitle } from './helpers/indicatorReference';
import { ACTIVITY_CASES, INDICATOR_CASES, MERGE_CASES, PRESERVE_CASES, PRUNE_CASES, TIMELINE_CASES, TITLE_CASES } from './helpers/transitionCases';

const VECTORS = resolve(__dirname, '../../../../../../../packages/openmates-rust/src/web_chat_state/transition_vectors.json');
const vectors = JSON.parse(readFileSync(VECTORS, 'utf8'));
const json = (value: unknown) => JSON.parse(JSON.stringify(value));
const key = (value: unknown) => JSON.stringify(value);
type Any = any;

describe('transition parity vectors (TypeScript side)', () => {
	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('window pruning and preservation match the committed vectors', () => {
		expect(vectors.prune).toHaveLength(PRUNE_CASES.length);
		vectors.prune.forEach((c: Any, i: number) => {
			const { messages, options } = PRUNE_CASES[i];
			expect(json(buildPruneInput(messages as Any, options as Any)), c.name).toEqual(c.input);
			const indexed = messages.map((m, n) => ({ ...m, __i: n }));
			expect(pruneDecryptedMessageWindow(indexed as Any, options as Any).messages.map((m: Any) => m.__i), c.name).toEqual(c.out);
		});
		vectors.preserve.forEach((c: Any, i: number) => {
			const { current, incoming } = PRESERVE_CASES[i];
			expect({ current: messageIds(current as Any), incoming: messageIds(incoming as Any) }, c.name).toEqual(c.input);
			expect(shouldPreserveExpandedMessageWindow(current as Any, incoming as Any), c.name).toBe(c.out);
		});
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('timeline merge, exchange index, response and pairing match the committed vectors', () => {
		vectors.timeline.forEach((c: Any, i: number) => {
			const { entries, bookmarks, id, pendingUserId } = TIMELINE_CASES[i];
			expect(json(timelineRows(entries as Any)), c.name).toEqual(c.entries);
			const index = buildTimelineExchangeIndex(entries as Any, new Set(bookmarks));
			expect([...index.bookmarkedExchanges], c.name).toEqual(c.index.bookmarkedExchanges);
			expect(index.answeredCount, c.name).toBe(c.index.answeredCount);
			expect(timelineResponseId(entries as Any, id), c.name).toBe(c.response);
			if (c.pair.error) expect(() => pairTimelineExchange(entries as Any, id, pendingUserId), c.name).toThrow();
			else expect(pairTimelineExchange(entries as Any, id, pendingUserId).pending, c.name).toBe(c.pair.pending);
		});
		vectors.merge.forEach((c: Any, i: number) => {
			const merged = mergeTimelineEntries(...(MERGE_CASES[i].pages as Any[]));
			const flat = MERGE_CASES[i].pages.flat();
			expect(c.out.map((index: number) => flat[index].message_id), c.name).toEqual(merged.map((row) => row.message_id));
		});
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('activity grouping matches the committed vectors', () => {
		vectors.activity.forEach((c: Any, i: number) => {
			const { chats, running } = ACTIVITY_CASES[i];
			expect([...processingAncestorIds(chats as Any, new Set(running))], c.name).toEqual(c.ancestors);
			expect(aggregateRunningChats(chats as Any, new Set(running)).map((g) => g.activeSubChatCount), c.name).toEqual(c.aggregate.map((g: number[]) => g[1]));
		});
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('indicator decisions match the committed vectors', () => {
		const byName = new Map(INDICATOR_CASES.map((c) => [c.name, c.state]));
		for (const c of vectors.composer) {
			const state = byName.get(c.name)!;
			expect(json(buildComposerIndicatorInput(state as Any)), c.name).toEqual(c.input);
			expect(json(referenceComposer(state as Any)), c.name).toEqual(c.out);
		}
		for (const c of vectors.title) {
			const t = TITLE_CASES.find((x) => x.name === c.name)!;
			expect(buildTitleIndicatorInput(t.typing, t.skill, t.reasoning), c.name).toEqual(c.input);
			expect(referenceTitle(t.typing, t.skill, t.reasoning), c.name).toEqual(c.out);
		}
	});
});

// Answers each Worker export from the vectors by exact request, so the adapter's request shaping and result mapping are proven end to end.
const answers = new Map<string, string>();
const remember = (name: string, input: unknown, out: unknown) => answers.set(`${name}:${key(input)}`, JSON.stringify(out));
for (const c of vectors.prune) remember('chat_state_window_prune', c.input, c.out);
for (const c of vectors.preserve) remember('chat_state_window_preserve', c.input, c.out);
for (const c of vectors.merge) remember('chat_state_timeline_merge', c.input, c.out);
for (const c of vectors.timeline) {
	remember('chat_state_timeline_index', { entries: c.entries, bookmarks: c.bookmarks }, c.index);
	remember('chat_state_timeline_response', { entries: c.entries, id: c.id }, c.response);
	remember('chat_state_timeline_pair', { entries: c.entries, id: c.id, pendingUserId: c.pendingUserId, undecryptable: false }, c.pair);
}
for (const c of vectors.activity) {
	remember('chat_state_activity_ancestors', c.input, c.ancestors);
	remember('chat_state_activity_aggregate', c.input, c.aggregate);
}
for (const c of vectors.composer) remember('chat_state_indicator_composer', c.input, c.out);
for (const c of vectors.title) remember('chat_state_indicator_title', c.input, c.out);

const binding = Object.fromEntries([...Object.values(TRANSITION_OPS), ...Object.values(CHAT_VIEW_OPS), 'chat_state_sort', 'chat_state_group'].map((name) => [name, (input: string) => {
	const out = answers.get(`${name}:${key(JSON.parse(input))}`);
	if (out === undefined) throw new Error('protocol');
	return out;
}])) as unknown as ChatListBinding;

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

describe('flag-on transition adapter over the shared chatState unit', () => {
	let unregister: (() => void) | null = null;
	beforeEach(() => { unregister = registerSharedRustCore(createSharedCoreClient(fakeWorker)); });
	afterEach(() => unregister?.());

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('prunes, merges, indexes, pairs and groups like the TypeScript it replaces', async () => {
		for (const [i, c] of vectors.prune.entries()) {
			const { messages, options } = PRUNE_CASES[i];
			const indexed = messages.map((m, n) => ({ ...m, __i: n }));
			const rust = await rustPruneWindow(indexed as Any, options as Any);
			expect(rust.messages.map((m: Any) => m.__i), c.name).toEqual(pruneDecryptedMessageWindow(indexed as Any, options as Any).messages.map((m: Any) => m.__i));
		}
		for (const [i, c] of vectors.preserve.entries()) {
			expect(await rustPreserveExpandedWindow(PRESERVE_CASES[i].current as Any, PRESERVE_CASES[i].incoming as Any), c.name).toBe(c.out);
		}
		for (const [i, c] of vectors.merge.entries()) {
			const rust = await rustMergeTimelineEntries(...(MERGE_CASES[i].pages as Any[]));
			expect(rust, c.name).toEqual(mergeTimelineEntries(...(MERGE_CASES[i].pages as Any[])));
		}
		for (const [i, c] of vectors.timeline.entries()) {
			const { entries, bookmarks, id, pendingUserId } = TIMELINE_CASES[i];
			const ts = buildTimelineExchangeIndex(entries as Any, new Set(bookmarks));
			const rust = await rustTimelineExchangeIndex(entries as Any, new Set(bookmarks));
			expect(rust.entries, c.name).toEqual(ts.entries);
			expect([...rust.assistantBookmarks], c.name).toEqual([...ts.assistantBookmarks]);
			expect([...rust.legacyAliases], c.name).toEqual([...ts.legacyAliases]);
			expect([...rust.assistantUsers], c.name).toEqual([...ts.assistantUsers]);
			expect(await rustTimelineResponseId(entries as Any, id), c.name).toBe(timelineResponseId(entries as Any, id));
			let expected: unknown;
			try { expected = pairTimelineExchange(entries as Any, id, pendingUserId); } catch (error) { expected = (error as Error).message; }
			let actual: unknown;
			try { actual = await rustPairTimelineExchange(entries as Any, id, pendingUserId); } catch (error) { actual = (error as Error).message; }
			expect(actual, c.name).toEqual(expected);
		}
		for (const [i, c] of vectors.activity.entries()) {
			const { chats, running } = ACTIVITY_CASES[i];
			expect([...(await rustProcessingAncestorIds(chats as Any, new Set(running)))], c.name).toEqual([...processingAncestorIds(chats as Any, new Set(running))]);
			expect(await rustAggregateRunningChats(chats as Any, new Set(running)), c.name).toEqual(aggregateRunningChats(chats as Any, new Set(running)));
		}
	});

	// contract-test: supporting surface=gui.web assertions=sdk.client.thin-platform-boundary
	it('answers the indicator decisions of every vector', async () => {
		const byName = new Map(INDICATOR_CASES.map((c) => [c.name, c.state]));
		for (const c of vectors.composer) expect(await rustComposerIndicator(byName.get(c.name)!), c.name).toEqual(c.out);
		for (const c of vectors.title) {
			const t = TITLE_CASES.find((x) => x.name === c.name)!;
			expect(await rustTitleIndicator(t.typing, t.skill, t.reasoning), c.name).toEqual(c.out);
		}
	});
});

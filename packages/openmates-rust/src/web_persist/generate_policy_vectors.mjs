// Generates policy_vectors.json: for every cache/chat-row op of the persist unit, the
// op input (JSON the page sends) and the output of the TypeScript reference
// (db/cachePolicy.ts, db/chatRowPolicy.ts). Run with Node 24:
//   node packages/openmates-rust/src/web_persist/generate_policy_vectors.mjs
import { writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import * as cache from '../../../../frontend/packages/ui/src/services/db/cachePolicy.ts';
import { isSafeToEvictMessage } from '../../../../frontend/packages/ui/src/services/db/messageRowPolicy.ts';
import * as chats from '../../../../frontend/packages/ui/src/services/db/chatRowPolicy.ts';

const vectors = {};
/** Records an op case: `input` is what is sent to Rust (after JSON), `out` the TS answer. */
const add = (op, input, out) => { (vectors[op] ??= []).push({ input: JSON.parse(JSON.stringify(input)), out: JSON.parse(JSON.stringify(out)) }); };

// ---- windowPlan
const NUMS = [undefined, null, 0, -5, 0.5, 1, 2, 3, 30, 31.7, 99, 100, 101, 5000, 1700000000, 1700000000.5];
for (const limit of NUMS) add('windowPlan', { chatId: 'c1', limit }, cache.planMessageWindow({ chatId: 'c1', limit }));
for (const direction of [undefined, null, 'latest', 'before', 'after', 'around', 'sideways']) {
	for (const limit of [undefined, 2, 7, 100]) {
		for (const anchorCreatedAt of [undefined, 0, 1000]) {
			for (const compressedUpToTimestamp of [undefined, 0, 500]) {
				for (const stamp of [undefined, 0, 900]) {
					const input = { chatId: 'c1', direction, limit, anchorCreatedAt, compressedUpToTimestamp, beforeTimestamp: stamp, afterTimestamp: stamp, anchorMessageId: direction === 'around' ? 'm9' : undefined };
					add('windowPlan', input, cache.planMessageWindow(input));
				}
			}
		}
	}
}
for (const anchorRecord of [null, undefined, { chat_id: 'c1', created_at: 700 }, { chat_id: 'c1', created_at: 0 }, { chat_id: 'c1' }, { chat_id: 'c1', created_at: null }, { chat_id: 'other', created_at: 700 }]) {
	for (const anchorCreatedAt of [undefined, 0, 1000]) {
		for (const anchorMessageId of [undefined, null, '', 'm9']) {
			const input = { chatId: 'c1', direction: 'around', limit: 10, anchorMessageId, anchorCreatedAt, anchorRecord };
			add('windowPlan', input, cache.planMessageWindow(input));
		}
	}
}

// ---- windowResultMeta
const cursors = [null, undefined, { created_at: 10, message_id: 'a' }, { created_at: 0, message_id: '' }, { created_at: null, message_id: null }, {}];
for (const direction of ['latest', 'before', 'after', 'around', 'x']) {
	for (const hasMore of [true, false]) for (const beforeHasMore of [true, false]) for (const afterHasMore of [true, false]) {
		for (const first of cursors.slice(0, 4)) for (const last of [null, { created_at: 99, message_id: 'z' }]) {
			const input = { direction, hasMore, beforeHasMore, afterHasMore, anchorFound: hasMore, first, last };
			add('windowResultMeta', input, cache.windowResultMeta(input));
		}
	}
}

// ---- windowPageRecord
const result = (extra) => ({ startCursor: 10, startCursorMessageId: 'a', endCursor: 20, endCursorMessageId: 'b', hasMoreBefore: true, hasMoreAfter: false, ...extra });
for (const extra of [{}, { startCursor: null }, { startCursorMessageId: null }, { endCursor: null, endCursorMessageId: null },
	{ startCursor: 1700000000.25 }, { startCursor: 0 }, { startCursor: null, startCursorMessageId: null, endCursor: null, endCursorMessageId: null, hasMoreBefore: false }]) {
	for (const existingCachedAt of [null, 5, 0]) for (const pageKind of ['normal', 'forgotten']) for (const direction of ['latest', 'around']) {
		const input = { chatId: 'c1', pageKind, direction, result: result(extra), messageIds: ['a', 'b'], existingCachedAt, now: 1234 };
		add('windowPageRecord', input, cache.buildWindowPageRecord(input));
	}
}

// ---- eviction plans
const page = (id, accessed, kind, ids, extra) => ({ id, chat_id: 'c1', page_kind: kind, last_accessed_at: accessed, message_ids: ids, cache_generation: 1, ...extra });
const pageSets = [
	[],
	[page('p1', 5, 'normal', ['a'])],
	[page('p1', 5, 'normal', ['a']), page('p2', 3, 'normal', ['b']), page('p3', 9, 'normal', ['c']), page('p4', 1, 'forgotten', ['d'])],
	Array.from({ length: 15 }, (_, i) => page(`n${i}`, (i * 7) % 11, 'normal', [`m${i}`, `m${(i + 1) % 15}`])),
	[page('t1', 4, 'normal', ['a']), page('t2', 4, 'normal', ['a']), page('t3', 4, 'normal', ['b'])],
];
for (const pages of pageSets) {
	for (const maxPagesPerChat of [undefined, 0, 1, 2.9, 12]) {
		for (const protectedPageIds of [undefined, ['p1', 'n3']]) {
			for (const protectedMessageIds of [undefined, [], ['a'], ['m5']]) {
				const input = { pages, maxPagesPerChat, protectedPageIds, protectedMessageIds };
				add('evictPlan', input, cache.planPageEviction(input));
			}
		}
	}
	for (const deletingPageIds of [[], ['p1'], ['p2', 'p3'], ['n1', 'n2', 'n3'], ['missing'], ['t1', 't3']]) {
		for (const protectedMessageIds of [undefined, [], ['a'], ['m2']]) {
			const input = { pages, deletingPageIds, protectedMessageIds };
			add('evictDeletePlan', input, { plan: cache.planPageDeletion(input) });
		}
	}
	add('budgetCandidates', { pages }, { pages: cache.budgetCandidates(pages) });
}
add('budgetCandidates', { pages: [page('g2', 1, 'normal', [], { cache_generation: 2 }), page('g0', 2, 'normal', [], { cache_generation: undefined }), page('ok', 3, 'normal', [])] },
	{ pages: cache.budgetCandidates([page('g2', 1, 'normal', [], { cache_generation: 2 }), page('g0', 2, 'normal', [], { cache_generation: undefined }), page('ok', 3, 'normal', [])]) });

// ---- page confirmation
const synced = { status: 'synced' };
for (const messages of [[], [synced], [synced, synced], [synced, { status: 'sending' }], [null], [synced, null], [{ status: 'synced', pending_turn_preflight_v1: { a: 1 } }]]) {
	add('pageConfirmed', { messages }, { confirmed: messages.every((m) => isSafeToEvictMessage(m ?? undefined)) });
}

// ---- budget gates
for (const force of [true, false]) {
	for (const now of [0, 29_999, 30_000, 100_000]) for (const lastCheckAt of [0, 70_000, 100_000]) {
		const input = { force, now, lastCheckAt };
		add('budgetThrottle', input, { throttled: cache.budgetCheckThrottled(input) });
	}
	for (const quota of [undefined, null, 0, -1, 1000, 200 * 1024 * 1024, 1e12]) for (const usage of [undefined, null, 0, 49, 50, 51, 1e12]) {
		const input = { force, configuredBytes: 100, quota, usage };
		add('budgetTarget', input, cache.budgetTarget(input));
	}
	for (const removed of [1, 3, 4, 8, 31, 32, 33]) for (const usage of [undefined, null, 5, 10, 11]) {
		const input = { force, removed, target: 10, usage };
		add('budgetAfter', input, { action: cache.budgetAfterEviction(input) });
	}
}
for (const normalPageCount of [0, 1, 2, 12]) add('budgetChatStep', { normalPageCount }, cache.budgetChatStep({ normalPageCount }));

// ---- quota flow and paging
for (const stage of ['write', 'retry']) for (const canRetry of [true, false]) for (const errorName of [null, 'QuotaExceededError', 'AbortError', '']) {
	const input = { stage, canRetry, errorName };
	add('quotaStep', input, { action: cache.quotaStep(input) });
}
for (const limit of [-5, 0, 0.5, 1, 49, 50, 51, 1000]) add('chatsPageSize', { limit }, { size: cache.chatsPageSize(limit) });

// ---- chat rows
const chatBase = { chat_id: 'c1', messages_v: 0 };
for (const chat of [{}, { draft_v: 3 }, { draft_v: 0, title_v: 2, messages_v: 9 }, { last_edited_overall_timestamp: 5, updated_at: 6, created_at: 7 },
	{ updated_at: 6, created_at: 7 }, { created_at: 7 }, { last_edited_overall_timestamp: 0 }, { draft_v: null, title_v: null, messages_v: null, updated_at: null }]) {
	add('chatDefaults', { chat, now: 1700000000 }, chats.chatRowDefaults(chat, 1700000000));
}
const shells = [
	{ ...chatBase, draft_v: 1, encrypted_draft_md: 'cipher' },
	{ ...chatBase, draft_v: 0, encrypted_draft_md: 'cipher' },
	{ ...chatBase, encrypted_draft_md: 'cipher' },
	{ ...chatBase, draft_v: 2, encrypted_draft_md: 'null' },
	{ ...chatBase, draft_v: 2, encrypted_draft_md: '' },
	{ ...chatBase, draft_v: 2 },
	{ ...chatBase, draft_v: 2, encrypted_draft_md: 'c', messages_v: 1 },
	{ ...chatBase, draft_v: 2, encrypted_draft_md: 'c', team_id: 't' },
	{ ...chatBase, draft_v: 2, encrypted_draft_md: 'c', chat_visibility: 'direct' },
	{ ...chatBase, draft_v: 2, encrypted_draft_md: 'c', is_anonymous: true },
	{ ...chatBase, draft_v: 2, encrypted_draft_md: 'c', anonymous_encrypted_chat_key: 'k' },
	{ ...chatBase, draft_v: 2, encrypted_draft_md: 'c', is_shared: true },
	{ ...chatBase, draft_v: 2, encrypted_draft_md: 'c', is_shared_by_others: true },
	{ ...chatBase, draft_v: 2, encrypted_draft_md: 'c', encrypted_chat_key: 'k' },
	{ ...chatBase, draft_v: 2, encrypted_draft_md: 'c', encrypted_title: 't' },
];
const existings = [null, { messages_v: 0 }, { messages_v: 1 }, { messages_v: 0, encrypted_chat_key: 'k' }, { messages_v: 0, encrypted_title: 't' },
	{ messages_v: 0, team_id: 't' }, { messages_v: 0, chat_visibility: 'direct' }, {}];
for (const chat of shells) for (const existing of existings) add('keylessDraftOnly', { chat, existing }, { expected: chats.isExpectedKeylessDraftOnlySyncChat(chat, existing) });
for (const existing of [undefined, null, [], ['a'], ['a', 'b', 'c', 'd', 'e'], ['a', 'b', 'c', 'd']]) for (const blob of ['a', 'e', 'z']) {
	add('candidateKeys', { existing, blob }, { updated: chats.nextCandidateKeys(existing, blob) });
}

// draft merge: rows x fields
const rows = [null, { chat_id: 'c1', draft_v: 3, cleared_draft_v: 2, updated_at: 50, team_id: null }, { chat_id: 'c1', draft_v: 0 }, { chat_id: 'c1', draft_v: 3, cleared_draft_v: 5, team_id: 't' }, { chat_id: 'c1' }];
const seeds = [null, { chat_id: 'c1', draft_v: 1, team_id: null }, { chat_id: 'other', draft_v: 1 }, { chat_id: 'c1', team_id: 't' }, { chat_id: 'c1', team_id: undefined, cleared_draft_v: 4, updated_at: 9 }];
const fieldSets = [
	{}, { draft_v: 4, encrypted_draft_md: 'x' }, { draft_v: 2, encrypted_draft_md: 'x' }, { draft_v: 3, encrypted_draft_md: 'x' }, { draft_v: 1, encrypted_draft_md: null },
	{ draft_v: 0, encrypted_draft_md: null, cleared_draft_v: 3 }, { draft_v: 0, encrypted_draft_md: null, cleared_draft_v: 2 }, { draft_v: 0, encrypted_draft_md: null },
	{ draft_v: 5, encrypted_draft_md: 'x', cleared_draft_v: 1, updated_at: 99 }, { draft_v: 5, encrypted_draft_md: 'x', updated_at: 10 }, { draft_v: 5, encrypted_draft_md: 'x', cleared_draft_v: null, updated_at: null },
	{ draft_v: 6, encrypted_draft_md: 'x', encrypted_draft_preview: 'p', ideabucket: { a: 1 }, ideabucket_processing_window_id: 'w' },
	{ draft_v: 2, encrypted_draft_md: undefined, encrypted_draft_preview: undefined }, { draft_v: 7, ideabucket: undefined },
	{ draft_v: null, encrypted_draft_md: 'x' }, { encrypted_draft_md: 'x' }, { cleared_draft_v: 8, updated_at: 3 }, { draft_v: 4 },
];
for (const current of rows) for (const missingRow of seeds) for (const fields of fieldSets) {
	const undefinedKeys = Object.keys(fields).filter((k) => fields[k] === undefined);
	const out = chats.mergeDraftFields('c1', current, fields, missingRow);
	add('draftMerge', { chatId: 'c1', current, fields, missingRow, undefinedKeys }, out);
}

// team draft intent
const teamChats = [null, { team_id: 't', team_draft_pending_sync: 'update', encrypted_draft_md: 'c', draft_v: 2, cleared_draft_v: 1 },
	{ team_id: 't', team_draft_pending_sync: 'delete', encrypted_draft_md: null, draft_v: 0 }, { team_id: 'u', team_draft_pending_sync: 'update' },
	{ team_id: 't' }, { team_id: 't', team_draft_pending_sync: 'update', draft_v: 2, cleared_draft_v: null }];
const expects = [undefined, { kind: 'update' }, { kind: 'delete' }, { kind: 'update', cipher: 'c' }, { kind: 'update', cipher: 'x' }, { kind: 'delete', cipher: null },
	{ kind: 'update', version: 2 }, { kind: 'update', version: 3 }, { kind: 'delete', version: 0 }, { kind: 'update', clearedDraftVersion: 5 }, { kind: 'delete', clearedDraftVersion: 0, cipher: null }];
for (const chat of teamChats) for (const pending of [undefined, 'update', 'delete']) for (const expected of expects) for (const teamId of ['t', 'x']) {
	add('teamDraftIntent', { chat, teamId, pending, expected }, chats.applyTeamDraftIntent(chat, teamId, pending, expected));
}

const target = fileURLToPath(new URL('./policy_vectors.json', import.meta.url));
const body = Object.entries(vectors).map(([op, cases]) => `${JSON.stringify(op)}:[\n${cases.map((c) => JSON.stringify(c)).join(',\n')}\n]`).join(',\n');
writeFileSync(target, `{\n${body}\n}\n`);
console.log(Object.entries(vectors).map(([k, v]) => `${k}: ${v.length}`).join(', '));

/**
 * Scenarios for the TS-generated Rust parity vectors of the chatState view ops
 * (selection plans, unread bookkeeping, read gate, shared sub-chat metadata).
 * chatViewVectors.test.ts records what the TypeScript code does with them
 * (WRITE_CHAT_VIEW_VECTORS=1) and re-checks the committed file; web_chat_state/
 * view_tests.rs replays the same file against Rust.
 */
import type { UnreadEvent } from '../../../../stores/unreadReducer';

const bools = [false, true];

/** Every combination of the URL plan facts (hash equality is the only hash fact that matters). */
export function urlPlanCases() {
	const cases: Record<string, unknown>[] = [];
	for (const chatId of [null, '', 'chat-a']) for (const appsRoute of bools) for (const hasChatIdParam of bools)
		for (const workflowHandoff of bools) for (const onSemanticPath of bools) for (const same of bools) {
			cases.push({ chatId, appsRoute, hasChatIdParam, workflowHandoff, onSemanticPath, currentHash: '#chat-id=chat-a', targetHash: same ? '#chat-id=chat-a' : '#other=1' });
		}
	return cases;
}

export function globalSelectedCases() {
	const ids = [null, '', 'a', 'b'];
	return ids.flatMap((selected) => ids.map((active) => ({ selected, newId: 'b', active })));
}

export function draftActivationCases() {
	return [null, '', 'a', 'b'].map((selected) => ({ selected, persisted: 'b' }));
}

export function readGateCases() {
	const cases: Record<string, unknown>[] = [];
	for (const stage of ['pre', 'post']) for (const visible of bools) for (const manual of bools)
		for (const hasUnread of bools) for (const endVisible of bools) for (const stillOpen of [null, true, false]) {
			cases.push({ stage, visible, manual, hasUnread, endVisible, stillOpen });
		}
	return cases;
}

const ids = (prefix: string, count: number) => Array.from({ length: count }, (_, i) => `${prefix}${i}`);
export interface UnreadCase { name: string; events: UnreadEvent[] }
export const UNREAD_CASES: UnreadCase[] = [
	{ name: 'increment counts every call without a reply id', events: [
		{ type: 'increment', chat: 'a' }, { type: 'increment', chat: 'a' }, { type: 'increment', chat: 'b' }] },
	{ name: 'a reply is counted once across local and server signals', events: [
		{ type: 'increment', chat: 'a', messageId: 'm1' }, { type: 'increment', chat: 'a', messageId: 'm1' },
		{ type: 'set', chat: 'a', count: 3, messageId: 'm2' }, { type: 'increment', chat: 'a', messageId: 'm2' },
		{ type: 'increment', chat: 'a', messageId: 'm3' }] },
	{ name: 'empty message id counts like none', events: [
		{ type: 'increment', chat: 'a', messageId: '' }, { type: 'increment', chat: 'a', messageId: '' }] },
	{ name: 'set zero or negative removes the entry and keeps order of the rest', events: [
		{ type: 'set', chat: 'a', count: 2 }, { type: 'set', chat: 'b', count: 4 }, { type: 'set', chat: 'a', count: 0 },
		{ type: 'set', chat: 'a', count: 5 }, { type: 'set', chat: 'b', count: -1 }] },
	{ name: 'set on an existing chat keeps its position', events: [
		{ type: 'set', chat: 'a', count: 1 }, { type: 'set', chat: 'b', count: 1 }, { type: 'set', chat: 'a', count: 7 }] },
	{ name: 'manual unread is exactly one and survives increments until cleared', events: [
		{ type: 'increment', chat: 'a' }, { type: 'increment', chat: 'a' }, { type: 'mark_manual', chat: 'a' },
		{ type: 'increment', chat: 'a' }, { type: 'clear', chat: 'a' }, { type: 'increment', chat: 'a' }] },
	{ name: 'release keeps the count but drops the manual flag', events: [
		{ type: 'mark_manual', chat: 'a' }, { type: 'mark_manual', chat: 'a' }, { type: 'release_manual', chat: 'a' },
		{ type: 'release_manual', chat: 'zzz' }, { type: 'clear', chat: 'never-seen' }] },
	{ name: 'clear all resets counts, counted replies and manual flags', events: [
		{ type: 'increment', chat: 'a', messageId: 'm1' }, { type: 'mark_manual', chat: 'b' }, { type: 'clear_all' },
		{ type: 'increment', chat: 'a', messageId: 'm1' }] },
	{ name: 'only the newest 50 counted replies are remembered per chat', events: [
		...ids('r', 51).map((messageId): UnreadEvent => ({ type: 'increment', chat: 'a', messageId })),
		{ type: 'increment', chat: 'a', messageId: 'r0' }, { type: 'increment', chat: 'a', messageId: 'r50' },
		{ type: 'increment', chat: 'a', messageId: 'r1' }] },
	{ name: 'counted replies are per chat', events: [
		{ type: 'increment', chat: 'a', messageId: 'm' }, { type: 'increment', chat: 'b', messageId: 'm' }] },
];

export const SHARED_SUB_CHAT_CASES = [
	{ name: 'minimal row', row: { id: 's1', parent_id: 'p', is_sub_chat: true, created_at: 100 }, parent: { chat_id: 'p' } },
	{ name: 'full row', row: {
		id: 's2', parent_id: 'p', is_sub_chat: true, created_at: 100, updated_at: 150, last_edited_overall_timestamp: 160,
		encrypted_title: 'T', encrypted_chat_summary: 'S', encrypted_icon: 'I', encrypted_category: 'C',
		messages_v: 4, title_v: 2, metadata_v: 3, unread_count: 2, budget_limit: 5.5, budget_spent: 1.25,
	}, parent: { chat_id: 'p', share_pii: true, share_highlights: false } },
	{ name: 'nulls fall back like undefined, zero stays', row: {
		id: 's3', parent_id: 'p', is_sub_chat: true, created_at: 10, updated_at: null, last_edited_overall_timestamp: null,
		encrypted_title: null, messages_v: null, title_v: 0, unread_count: 0, budget_limit: null, budget_spent: 0,
	}, parent: { chat_id: 'p', share_pii: null, share_highlights: null } },
	{ name: 'edit time falls back to updated time', row: { id: 's4', parent_id: 'p', is_sub_chat: true, created_at: 10, updated_at: 20 }, parent: { chat_id: 'p2', share_highlights: true } },
] as const;

const fact = (over: Record<string, unknown> = {}) => ({ incognito: false, sharedByOthers: false, demo: false, legal: false, public: false, teamId: null, ...over });
export const ORGANIZABLE_CASES = [
	{ chats: [fact()], teamId: null },
	{ chats: [], teamId: null },
	{ chats: [fact(), fact({ incognito: true })], teamId: null },
	{ chats: [fact({ sharedByOthers: true })], teamId: null },
	{ chats: [fact({ demo: true })], teamId: null },
	{ chats: [fact({ legal: true })], teamId: null },
	{ chats: [fact({ public: true })], teamId: null },
	{ chats: [fact({ teamId: 't1' })], teamId: 't1' },
	{ chats: [fact({ teamId: 't1' })], teamId: null },
	{ chats: [fact()], teamId: 't1' },
];

const project = (id: string, chats: [string, string, string | null][], folders: [string, string, string | null][] = []) => ({
	id, name: id, folders: folders.map(([fid, hash, parentHash]) => ({ id: fid, hash, parentHash, name: fid })),
	chats: chats.map(([itemId, chatId, folderHash]) => ({ id: itemId, chatId, folderHash })),
});
const PA = project('pa', [['i1', 'c1', null], ['i2', 'c2', 'h-docs']], [['docs', 'h-docs', null], ['sub', 'h-sub', 'h-docs']]);
const PB = project('pb', [['i3', 'c3', null], ['i4', 'c1', null]]);
export const PLACEMENT_CASES = [
	{ chatIds: ['c1'], location: { projectId: 'zz', folderId: null }, mode: 'add', index: [PA, PB] },
	{ chatIds: ['c1'], location: { projectId: 'pa', folderId: 'gone' }, mode: 'add', index: [PA, PB] },
	{ chatIds: ['c1', 'c2', 'c9'], location: { projectId: 'pa', folderId: null }, mode: 'add', index: [PA, PB] },
	{ chatIds: ['c1', 'c2', 'c9'], location: { projectId: 'pa', folderId: 'docs' }, mode: 'add', index: [PA, PB] },
	{ chatIds: ['c1', 'c3'], location: { projectId: 'pa', folderId: 'sub' }, mode: 'move', index: [PA, PB] },
	{ chatIds: ['c1', 'c3', 'c9'], location: { projectId: 'pb', folderId: null }, mode: 'move', index: [PA, PB, project('pc', [['i5', 'c9', null]])] },
	{ chatIds: [], location: { projectId: 'pa', folderId: null }, mode: 'move', index: [PA, PB] },
	{ chatIds: ['c2'], location: { projectId: 'pa', folderId: 'docs' }, mode: 'move', index: [PA, PB] },
];

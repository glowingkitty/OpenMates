/**
 * Shared message-list / activity scenarios (edge inputs included) for the
 * TS-generated Rust parity vectors: generateTransitionVectors.mjs records what
 * the TypeScript functions do with them, transitionVectors.test.ts re-checks the
 * committed file, and web_chat_state/transition_tests.rs replays it against Rust.
 */
type Raw = Record<string, unknown>;
const row = (role: string, created_at: number | null | undefined, extra: Raw = {}): Raw => ({ role, created_at, ...extra });
const run = (count: number, from = 1000, extra: (i: number) => Raw = () => ({})) =>
	Array.from({ length: count }, (_, i) => row(i % 2 ? 'assistant' : 'user', from + i, { status: 'synced', ...extra(i) }));

export interface PruneCase { name: string; messages: Raw[]; options: Raw }
export const PRUNE_CASES: PruneCase[] = [
	{ name: 'empty', messages: [], options: {} },
	{ name: 'at the hard cap nothing is pruned', messages: run(90), options: {} },
	{ name: 'one over the hard cap prunes the middle', messages: run(91), options: {} },
	{ name: 'long window keeps first page, last page and fills toward the target', messages: run(200), options: {} },
	{ name: 'unsafe statuses survive', messages: run(200, 1000, (i) => (i === 100 ? { status: 'streaming' } : i === 101 ? { status: 'failed' } : i === 102 ? { status: 'delivered' } : {})), options: {} },
	{ name: 'every unsafe status is kept', messages: run(120, 1000, (i) => ({ status: ['sending', 'waiting_for_upload', 'waiting_for_internet', 'processing', 'streaming', 'failed', 'waiting_for_user', 'delivered', 'synced', undefined][i % 10] })), options: {} },
	{ name: 'rows without created_at are never pruned and never counted', messages: [...run(100), row('user', null, { status: 'synced' }), row('assistant', undefined, { original_message: { created_at: 5 } }), row('user', 0)], options: {} },
	{ name: 'original_message supplies created_at and category', messages: [...run(95).map((m, i) => (i === 3 ? { role: 'system', original_message: { created_at: 1003, category: 'compression_summary' } } : m))], options: {} },
	{ name: 'compression summaries are not normal rows', messages: [...run(88), row('system', 50, { category: 'compression_summary' }), row('system', 51, { category: 'compression_summary' }), row('system', 52, { category: 'other' })], options: {} },
	{ name: 'compression boundary excludes older rows', messages: run(200), options: { compressionCheckpoints: [{ created_at: 1, compressed_up_to_timestamp: 1100 }, { created_at: 5, compressed_up_to_timestamp: 1150 }] } },
	{ name: 'newest checkpoint wins, first of equals', messages: run(200), options: { compressionCheckpoints: [{ created_at: 5, compressed_up_to_timestamp: 1010 }, { created_at: 5, compressed_up_to_timestamp: 1190 }] } },
	{ name: 'checkpoint without a boundary prunes nothing extra', messages: run(120), options: { compressionCheckpoints: [{ created_at: 5 }] } },
	{ name: 'custom limits', messages: run(20), options: { pageLimit: 2, target: 6, hardCap: 8 } },
	{ name: 'limits are floored and clamped', messages: run(40), options: { pageLimit: 0, target: 3.9, hardCap: 2 } },
	{ name: 'target below page limit is raised to it', messages: run(30), options: { pageLimit: 5, target: 1, hardCap: 10 } },
	{ name: 'page limit larger than the window keeps everything', messages: run(100), options: { pageLimit: 500 } },
];

export interface PreserveCase { name: string; current: Raw[]; incoming: Raw[] }
const ids = (...list: (string | undefined)[]) => list.map((message_id) => ({ message_id }));
export const PRESERVE_CASES: PreserveCase[] = [
	{ name: 'empty incoming', current: ids('a', 'b'), incoming: [] },
	{ name: 'incoming is a suffix of a longer window', current: ids('a', 'b', 'c'), incoming: ids('b', 'c') },
	{ name: 'equal length', current: ids('a', 'b'), incoming: ids('a', 'b') },
	{ name: 'incoming has an unknown id', current: ids('a', 'b', 'c'), incoming: ids('b', 'z') },
	{ name: 'incoming id missing', current: ids('a', 'b', 'c'), incoming: ids('b', undefined) },
	{ name: 'empty id counts as missing', current: ids('a', 'b', 'c'), incoming: ids('b', '') },
	{ name: 'current ids missing are ignored', current: ids('a', undefined, 'c'), incoming: ids('a', 'c') },
	{ name: 'current shorter', current: ids('a'), incoming: ids('a', 'b') },
];

export interface TimelineCase { name: string; entries: Raw[]; bookmarks: string[]; id: string; pendingUserId?: string }
const e = (message_id: string, role: string, extra: Raw = {}): Raw => ({ message_id, role, created_at: 1, ...extra });
export const TIMELINE_CASES: TimelineCase[] = [
	{ name: 'empty', entries: [], bookmarks: [], id: 'u1' },
	{ name: 'explicit pairing', entries: [e('u1', 'user'), e('a1', 'assistant', { user_message_id: 'u1' })], bookmarks: [], id: 'u1' },
	{ name: 'legacy pairing by position', entries: [e('u1', 'user'), e('a1', 'assistant'), e('u2', 'user'), e('a2', 'assistant')], bookmarks: ['a2'], id: 'u2' },
	{ name: 'explicit wins over legacy; first of each kind', entries: [e('u1', 'user'), e('a0', 'assistant'), e('a1', 'assistant', { user_message_id: 'u1' }), e('a2', 'assistant', { user_message_id: 'u1' })], bookmarks: ['a1', 'a2'], id: 'u1' },
	{ name: 'bookmarked question marks its response', entries: [e('u1', 'user'), e('a1', 'assistant', { user_message_id: 'u1' }), e('u2', 'user')], bookmarks: ['u1', 'u2'], id: 'u2', pendingUserId: 'u2' },
	{ name: 'assistant of an unknown user is ignored', entries: [e('a0', 'assistant', { user_message_id: 'ghost' }), e('u1', 'user'), e('a1', 'assistant')], bookmarks: ['a0'], id: 'u1' },
	{ name: 'leading assistant has no user', entries: [e('a0', 'assistant'), e('u1', 'user')], bookmarks: [], id: 'u1' },
	{ name: 'system and tool rows are skipped', entries: [e('u1', 'user'), e('s1', 'system'), e('a1', 'assistant'), e('u2', 'user'), e('s2', 'system')], bookmarks: [], id: 'u1' },
	{ name: 'empty user_message_id is legacy', entries: [e('u1', 'user'), e('a1', 'assistant', { user_message_id: '' })], bookmarks: ['a1'], id: 'u1' },
	{ name: 'duplicate answers across users', entries: [e('u1', 'user'), e('a1', 'assistant', { user_message_id: 'u1' }), e('a1', 'assistant', { user_message_id: 'u1' }), e('u2', 'user'), e('a3', 'assistant')], bookmarks: ['a1', 'a3'], id: 'u2' },
	{ name: 'legacy scan stops at the next user', entries: [e('u1', 'user'), e('u2', 'user'), e('a2', 'assistant')], bookmarks: [], id: 'u1', pendingUserId: 'u1' },
	{ name: 'missing user id', entries: [e('u1', 'user')], bookmarks: [], id: 'nope', pendingUserId: 'nope' },
	{ name: 'id of an assistant row is not a user', entries: [e('u1', 'user'), e('a1', 'assistant')], bookmarks: [], id: 'a1' },
	{ name: 'answered counts explicit plus legacy only', entries: [e('u1', 'user'), e('a1', 'assistant', { user_message_id: 'u1' }), e('a1b', 'assistant'), e('u2', 'user'), e('a2', 'assistant'), e('u3', 'user')], bookmarks: [], id: 'u3' },
];

export interface MergeCase { name: string; pages: { message_id: string; created_at: number; role: string; user_message_id?: string }[][] }
const m = (message_id: string, created_at: number, role = 'user', user_message_id?: string) => ({ message_id, created_at, role, user_message_id });
export const MERGE_CASES: MergeCase[] = [
	{ name: 'no pages', pages: [] },
	{ name: 'sorted by created_at', pages: [[m('b', 3), m('a', 1)], [m('c', 2)]] },
	{ name: 'later page wins a duplicate id', pages: [[m('a', 1, 'user'), m('b', 5)], [m('a', 9, 'assistant', 'x')]] },
	{ name: 'ties break by id', pages: [[m('b2', 1), m('a1', 1), m('B1', 1), m('a-1', 1), m('a10', 1), m('a2', 1)]] },
	{ name: 'uuid-like ids', pages: [[m('c2a1b3-0001', 5), m('c2a1b3-0000', 5), m('f0000000-aaaa-4bbb-8ccc-000000000001', 5), m('0f000000-aaaa-4bbb-8ccc-000000000002', 5)]] },
	{ name: 'negative and fractional stamps', pages: [[m('x', -5), m('y', 0.5), m('z', 0.25)]] },
];

export interface ActivityCase { name: string; chats: Raw[]; running: string[] }
const c = (chat_id: string, extra: Raw = {}): Raw => ({ chat_id, ...extra });
export const ACTIVITY_CASES: ActivityCase[] = [
	{ name: 'empty', chats: [], running: [] },
	{ name: 'single running root', chats: [c('a')], running: ['a'] },
	{ name: 'unknown running ids are skipped', chats: [c('a')], running: ['ghost', 'a'] },
	{ name: 'children group under their root, root counted once', chats: [c('r'), c('k1', { parent_id: 'r' }), c('k2', { parent_id: 'r' })], running: ['k1', 'r', 'k2'] },
	{ name: 'deep chain groups under the top root', chats: [c('r'), c('m', { parent_id: 'r' }), c('l', { parent_id: 'm' })], running: ['l', 'm'] },
	{ name: 'hidden ancestor hides the group', chats: [c('r', { is_hidden: true }), c('k', { parent_id: 'r' })], running: ['k'] },
	{ name: 'hidden candidate hides', chats: [c('r'), c('k', { parent_id: 'r', is_hidden_candidate: true })], running: ['k', 'r'] },
	{ name: 'cycle terminates', chats: [c('a', { parent_id: 'b' }), c('b', { parent_id: 'a' })], running: ['a'] },
	{ name: 'missing parent makes the chat its own root', chats: [c('k', { parent_id: 'gone' })], running: ['k'] },
	{ name: 'self parent', chats: [c('a', { parent_id: 'a' })], running: ['a'] },
	{ name: 'two roots keep first-seen order', chats: [c('r1'), c('r2'), c('k', { parent_id: 'r2' })], running: ['k', 'r1', 'r2'] },
	{ name: 'duplicate chat ids use the last record', chats: [c('a'), c('b'), c('a', { parent_id: 'b' })], running: ['a'] },
	{ name: 'empty parent id is no parent', chats: [c('a', { parent_id: '' }), c('b', { parent_id: null })], running: ['a', 'b'] },
	{ name: 'ancestors of non-hidden branch beside hidden sibling', chats: [c('r'), c('h', { parent_id: 'r', is_hidden: true }), c('v', { parent_id: 'r' })], running: ['h', 'v'] },
];

import type { IndicatorState } from '../../chatState/transitionInput';

export interface IndicatorCase { name: string; state: IndicatorState }
const baseTyping = { isTyping: true, chatId: 'c1', userMessageId: 'u1', category: 'software_development', modelName: 'gpt-x', providerName: 'Acme', serverRegion: 'EU' };
const baseTurn = { chatId: 'c1', userMessageId: 'u1', explicitMateCategory: null };
const baseState = { projectKey: null, chatId: 'c1', anonymous: false, typing: null, turn: null, terminal: false, activeTaskMatches: true, phase: null, reasoning: false, displayModelName: 'GPT X' };
/** A fixed grid over every decision input, so each branch of both indicator decisions is covered. */
export const INDICATOR_CASES: IndicatorCase[] = (() => {
	const cases: IndicatorCase[] = [];
	const typings = [null, baseTyping, { ...baseTyping, isTyping: false }, { ...baseTyping, chatId: 'other' }, { ...baseTyping, category: null },
		{ ...baseTyping, userMessageId: 'u2' }, { ...baseTyping, modelName: null, providerName: null, serverRegion: null },
		{ ...baseTyping, serverRegion: 'unknown' }, { ...baseTyping, serverRegion: 'global', providerName: '' }, { ...baseTyping, chatId: null }];
	const turns = [null, baseTurn, { ...baseTurn, explicitMateCategory: 'research' }, { ...baseTurn, chatId: 'other' }, { ...baseTurn, userMessageId: 'u2' }, { ...baseTurn, chatId: null }];
	const phases = [null, { phase: 'sending', statusLines: ['Sending...'] }, { phase: 'compressing', statusLines: ['Compressing chat...', 'x'] }, { phase: 'typing', statusLines: [] }];
	typings.forEach((typing, ti) => turns.forEach((turn, ui) => phases.forEach((phase, pi) => {
		// Anonymity only matters while a phase shows; the active-task check only once typing and a turn exist.
		for (const anonymous of phase ? [false, true] : [false]) for (const activeTaskMatches of typing && turn ? [true, false] : [true]) {
			cases.push({ name: `typing${ti} turn${ui} phase${pi} anon${+anonymous} task${+activeTaskMatches}`, state: { ...baseState, typing, turn, phase, anonymous, activeTaskMatches, reasoning: (ti + ui) % 2 === 1 } });
		}
	})));
	cases.push({ name: 'project progress wins', state: { ...baseState, projectKey: 'uploading', typing: baseTyping, turn: baseTurn } });
	cases.push({ name: 'terminal turn hides', state: { ...baseState, terminal: true, typing: baseTyping, turn: baseTurn } });
	cases.push({ name: 'terminal with project progress', state: { ...baseState, terminal: true, projectKey: 'x' } });
	cases.push({ name: 'no chat id at all', state: { ...baseState, chatId: undefined, typing: { ...baseTyping, chatId: null }, turn: { ...baseTurn, chatId: null } } });
	return cases;
})();

export const TITLE_CASES: { name: string; typing: { isTyping: boolean; category: string | null } | null; skill: { appId: string; skillId: string } | null; reasoning: boolean }[] = [
	{ name: 'idle', typing: null, skill: null, reasoning: false },
	{ name: 'typing', typing: { isTyping: true, category: 'general_knowledge' }, skill: null, reasoning: false },
	{ name: 'thinking', typing: { isTyping: true, category: 'general_knowledge' }, skill: null, reasoning: true },
	{ name: 'skill beats thinking', typing: { isTyping: true, category: 'general_knowledge' }, skill: { appId: 'web', skillId: 'search' }, reasoning: true },
	{ name: 'not typing ignores skill', typing: { isTyping: false, category: 'x' }, skill: { appId: 'web', skillId: 'search' }, reasoning: false },
	{ name: 'no category', typing: { isTyping: true, category: null }, skill: { appId: 'web', skillId: 'search' }, reasoning: false },
	{ name: 'empty category', typing: { isTyping: true, category: '' }, skill: null, reasoning: true },
];

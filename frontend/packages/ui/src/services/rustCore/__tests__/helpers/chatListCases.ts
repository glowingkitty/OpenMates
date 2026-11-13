/**
 * Shared chat-list scenarios (odd inputs included) for the TS-generated Rust
 * parity vectors: generateChatListVectors.mjs records what the TypeScript
 * `sortChats` / `groupChats` do with them, chatListVectors.test.ts re-checks
 * that against the committed vectors, and web_chat_state/tests.rs replays them.
 */
export const VECTOR_TIME_ZONE = 'Europe/Berlin';
/** 2026-11-07 12:00:00 UTC; the fixed "now" of every grouping case. */
export const VECTOR_NOW_MS = Date.UTC(2026, 10, 7, 12, 0, 0);

type Raw = Record<string, unknown>;
const DAY = 86_400;
const NOW_S = VECTOR_NOW_MS / 1000;
const at = (days: number, offsetSeconds = 0) => NOW_S - days * DAY + offsetSeconds;
const chat = (id: string, extra: Raw = {}): Raw => ({ chat_id: id, ...extra });

export interface SortCase { name: string; chats: Raw[]; serverOrder: string[] }
export interface GroupCase { name: string; chats: Raw[] }

export const SORT_CASES: SortCase[] = [
	{ name: 'empty', chats: [], serverOrder: [] },
	{ name: 'single', chats: [chat('a')], serverOrder: [] },
	{ name: 'newest first by last edit', chats: [chat('old', { last_edited_overall_timestamp: 100 }), chat('new', { last_edited_overall_timestamp: 300 }), chat('mid', { last_edited_overall_timestamp: 200 })], serverOrder: [] },
	{ name: 'pinned before drafts before regular', chats: [
		chat('regular', { last_edited_overall_timestamp: 900 }),
		chat('draft', { last_edited_overall_timestamp: 100, encrypted_draft_md: 'x' }),
		chat('pinned-old', { pinned: true, last_edited_overall_timestamp: 1 }),
		chat('pinned-draft', { pinned: true, last_edited_overall_timestamp: 2, encrypted_draft_md: 'y' }),
	], serverOrder: [] },
	{ name: 'empty and null drafts are not drafts', chats: [
		chat('empty-draft', { encrypted_draft_md: '', last_edited_overall_timestamp: 5 }),
		chat('null-draft', { encrypted_draft_md: null, last_edited_overall_timestamp: 9 }),
		chat('real-draft', { encrypted_draft_md: 'z', last_edited_overall_timestamp: 1 }),
	], serverOrder: [] },
	{ name: 'missing and null timestamps count as zero', chats: [
		chat('none'), chat('null', { last_edited_overall_timestamp: null }), chat('zero', { last_edited_overall_timestamp: 0 }),
		chat('negative', { last_edited_overall_timestamp: -50 }), chat('positive', { last_edited_overall_timestamp: 1 }),
	], serverOrder: [] },
	{ name: 'server order breaks timestamp ties', chats: [
		chat('c', { last_edited_overall_timestamp: 10 }), chat('a', { last_edited_overall_timestamp: 10 }), chat('b', { last_edited_overall_timestamp: 10 }),
	], serverOrder: ['a', 'b', 'c'] },
	{ name: 'only some chats in server order', chats: [
		chat('local-1', { updated_at: 5 }), chat('known', {}), chat('local-2', { updated_at: 50 }), chat('also-known', {}),
	], serverOrder: ['also-known', 'known'] },
	{ name: 'updated_at is the last tie break', chats: [
		chat('u1', { last_edited_overall_timestamp: 7, updated_at: 1 }), chat('u2', { last_edited_overall_timestamp: 7, updated_at: 3 }),
		chat('u3', { last_edited_overall_timestamp: 7 }), chat('u4', { last_edited_overall_timestamp: 7, updated_at: 3 }),
	], serverOrder: [] },
	{ name: 'duplicate ids and duplicate server order entries', chats: [
		chat('dup', { last_edited_overall_timestamp: 1 }), chat('dup', { last_edited_overall_timestamp: 1 }), chat('other', { last_edited_overall_timestamp: 1 }),
	], serverOrder: ['other', 'dup', 'other', 'dup'] },
	{ name: 'server order ids with no chat are ignored', chats: [chat('x', { last_edited_overall_timestamp: 2 }), chat('y', { last_edited_overall_timestamp: 2 })], serverOrder: ['ghost', 'y', 'x'] },
	{ name: 'millisecond and huge timestamps', chats: [
		chat('ms', { last_edited_overall_timestamp: 1_700_000_000_000 }), chat('s', { last_edited_overall_timestamp: 1_700_000_000 }),
		chat('huge', { last_edited_overall_timestamp: 9_007_199_254_740_991 }), chat('fraction', { last_edited_overall_timestamp: 1_700_000_000.5 }),
	], serverOrder: [] },
	{ name: 'truthy non-boolean pinned values', chats: [
		chat('p0', { pinned: 0, last_edited_overall_timestamp: 9 }), chat('p1', { pinned: 1, last_edited_overall_timestamp: 1 }),
		chat('pf', { pinned: false, last_edited_overall_timestamp: 8 }), chat('pn', { pinned: null, last_edited_overall_timestamp: 7 }),
	], serverOrder: [] },
	{ name: 'identical chats keep input order', chats: [chat('s1'), chat('s2'), chat('s3'), chat('s4')], serverOrder: [] },
	{ name: 'many chats mixed', chats: Array.from({ length: 40 }, (_, i) => chat(`m${i}`, {
		pinned: i % 7 === 0, encrypted_draft_md: i % 5 === 0 ? 'd' : '', last_edited_overall_timestamp: (i * 37) % 11, updated_at: (i * 13) % 5,
	})), serverOrder: ['m3', 'm11', 'm2', 'm30'] },
];

export const GROUP_CASES: GroupCase[] = [
	{ name: 'empty', chats: [] },
	{ name: 'time buckets', chats: [
		chat('today', { last_edited_overall_timestamp: at(0) }), chat('yesterday', { last_edited_overall_timestamp: at(1) }),
		chat('d3', { last_edited_overall_timestamp: at(3) }), chat('d6', { last_edited_overall_timestamp: at(6) }),
		chat('d7', { last_edited_overall_timestamp: at(7) }), chat('d29', { last_edited_overall_timestamp: at(29) }),
		chat('d30', { last_edited_overall_timestamp: at(30) }), chat('d400', { last_edited_overall_timestamp: at(400) }),
	] },
	{ name: 'month groups and order of first appearance', chats: [
		chat('feb', { last_edited_overall_timestamp: Date.UTC(2026, 1, 3, 10) / 1000 }), chat('today', { last_edited_overall_timestamp: at(0) }),
		chat('jan', { last_edited_overall_timestamp: Date.UTC(2026, 0, 31, 23) / 1000 }), chat('feb2', { last_edited_overall_timestamp: Date.UTC(2026, 1, 20, 10) / 1000 }),
		chat('dec25', { last_edited_overall_timestamp: Date.UTC(2025, 11, 31, 23, 30) / 1000 }),
	] },
	{ name: 'explicit group keys override time', chats: [
		chat('intro', { group_key: 'intro', last_edited_overall_timestamp: at(0) }), chat('plain', { last_edited_overall_timestamp: at(0) }),
		chat('legal', { group_key: 'legal' }), chat('intro2', { group_key: 'intro' }), chat('empty-key', { group_key: '', last_edited_overall_timestamp: at(2) }),
	] },
	{ name: 'missing, zero, null and invalid timestamps are today', chats: [
		chat('none'), chat('zero', { last_edited_overall_timestamp: 0 }), chat('null', { last_edited_overall_timestamp: null }),
		chat('nan', { last_edited_overall_timestamp: Number.NaN }), chat('too-big', { last_edited_overall_timestamp: 9e15 }),
	] },
	{ name: 'future timestamps land in previous_7_days', chats: [
		chat('tomorrow', { last_edited_overall_timestamp: at(-1) }), chat('next-month', { last_edited_overall_timestamp: at(-40) }),
	] },
	{ name: 'local midnight boundaries (Europe/Berlin)', chats: [
		chat('23:59 yesterday', { last_edited_overall_timestamp: Date.UTC(2026, 10, 6, 22, 59, 59) / 1000 }),
		chat('00:00 today', { last_edited_overall_timestamp: Date.UTC(2026, 10, 6, 23, 0, 0) / 1000 }),
		chat('23:59 today', { last_edited_overall_timestamp: Date.UTC(2026, 10, 7, 22, 59, 59) / 1000 }),
	] },
	{ name: 'daylight-saving change window', chats: [
		chat('before dst end', { last_edited_overall_timestamp: Date.UTC(2026, 9, 25, 0, 30) / 1000 }),
		chat('after dst end', { last_edited_overall_timestamp: Date.UTC(2026, 9, 25, 2, 30) / 1000 }),
		chat('week before', { last_edited_overall_timestamp: Date.UTC(2026, 9, 31, 12) / 1000 }),
	] },
	{ name: 'millisecond timestamps and epoch edges', chats: [
		chat('ms-today', { last_edited_overall_timestamp: VECTOR_NOW_MS - 1000 }), chat('epoch-1s', { last_edited_overall_timestamp: 1 }),
		chat('negative', { last_edited_overall_timestamp: -86_400 * 400 }), chat('1e10 boundary', { last_edited_overall_timestamp: 10_000_000_000 }),
		chat('just under 1e10', { last_edited_overall_timestamp: 9_999_999_999 }),
	] },
];

/**
 * Regenerates packages/openmates-rust/src/web_chat_state/ts_vectors.json from the
 * TypeScript `sortChats` and the `chatTimeGroupKey` grouping the web app runs.
 * Run from the repo root (Node 22.18+ strips types):
 *   TZ=Europe/Berlin node frontend/packages/ui/src/services/rustCore/__tests__/helpers/generateChatListVectors.mjs
 * chatListVectors.test.ts runs the real `groupChats` against the committed file,
 * so a drift between this generator and the shipped grouping fails there.
 */
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { sortChats } from '../../../../components/chats/utils/chatSortUtils.ts';
import { buildGroupInput, buildSortInput } from '../../../../components/chats/utils/chatListInput.ts';
import { chatTimeGroupKey } from '../../../../utils/chatTimeGroups.ts';
import { GROUP_CASES, SORT_CASES, VECTOR_NOW_MS, VECTOR_TIME_ZONE } from './chatListCases.ts';

if (process.env.TZ !== VECTOR_TIME_ZONE) throw new Error(`run with TZ=${VECTOR_TIME_ZONE}`);
const now = new Date(VECTOR_NOW_MS);
/** The grouping of chatGroupUtils.groupChats (it only adds svelte-i18n imports), as chat indices. */
function groupIndices(chats) {
	const groups = new Map();
	chats.forEach((chat, index) => {
		const key = chat.group_key ? String(chat.group_key) : chatTimeGroupKey(chat.last_edited_overall_timestamp, now);
		groups.set(key, [...(groups.get(key) ?? []), index]);
	});
	return [...groups];
}

const withIndex = (chats) => chats.map((chat, index) => ({ ...chat, __index: index }));
const sort = SORT_CASES.map((c) => {
	const sorted = sortChats(withIndex(c.chats), c.serverOrder);
	return { name: c.name, chats: c.chats, serverOrder: c.serverOrder, input: buildSortInput(c.chats, c.serverOrder), out: sorted.map((x) => x.__index) };
});
const group = GROUP_CASES.map((c) => ({ name: c.name, chats: c.chats, input: buildGroupInput(c.chats, now), out: groupIndices(c.chats) }));
const target = resolve(import.meta.dirname, '../../../../../../../../packages/openmates-rust/src/web_chat_state/ts_vectors.json');
writeFileSync(target, `${JSON.stringify({ nowMs: VECTOR_NOW_MS, timeZone: VECTOR_TIME_ZONE, sort, group }, null, 1)}\n`);
console.log(`wrote ${sort.length} sort and ${group.length} group vectors`);

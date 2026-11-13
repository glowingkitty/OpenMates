/**
 * Regenerates packages/openmates-rust/src/web_chat_state/transition_vectors.json
 * from the TypeScript the web app runs with the flag off (messageWindowPruning,
 * chatTimeline, chatActivity) and the indicatorReference transcription. Run from
 * the repo root (Node 22.18+ strips types):
 *   node --import ./frontend/packages/ui/src/services/rustCore/__tests__/helpers/registerTsResolve.mjs frontend/packages/ui/src/services/rustCore/__tests__/helpers/generateTransitionVectors.mjs
 * transitionVectors.test.ts replays the committed file against the same code.
 */
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pruneDecryptedMessageWindow, shouldPreserveExpandedMessageWindow } from '../../../../utils/messageWindowPruning.ts';
import { buildTimelineExchangeIndex, mergeTimelineEntries, pairTimelineExchange, timelineResponseId } from '../../../../utils/chatTimeline.ts';
import { aggregateRunningChats, processingAncestorIds } from '../../../../utils/chatActivity.ts';
import { buildComposerIndicatorInput, buildPruneInput, buildTitleIndicatorInput, messageIds, timelineRows } from '../../chatState/transitionInput.ts';
import { referenceComposer, referenceTitle } from './indicatorReference.ts';
import { ACTIVITY_CASES, INDICATOR_CASES, MERGE_CASES, PRESERVE_CASES, PRUNE_CASES, TIMELINE_CASES, TITLE_CASES } from './transitionCases.ts';

const out = {};
out.prune = PRUNE_CASES.map((c) => {
	const indexed = c.messages.map((m, i) => ({ ...m, __i: i }));
	const result = pruneDecryptedMessageWindow(indexed, c.options);
	return { name: c.name, input: JSON.parse(JSON.stringify(buildPruneInput(c.messages, c.options))), out: result.messages.map((m) => m.__i) };
});
out.preserve = PRESERVE_CASES.map((c) => ({ name: c.name, input: { current: messageIds(c.current), incoming: messageIds(c.incoming) }, out: shouldPreserveExpandedMessageWindow(c.current, c.incoming) }));
out.merge = MERGE_CASES.map((c) => {
	const flat = c.pages.flat();
	const merged = mergeTimelineEntries(...c.pages.map((p) => p.map((r, i) => ({ ...r, __k: `${p.indexOf(r)}` }))));
	// index of the winning flat row: the last row with that id
	const winner = (id) => flat.map((r, i) => [r, i]).filter(([r]) => r.message_id === id).pop()[1];
	return { name: c.name, input: { pages: c.pages.map((p) => p.map((r) => ({ id: r.message_id, createdAt: r.created_at }))) }, out: merged.map((r) => winner(r.message_id)) };
});
out.timeline = TIMELINE_CASES.map((c) => {
	const index = buildTimelineExchangeIndex(c.entries, new Set(c.bookmarks));
	const questionIdx = c.entries.map((x, i) => [x, i]).filter(([x]) => x.role === 'user').map(([, i]) => i);
	let pair;
	try {
		const p = pairTimelineExchange(c.entries, c.id, c.pendingUserId);
		pair = { user: c.entries.indexOf(p.user), assistant: p.assistant ? c.entries.indexOf(p.assistant) : null, pending: p.pending };
	} catch (error) {
		pair = { error: error.message.includes('unavailable') ? 'unavailable' : 'undecryptable' };
	}
	return {
		name: c.name,
		entries: timelineRows(c.entries), bookmarks: c.bookmarks, id: c.id, pendingUserId: c.pendingUserId ?? null,
		index: {
			exchanges: index.entries.map((x, n) => [questionIdx[n], x.response_id ?? null, x.bookmarked]),
			answeredCount: index.answeredCount, assistantBookmarks: [...index.assistantBookmarks], legacyAliases: [...index.legacyAliases],
			assistantUsers: [...index.assistantUsers], bookmarkedExchanges: [...index.bookmarkedExchanges],
		},
		response: timelineResponseId(c.entries, c.id), pair,
	};
});
const activityInput = (c) => ({ chats: c.chats.map((x) => ({ id: x.chat_id, parent: x.parent_id || null, hidden: !!(x.is_hidden || x.is_hidden_candidate) })), running: c.running });
out.activity = ACTIVITY_CASES.map((c) => {
	const running = new Set(c.running);
	const groups = aggregateRunningChats(c.chats, running);
	// Root index: the last chat record carrying the root id (Map semantics).
	const last = (id) => c.chats.map((x, i) => [x, i]).filter(([x]) => x.chat_id === id).pop()[1];
	return { name: c.name, input: activityInput(c), ancestors: [...processingAncestorIds(c.chats, running)], aggregate: groups.map((g) => [last(g.chat.chat_id), g.activeSubChatCount]) };
});
// The grid is large; keep one case per distinct (outcome, branch inputs) so every branch stays covered.
const seen = new Set();
out.composer = INDICATOR_CASES.map((c) => {
	const state = c.state;
	return { name: c.name, input: buildComposerIndicatorInput(state), out: referenceComposer(state) };
}).filter((c) => {
	const { typing, ...rest } = c.input;
	const key = JSON.stringify([c.out, rest, typing.active, typing.chatMatch, !!typing.category, !!typing.providerName, typing.serverRegion]);
	return !seen.has(key) && seen.add(key);
});
out.title = TITLE_CASES.map((c) => ({ name: c.name, input: buildTitleIndicatorInput(c.typing, c.skill, c.reasoning), out: referenceTitle(c.typing, c.skill, c.reasoning) }));
const target = resolve(import.meta.dirname, '../../../../../../../../packages/openmates-rust/src/web_chat_state/transition_vectors.json');
// One case per line keeps the committed file reviewable.
const body = Object.entries(out).map(([key, cases]) => ` ${JSON.stringify(key)}: [\n${cases.map((c) => `  ${JSON.stringify(c)}`).join(',\n')}\n ]`).join(',\n');
writeFileSync(target, `{\n${body}\n}\n`);
console.log(Object.entries(out).map(([k, v]) => `${v.length} ${k}`).join(', '));

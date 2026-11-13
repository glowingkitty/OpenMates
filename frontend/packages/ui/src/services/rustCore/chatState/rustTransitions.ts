/**
 * Flag-on (VITE_OPENMATES_RUST_CORE) message-list transitions, running-chat
 * activity and typing/streaming indicators: the page adapter over the shared
 * Rust core Worker `chatState` unit. Loaded only by guarded branches, so
 * default builds never bundle it. Rust (packages/openmates-rust/src/web_chat_state)
 * decides; the page keeps message objects, stores, translations and rendering.
 * There is no TypeScript fallback: a refused or failed call rejects with its fixed code.
 */
import type { Chat, Message } from '../../../types/chat';
import type { TimelineEntry, TimelinePreview } from '../../../utils/chatTimeline';
import { chatStateCall } from './chatListUnitClient';
import { buildComposerIndicatorInput, buildPruneInput, buildTitleIndicatorInput, messageIds, timelineRows, type IndicatorState, type PrunableRow, type PruneOptions } from './transitionInput';
import type {
	ActivityInput, ComposerIndicatorOutput, ExchangeIndexOutput, IndicatorLine,
} from './transitionProtocol';

export async function rustPruneWindow<T extends PrunableRow>(messages: T[], options: PruneOptions = {}): Promise<{ messages: T[]; prunedCount: number }> {
	const kept = await chatStateCall('windowPrune', buildPruneInput(messages, options));
	if (kept.length === messages.length) return { messages, prunedCount: 0 };
	return { messages: kept.map((index) => messages[index]), prunedCount: messages.length - kept.length };
}

export const rustPreserveExpandedWindow = (current: readonly { message_id?: string }[], incoming: readonly { message_id?: string }[]): Promise<boolean> =>
	chatStateCall('windowPreserve', { current: messageIds(current), incoming: messageIds(incoming) });

/** `reconcileRecentChatMessages` (recentChatWindowCache.ts) with the preserve decision made by Rust. */
export async function rustReconcileRecentChatMessages(current: Message[], incoming: Message[], hasMoreBefore: boolean): Promise<Message[]> {
	if (!hasMoreBefore || !(await rustPreserveExpandedWindow(current, incoming))) return incoming;
	const freshById = new Map(incoming.map((message) => [message.message_id, message]));
	return current.map((message) => freshById.get(message.message_id) ?? message);
}

export async function rustMergeTimelineEntries(...pages: TimelineEntry[][]): Promise<TimelineEntry[]> {
	const flat = pages.flat();
	const order = await chatStateCall('timelineMerge', { pages: pages.map((page) => page.map((row) => ({ id: row.message_id, createdAt: row.created_at }))) });
	return order.map((index) => ({
		message_id: flat[index].message_id, created_at: flat[index].created_at, role: flat[index].role, user_message_id: flat[index].user_message_id,
	}));
}

export async function rustTimelineExchangeIndex(entries: TimelineEntry[], bookmarks: ReadonlySet<string>) {
	const out: ExchangeIndexOutput = await chatStateCall('timelineIndex', { entries: timelineRows(entries), bookmarks: [...bookmarks] });
	return {
		entries: out.exchanges.map(([index, responseId, bookmarked]) => ({ ...entries[index], response_id: responseId ?? undefined, bookmarked })),
		answeredCount: out.answeredCount,
		assistantBookmarks: new Set(out.assistantBookmarks),
		legacyAliases: new Map(out.legacyAliases),
		assistantUsers: new Map(out.assistantUsers),
		bookmarkedExchanges: new Set(out.bookmarkedExchanges),
	};
}

export const rustTimelineResponseId = (entries: TimelineEntry[], id: string): Promise<string | null> =>
	chatStateCall('timelineResponse', { entries: timelineRows(entries), id });

export async function rustPairTimelineExchange(messages: Message[], id: string, pendingUserId?: string): Promise<TimelinePreview> {
	const user = messages.find((message) => message.message_id === id && message.role === 'user');
	const out = await chatStateCall('timelinePair', {
		entries: timelineRows(messages), id, pendingUserId: pendingUserId ?? null, undecryptable: !!(user?.encrypted_content && !user.content),
	});
	if ('error' in out) throw new Error(out.error === 'unavailable' ? 'Timeline exchange unavailable' : 'Timeline message could not be decrypted');
	return { user: messages[out.user], assistant: out.assistant === null ? null : messages[out.assistant], pending: out.pending };
}

type ActivityChat = Pick<Chat, 'chat_id'> & { parent_id?: string | null; is_hidden?: boolean; is_hidden_candidate?: boolean };
const activityInput = (chats: readonly ActivityChat[], running: ReadonlySet<string>): ActivityInput => ({
	chats: chats.map((chat) => ({ id: chat.chat_id, parent: chat.parent_id || null, hidden: !!(chat.is_hidden || chat.is_hidden_candidate) })),
	running: [...running],
});

export async function rustProcessingAncestorIds(chats: readonly ActivityChat[], running: ReadonlySet<string>): Promise<Set<string>> {
	return new Set(await chatStateCall('activityAncestors', activityInput(chats, running)));
}

export async function rustAggregateRunningChats<T extends ActivityChat>(chats: readonly T[], running: ReadonlySet<string>): Promise<{ chat: T; activeSubChatCount: number }[]> {
	// Root indices refer to the de-duplicated (last wins) chat records, which are the input positions.
	const groups = await chatStateCall('activityAggregate', activityInput(chats, running));
	return groups.map(([index, activeSubChatCount]) => ({ chat: chats[index], activeSubChatCount }));
}

/** Composer indicator for the resolved ActiveChat state (see `IndicatorState`). */
export const rustComposerIndicator = (state: IndicatorState): Promise<ComposerIndicatorOutput> => chatStateCall('indicatorComposer', buildComposerIndicatorInput(state));
/** Chat-row title indicator (see `buildTitleIndicatorInput`). */
export const rustTitleIndicator = (typing: { isTyping: boolean; category: string | null } | null, skill: { appId: string; skillId: string } | null, reasoning: boolean): Promise<IndicatorLine | null> =>
	chatStateCall('indicatorTitle', buildTitleIndicatorInput(typing, skill, reasoning));

// frontend/packages/ui/src/services/continueCarouselRust.ts
// spec: specifications/features/continue-carousel#continue-carousel.chat.reminder-gated
// Flag-on (VITE_OPENMATES_RUST_CORE=1) twins of the two continue-carousel helpers the
// welcome screen calls from its async loadPriorityContinueItems: the reminder index by
// chat and the priority sort, answered by the shared Rust core (web_continue) on the
// Worker `chatState` unit with no TypeScript fallback. Flag-off builds keep calling
// continueCarouselService.ts synchronously, so call sites read
// `CONTINUE_RUST_CORE ? await xRust(...) : x(...)` and the default path gains no await.
// The CLI home and saved-item classification stay on continueCarouselService.ts.
// Only reminder trigger times, statuses and target chat IDs cross to the Worker.
import type { ActiveReminderForContinue, ContinuePriority } from './continueCarouselService';

/** Compile-time flag: the bundler drops the Rust branch from default builds. */
export const CONTINUE_RUST_CORE = import.meta.env.VITE_OPENMATES_RUST_CORE === '1';

type ChatReminderMap = Map<string, { reminder: ActiveReminderForContinue; priority: ContinuePriority }>;

/** The `reminderByChat` input: the reminder fields the index reads, in input order. */
export function reminderByChatInput(reminders: readonly ActiveReminderForContinue[], nowMs: number): unknown {
	return {
		reminders: reminders.map((r) => ({ trigger_at: r.trigger_at ?? null, status: r.status ?? null, target_chat_id: r.target_chat_id ?? null })),
		nowMs,
	};
}

/** The `sortPriorities` input: each item's priority reason and timestamp, in input order. */
export function sortPrioritiesInput(items: readonly { priority: ContinuePriority }[], nowMs: number): unknown {
	return { priorities: items.map(({ priority }) => ({ reason: priority.reason, timestamp: priority.timestamp })), nowMs };
}

interface ReminderByChatAnswer {
	entries: { chatId: string; reminderIndex: number; priority: ContinuePriority }[];
}

async function decide(op: 'reminderByChat' | 'sortPriorities', input: unknown): Promise<unknown> {
	// Dynamic import keeps the Worker client out of flag-off bundles (rustPlacement.ts pattern).
	const { chatStateCall } = await import('./rustCore/chatState/chatListUnitClient');
	return chatStateCall('continueDecide', { op, input });
}

/** `getReminderByTargetChatId` answered by the shared Rust core (flag-on only). */
export async function getReminderByTargetChatIdRust(
	reminders: ActiveReminderForContinue[], nowMs: number,
): Promise<ChatReminderMap> {
	const answer = (await decide('reminderByChat', reminderByChatInput(reminders, nowMs))) as ReminderByChatAnswer;
	return new Map(answer.entries.map((e) => [e.chatId, { reminder: reminders[e.reminderIndex], priority: e.priority }]));
}

/** `sortContinuePriorityItems` answered by the shared Rust core (flag-on only). */
export async function sortContinuePriorityItemsRust<T extends { priority: ContinuePriority }>(items: T[], nowMs: number): Promise<T[]> {
	const answer = (await decide('sortPriorities', sortPrioritiesInput(items, nowMs))) as { order: number[] };
	return answer.order.map((index) => items[index]);
}

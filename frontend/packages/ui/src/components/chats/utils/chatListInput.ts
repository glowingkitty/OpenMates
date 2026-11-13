/**
 * Page-side normalisation of chats into the small records the shared chat-list
 * policy decides on. Pure and dependency-free: it reads chat fields (so a caller
 * inside a Svelte effect tracks them) and the local calendar, which Rust has no
 * access to. Used only by the flag-on branches of Chats.svelte, ActiveChat.svelte
 * and SearchResults.svelte; the decisions themselves live in
 * packages/openmates-rust/src/web_chat_state.
 */
import type { Chat as ChatType } from '../../../types/chat';

export type CalendarDay = [year: number, month: number, day: number];

export interface SortChatsInput {
	chats: { id: string; pinned: boolean; draft: boolean; timestamp: number; updated: number }[];
	serverOrder: string[];
}

export interface GroupChatsInput {
	chats: { group: string | null; day: CalendarDay | null }[];
	today: CalendarDay;
}

/** `value || 0` for a timestamp; non-finite junk counts as 0 (never occurs in typed chats). */
function stamp(value: number | null | undefined): number {
	const number = Number(value || 0);
	return Number.isFinite(number) ? number : 0;
}

/** Local calendar date of a chat timestamp exactly as `chatTimeGroupKey` reads it; null means "today". */
export function localCalendarDay(timestamp: number | null | undefined): CalendarDay | null {
	if (!timestamp) return null;
	const value = timestamp < 10_000_000_000 ? timestamp * 1000 : timestamp;
	const date = new Date(value);
	if (!Number.isFinite(date.getTime())) return null;
	return [date.getFullYear(), date.getMonth() + 1, date.getDate()];
}

export function buildSortInput(chats: readonly ChatType[], serverOrder: readonly string[]): SortChatsInput {
	return {
		chats: chats.map((chat) => ({
			id: chat.chat_id,
			pinned: !!chat.pinned,
			draft: !!(chat.encrypted_draft_md && chat.encrypted_draft_md.length > 0),
			timestamp: stamp(chat.last_edited_overall_timestamp),
			updated: stamp(chat.updated_at),
		})),
		serverOrder: [...serverOrder],
	};
}

export function buildGroupInput(chats: readonly ChatType[], now: Date = new Date()): GroupChatsInput {
	return {
		chats: chats.map((chat) => ({
			group: chat.group_key ? String(chat.group_key) : null,
			day: localCalendarDay(chat.last_edited_overall_timestamp),
		})),
		today: [now.getFullYear(), now.getMonth() + 1, now.getDate()],
	};
}

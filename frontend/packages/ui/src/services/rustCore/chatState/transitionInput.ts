/**
 * Page-side normalisation for the chatState transition operations
 * (transitionProtocol.ts). Pure and dependency-free: it reads message, chat and
 * store fields (so a caller inside a Svelte effect tracks them) and resolves the
 * JS fallbacks (`created_at ?? original_message.created_at`, falsy ids) that
 * the Rust policy in packages/openmates-rust/src/web_chat_state does not see.
 * Imported by the flag-on adapter and by the parity-vector generator only.
 */
import type { ChatCompressionCheckpoint, Message, MessageStatus } from '../../../types/chat';
import type { ComposerIndicatorInput, PruneInput, TimelineRow, TitleIndicatorInput } from './transitionProtocol';

export type PrunableRow = {
	role: string; status?: MessageStatus | string; category?: string; created_at?: number | null;
	original_message?: { created_at?: number | null; category?: string } | null;
};
export interface PruneOptions { compressionCheckpoints?: ChatCompressionCheckpoint[]; pageLimit?: number; target?: number; hardCap?: number }

export function buildPruneInput(messages: readonly PrunableRow[], options: PruneOptions = {}): PruneInput {
	return {
		messages: messages.map((message) => ({
			role: message.role,
			status: message.status || null,
			category: message.category ?? message.original_message?.category ?? null,
			createdAt: message.created_at ?? message.original_message?.created_at ?? null,
		})),
		checkpoints: (options.compressionCheckpoints ?? []).map((cp) => ({ createdAt: cp.created_at, upTo: cp.compressed_up_to_timestamp ?? null })),
		pageLimit: options.pageLimit, target: options.target, hardCap: options.hardCap,
	};
}

export const messageIds = (messages: readonly { message_id?: string }[]): (string | null)[] =>
	messages.map((message) => message.message_id || null);

type RowLike = Pick<Message, 'message_id' | 'role'> & { user_message_id?: string };
export const timelineRows = (entries: readonly RowLike[]): TimelineRow[] =>
	entries.map((entry) => ({ id: entry.message_id, role: entry.role, userMessageId: entry.user_message_id || null }));

export interface TypingState {
	isTyping: boolean; chatId: string | null; userMessageId?: string | null; category: string | null;
	modelName?: string | null; providerName?: string | null; serverRegion?: string | null;
}
export interface IndicatorState {
	/** `projectFileProgressKey` when the project file progress belongs to this chat, else null. */
	projectKey: string | null;
	chatId: string | null | undefined;
	anonymous: boolean;
	typing: TypingState | null;
	turn: { chatId: string | null; userMessageId: string; explicitMateCategory?: string | null } | null;
	terminal: boolean;
	/** `chatSyncService.getActiveAIUserMessageIdForChat(typing.chatId) === typing.userMessageId` (false without a typing chat). */
	activeTaskMatches: boolean;
	phase: { phase: string; statusLines: string[] } | null;
	reasoning: boolean;
	displayModelName: string | null;
}

/** The ActiveChat composer indicator state resolved into the Rust request (`typingStatusMatchesProcessingFeedback` included). */
export function buildComposerIndicatorInput(s: IndicatorState): ComposerIndicatorInput {
	const typing = s.typing;
	const matches = typing?.isTyping === true && typing.chatId === s.chatId && typing.userMessageId === s.turn?.userMessageId
		&& s.turn?.chatId === s.chatId && s.activeTaskMatches;
	return {
		projectProgress: s.projectKey,
		terminal: s.terminal,
		feedbackThisChat: !!s.turn && s.turn.chatId === s.chatId,
		feedbackPresent: !!s.turn,
		explicitMate: !!s.turn?.explicitMateCategory,
		typingMatchesFeedback: matches,
		phase: s.phase?.phase ?? null,
		phaseLines: s.phase?.statusLines ?? [],
		anonymous: s.anonymous,
		typing: {
			active: typing?.isTyping === true,
			chatMatch: typing?.chatId === s.chatId,
			category: typing?.category ?? null,
			providerName: typing?.providerName ?? null,
			serverRegion: typing?.serverRegion ?? null,
			reasoning: s.reasoning,
			displayModelName: typing?.modelName ? s.displayModelName : null,
		},
	};
}

export function buildTitleIndicatorInput(typing: { isTyping: boolean; category: string | null } | null, skill: { appId: string; skillId: string } | null, reasoning: boolean): TitleIndicatorInput {
	return { active: typing?.isTyping === true, category: typing?.category ?? null, skill: skill ? { appId: skill.appId, skillId: skill.skillId } : null, reasoning };
}

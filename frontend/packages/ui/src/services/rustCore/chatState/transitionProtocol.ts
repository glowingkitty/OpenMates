/**
 * `chatState` unit operations for message-list transitions, running-chat
 * activity and typing/streaming indicators. The decisions live in
 * packages/openmates-rust/src/web_chat_state ({window,timeline,activity,indicators}.rs);
 * the page sends normalised identity/flag records (transitionInput.ts) and
 * applies the answers (indices, ids, line specs) to its own objects.
 */
import type { UnitProtocol } from '../host/unitPort';

export interface PruneInput {
	messages: { role: string; status: string | null; category: string | null; createdAt: number | null }[];
	checkpoints: { createdAt: number; upTo: number | null }[];
	pageLimit?: number; target?: number; hardCap?: number;
}
export interface PreserveInput { current: (string | null)[]; incoming: (string | null)[] }
export interface TimelineRow { id: string; role: string; userMessageId: string | null }
export interface MergeInput { pages: { id: string; createdAt: number }[][] }
export interface ExchangeIndexInput { entries: TimelineRow[]; bookmarks: string[] }
export interface ExchangeIndexOutput {
	exchanges: [number, string | null, boolean][]; answeredCount: number; assistantBookmarks: string[];
	legacyAliases: [string, string[]][]; assistantUsers: [string, string][]; bookmarkedExchanges: string[];
}
export interface ResponseInput { entries: TimelineRow[]; id: string }
export interface PairInput { entries: TimelineRow[]; id: string; pendingUserId: string | null; undecryptable: boolean }
export type PairOutput = { error: 'unavailable' | 'undecryptable' } | { user: number; assistant: number | null; pending: boolean };
export interface ActivityInput { chats: { id: string; parent: string | null; hidden: boolean }[]; running: string[] }
export interface ComposerIndicatorInput {
	projectProgress: string | null; terminal: boolean; feedbackThisChat: boolean; feedbackPresent: boolean;
	explicitMate: boolean; typingMatchesFeedback: boolean; phase: string | null; phaseLines: string[]; anonymous: boolean;
	typing: {
		active: boolean; chatMatch: boolean; category: string | null; providerName: string | null;
		serverRegion: string | null; reasoning: boolean; displayModelName: string | null;
	};
}
export type IndicatorLine =
	| { k: 'key'; key: string } | { k: 'literal'; text: string }
	| { k: 'mate'; category: string; thinking: boolean } | { k: 'skill'; appId: string; skillId: string };
export interface ComposerIndicatorOutput { lines: IndicatorLine[]; statusType: 'typing' | 'processing' | null }
export interface TitleIndicatorInput {
	active: boolean; category: string | null; skill: { appId: string; skillId: string } | null; reasoning: boolean;
}

export interface TransitionUnitProtocol extends UnitProtocol {
	windowPrune: { request: PruneInput; response: number[] };
	windowPreserve: { request: PreserveInput; response: boolean };
	timelineMerge: { request: MergeInput; response: number[] };
	timelineIndex: { request: ExchangeIndexInput; response: ExchangeIndexOutput };
	timelineResponse: { request: ResponseInput; response: string | null };
	timelinePair: { request: PairInput; response: PairOutput };
	activityAncestors: { request: ActivityInput; response: string[] };
	activityAggregate: { request: ActivityInput; response: [number, number][] };
	indicatorComposer: { request: ComposerIndicatorInput; response: ComposerIndicatorOutput };
	indicatorTitle: { request: TitleIndicatorInput; response: IndicatorLine | null };
}

/** Worker module exports of browser_chat_state_transitions.rs (JSON text in, JSON text out). */
export interface TransitionBinding {
	chat_state_window_prune(input: string): string;
	chat_state_window_preserve(input: string): string;
	chat_state_timeline_merge(input: string): string;
	chat_state_timeline_index(input: string): string;
	chat_state_timeline_response(input: string): string;
	chat_state_timeline_pair(input: string): string;
	chat_state_activity_ancestors(input: string): string;
	chat_state_activity_aggregate(input: string): string;
	chat_state_indicator_composer(input: string): string;
	chat_state_indicator_title(input: string): string;
}

/** Operation to binding export. */
export const TRANSITION_OPS: Readonly<Record<keyof TransitionUnitProtocol & string, keyof TransitionBinding>> = Object.freeze({
	windowPrune: 'chat_state_window_prune',
	windowPreserve: 'chat_state_window_preserve',
	timelineMerge: 'chat_state_timeline_merge',
	timelineIndex: 'chat_state_timeline_index',
	timelineResponse: 'chat_state_timeline_response',
	timelinePair: 'chat_state_timeline_pair',
	activityAncestors: 'chat_state_activity_ancestors',
	activityAggregate: 'chat_state_activity_aggregate',
	indicatorComposer: 'chat_state_indicator_composer',
	indicatorTitle: 'chat_state_indicator_title',
});

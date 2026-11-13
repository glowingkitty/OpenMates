/**
 * Builds the chat view parity vectors from injected TypeScript implementations, so
 * the vitest drift check (chatViewVectors.test.ts) and the node generator
 * (generateChatViewVectors.mjs) produce the same document.
 */
import type { UnreadEvent } from '../../../../stores/unreadReducer';
import type * as Cases from './chatViewCases';

export interface ChatViewDeps {
	/** The chatViewCases module (injected so plain Node can load this file without extensions). */
	cases: typeof Cases;
	planUrlUpdate: (facts: never) => unknown;
	planGlobalSelected: (facts: never) => unknown;
	skipDraftActivation: (selected: string | null, persisted: string) => boolean;
	readGateAllows: (facts: never) => boolean;
	sharedSubChatToChat: (row: never, parent: never) => unknown;
	chatsOrganizable: (input: never) => unknown;
	planPlacement: (input: never) => unknown;
	unread: {
		apply: (event: UnreadEvent) => void;
		counts: () => [string, number][];
		isManual: (chat: string) => boolean;
		count: (chat: string) => number;
		/** `hasUnread()` of chatReadState. */
		hasUnread: (chat: string, persisted: number | undefined) => boolean;
	};
}

const json = <T>(value: T): T => JSON.parse(JSON.stringify(value));

export function buildChatViewVectors(d: ChatViewDeps) {
	const { ORGANIZABLE_CASES, PLACEMENT_CASES, SHARED_SUB_CHAT_CASES, UNREAD_CASES, draftActivationCases, globalSelectedCases, readGateCases, urlPlanCases } = d.cases;
	const runUnread = (events: UnreadEvent[]) => {
		d.unread.apply({ type: 'clear_all' });
		const chats = new Set<string>();
		return events.map((event) => {
			d.unread.apply(event);
			if ('chat' in event) chats.add(event.chat);
			return {
				counts: d.unread.counts(),
				manual: [...chats].filter((chat) => d.unread.isManual(chat)).sort(),
				queries: [...chats].sort().flatMap((chat) => [null, 0, 2].map((persisted) => ({
					chat, persisted, count: d.unread.count(chat), hasUnread: d.unread.hasUnread(chat, persisted ?? undefined),
				}))),
			};
		});
	};
	return json({
		urlPlan: urlPlanCases().map((input) => ({ input, out: d.planUrlUpdate(input as never) })),
		globalSelected: globalSelectedCases().map((input) => ({ input, out: d.planGlobalSelected(input as never) })),
		draftActivation: draftActivationCases().map((input) => ({ input, out: { skip: d.skipDraftActivation(input.selected, input.persisted) } })),
		readGate: readGateCases().map((input) => ({ input, out: { proceed: d.readGateAllows(input as never) } })),
		unread: UNREAD_CASES.map((c) => ({ name: c.name, events: c.events, steps: runUnread(c.events) })),
		placementOrganizable: ORGANIZABLE_CASES.map((input) => ({ input, out: d.chatsOrganizable(input as never) })),
		placementPlan: PLACEMENT_CASES.map((input) => ({ input, out: d.planPlacement(input as never) })),
		sharedSubChat: SHARED_SUB_CHAT_CASES.map((c) => ({
			name: c.name,
			input: { row: c.row, parent: { chatId: c.parent.chat_id, ...('share_pii' in c.parent ? { sharePii: c.parent.share_pii } : {}), ...('share_highlights' in c.parent ? { shareHighlights: c.parent.share_highlights } : {}) } },
			out: d.sharedSubChatToChat(c.row as never, c.parent as never),
		})),
	});
}

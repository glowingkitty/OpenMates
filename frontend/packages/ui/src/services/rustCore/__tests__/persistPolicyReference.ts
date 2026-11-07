// TypeScript reference of every cache/chat-row op of the `persist` unit: the op input
// JSON in, the output JSON out, computed by the flag-off policy (db/cachePolicy.ts,
// db/chatRowPolicy.ts, db/messageRowPolicy.ts). The parity vectors of
// packages/openmates-rust/src/web_persist/policy_vectors.json are generated from the same
// functions; this table lets tests check that and stand in for the WASM binding.
import * as cache from '../../db/cachePolicy';
import * as chats from '../../db/chatRowPolicy';
import { isSafeToEvictMessage } from '../../db/messageRowPolicy';
import type { Message } from '../../../types/chat';

type Input = any; // eslint-disable-line @typescript-eslint/no-explicit-any -- op inputs are validated JSON of the vectors

export const referenceOps: Record<string, (input: Input) => unknown> = {
	windowPlan: (i) => cache.planMessageWindow(i),
	windowResultMeta: (i) => cache.windowResultMeta(i),
	windowPageRecord: (i) => cache.buildWindowPageRecord(i),
	evictPlan: (i) => cache.planPageEviction(i),
	evictDeletePlan: (i) => ({ plan: cache.planPageDeletion(i) }),
	pageConfirmed: (i) => ({ confirmed: (i.messages as Array<Message | null>).every((m) => isSafeToEvictMessage(m ?? undefined)) }),
	budgetThrottle: (i) => ({ throttled: cache.budgetCheckThrottled(i) }),
	budgetTarget: (i) => cache.budgetTarget(i),
	budgetCandidates: (i) => ({ pages: cache.budgetCandidates(i.pages) }),
	budgetChatStep: (i) => cache.budgetChatStep(i),
	budgetAfter: (i) => ({ action: cache.budgetAfterEviction(i) }),
	quotaStep: (i) => ({ action: cache.quotaStep(i) }),
	chatsPageSize: (i) => ({ size: cache.chatsPageSize(i.limit) }),
	chatDefaults: (i) => chats.chatRowDefaults(i.chat, i.now),
	keylessDraftOnly: (i) => ({ expected: chats.isExpectedKeylessDraftOnlySyncChat(i.chat, i.existing) }),
	candidateKeys: (i) => ({ updated: chats.nextCandidateKeys(i.existing, i.blob) }),
	draftMerge: (i) => {
		const fields = { ...i.fields };
		for (const key of i.undefinedKeys as string[]) fields[key] = undefined;
		return chats.mergeDraftFields(i.chatId, i.current, fields, i.missingRow);
	},
	teamDraftIntent: (i) => chats.applyTeamDraftIntent(i.chat, i.teamId, i.pending, i.expected),
};

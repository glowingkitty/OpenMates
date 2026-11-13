// TypeScript reference of every cache/chat-row op of the `persist` unit: the op input
// JSON in, the output JSON out, computed by the test-only reference policy (reference/*.ts). The parity vectors of
// packages/openmates-rust/src/web_persist/policy_vectors.json are generated from the same
// functions; this table lets tests check that and stand in for the WASM binding.
import * as cache from './reference/cachePolicy';
import * as chats from './reference/chatRowPolicy';
import { hasNewEncryptedFields, isContentDuplicate, isSafeToEvictMessage, planDuplicateCleanup, shouldUpdateMessage } from './reference/messageRowPolicy';
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
	duplicateCleanup: (i) => ({ deleteIds: planDuplicateCleanup(i.messages) }),
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

/** Message-row ops of the `persist` unit, with the field projection the adapter sends. */
export const messageReferenceOps: Record<string, (input: Input) => unknown> = {
	messageShouldUpdate: (i) => ({ results: i.pairs.map((p: { existing: Message; incoming: Message }) => shouldUpdateMessage(p.existing, p.incoming)) }),
	messageSaveDecision: (i) => ({ shouldUpdate: shouldUpdateMessage(i.existing, i.incoming), fillsEncrypted: hasNewEncryptedFields(i.existing, i.incomingEncrypted) }),
	messageContentDuplicate: (i) => {
		const index = (i.candidates as Message[]).findIndex((c) => c.message_id !== i.message.message_id && isContentDuplicate(c, i.message));
		return { index: index < 0 ? null : index };
	},
	messageSafeToEvict: (i) => ({ results: (i.messages as Array<Message | null>).map((m) => isSafeToEvictMessage(m ?? undefined)) }),
};

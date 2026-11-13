/**
 * Draft chats claimed by a send in progress.
 *
 * A first message typed into a new chat is usually saved as a draft first,
 * which creates a draft-only chat. The send then clears the composer and
 * writes the message into that same chat. Until the send has stored its
 * message (or rolled back), an empty-draft cleanup that races it — a draft save
 * still in flight at the click, a stale write, or a draft deletion receipt —
 * would see "a chat with no messages" and delete the chat under the send. The
 * send owns that chat's draft cleanup while it holds the claim.
 *
 * shell-only: bugfix-in-frozen-code drafts
 */

const claims = new Map<string, number>();

/**
 * Chats whose first send was stopped and whose message was restored as a draft.
 * The server may still answer that turn with generated title/category/icon; a
 * chat without messages must not receive them (it would stop being draft-only).
 * A new send in the chat claims it again and clears the mark.
 */
const stoppedFirstSendChats = new Set<string>();

export function markFirstSendStopped(chatId: string | null | undefined): void {
  if (chatId) stoppedFirstSendChats.add(chatId);
}

export function isFirstSendStopped(chatId: string | null | undefined): boolean {
  return !!chatId && stoppedFirstSendChats.has(chatId);
}

/** Claim a chat for one send; call the returned function exactly once to release. */
export function claimDraftChatForSend(chatId: string): () => void {
  stoppedFirstSendChats.delete(chatId);
  claims.set(chatId, (claims.get(chatId) ?? 0) + 1);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    const remaining = (claims.get(chatId) ?? 1) - 1;
    if (remaining > 0) claims.set(chatId, remaining);
    else claims.delete(chatId);
  };
}

/** True while a send may still store its message in this chat. */
export function isDraftChatClaimedForSend(chatId: string | null | undefined): boolean {
  return !!chatId && claims.has(chatId);
}

/** Claims one running send holds; each chat is claimed at most once per send. */
export interface SendClaimSet {
  claim: (chatId: string | null | undefined) => void;
  claimedChatIds: () => string[];
  releaseAll: () => void;
}

export function createSendClaimSet(): SendClaimSet {
  const held = new Map<string, () => void>();
  return {
    claim: (chatId) => {
      if (chatId && !held.has(chatId)) held.set(chatId, claimDraftChatForSend(chatId));
    },
    claimedChatIds: () => [...held.keys()],
    releaseAll: () => {
      for (const release of held.values()) release();
    },
  };
}

/** Bounded ordered step names of one send, for locating an early exit. */
export interface SendStepTrail {
  reset: () => void;
  record: (step: string) => void;
  snapshot: () => string[];
}

export function createSendStepTrail(limit = 40): SendStepTrail {
  let steps: string[] = [];
  return {
    reset: () => { steps = []; },
    record: (step) => {
      steps.push(step);
      if (steps.length > limit) steps.shift();
    },
    snapshot: () => steps.slice(),
  };
}

/** Minimal chat/message view needed to decide on cleanup after a failed send. */
export interface FailedSendChatView {
  messages_v?: number | null;
}

/**
 * Pure decision: after a FAILED send, a claimed chat that still has no messages
 * is removed only when the composer does not hold draft content for it (a
 * restored rollback draft keeps the chat).
 */
export function shouldDiscardChatAfterFailedSend(
  chat: FailedSendChatView | null | undefined,
  storedMessageCount: number,
  composerHoldsDraft: boolean,
): boolean {
  return !!chat && (chat.messages_v ?? 0) === 0 && storedMessageCount === 0 && !composerHoldsDraft;
}

export interface FailedSendCleanupDeps<C extends FailedSendChatView> {
  getChat: (chatId: string) => Promise<C | null | undefined>;
  getMessagesForChat: (chatId: string) => Promise<unknown[] | null | undefined>;
  deleteDraftOnlyChat: (chatId: string) => Promise<{ deleted: boolean; deletedEmbedIds: string[] }>;
  /** Announce the deletion (UI event, server delete) exactly as empty-draft cleanup does. */
  onDeleted: (chatId: string, deletedEmbedIds: string[]) => Promise<void> | void;
}

/** Remove claimed draft-only chats a failed send left behind; returns deleted ids. */
export async function discardEmptyClaimedChatsAfterFailedSend<C extends FailedSendChatView>(
  chatIds: string[],
  composerHoldsDraftFor: (chatId: string) => boolean,
  deps: FailedSendCleanupDeps<C>,
): Promise<string[]> {
  const deletedIds: string[] = [];
  for (const chatId of chatIds) {
    try {
      const chat = await deps.getChat(chatId);
      const messages = await deps.getMessagesForChat(chatId);
      if (!shouldDiscardChatAfterFailedSend(chat, messages?.length ?? 0, composerHoldsDraftFor(chatId))) continue;
      const { deleted, deletedEmbedIds } = await deps.deleteDraftOnlyChat(chatId);
      if (!deleted) continue;
      await deps.onDeleted(chatId, deletedEmbedIds);
      deletedIds.push(chatId);
    } catch (error) {
      console.error(`[handleSend] Failed to remove empty draft chat ${chatId} after failed send:`, error);
    }
  }
  return deletedIds;
}

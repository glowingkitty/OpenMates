/**
 * Pending daily-inspiration chat (TASK-3406, plan daily-inspiration-deferred-chat).
 *
 * Opening a daily inspiration shows it like a chat but saves nothing: no chat key,
 * no IndexedDB record, no sync and no "opened" mark. The preview lives here, in
 * memory, keyed by the chat ID it will keep. The first send into that chat awaits
 * `materializePendingInspirationChat`, which runs the existing creation code, so the
 * message lands in a real saved chat with the inspiration message as history.
 * Leaving the preview discards it, so nothing is stored.
 */
import type { Message } from '../types/chat';

interface PendingInspirationChat {
  chatId: string;
  inspirationId: string;
  /** In-memory assistant message shown while the chat is a preview. */
  messages: Message[];
  /** Runs the existing chat creation (key, IndexedDB, sync, opened mark). */
  materialize: () => Promise<void>;
}

let pending: PendingInspirationChat | null = null;
let inFlight: { chatId: string; promise: Promise<void> } | null = null;

/** Starts a preview; replaces (discards) any earlier unsent preview. */
export function setPendingInspirationChat(entry: PendingInspirationChat): void {
  pending = entry;
}

/** The preview for this chat ID, if it has not been saved yet. */
export function getPendingInspirationChat(chatId: string | null | undefined): PendingInspirationChat | null {
  return chatId && pending?.chatId === chatId ? pending : null;
}

export function isPendingInspirationChat(chatId: string | null | undefined): boolean {
  return getPendingInspirationChat(chatId) !== null;
}

/** Leaving the preview without sending: forget it, nothing was stored. */
export function discardPendingInspirationChat(): void {
  pending = null;
}

/**
 * Saves the pending preview as a real chat before the first message is sent into it.
 * A no-op for any other chat. Concurrent callers for the same chat share one run.
 * Errors propagate so the send fails visibly instead of sending into a missing chat.
 */
export async function materializePendingInspirationChat(chatId: string | null | undefined): Promise<void> {
  if (!chatId) return;
  if (inFlight?.chatId === chatId) return inFlight.promise;
  const entry = getPendingInspirationChat(chatId);
  if (!entry) return;
  const promise = entry.materialize().then(() => {
    if (pending?.chatId === chatId) pending = null;
  });
  inFlight = { chatId, promise };
  try {
    await promise;
  } finally {
    if (inFlight?.chatId === chatId) inFlight = null;
  }
}

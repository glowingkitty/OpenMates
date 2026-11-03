import type { Message } from "../types/chat";

/** Device-local concurrency guard. Persisted message rows provide replay receipts;
 * ACK/history recovery never creates a new-message notice. No plaintext goes to disk.
 */
const receipts = new Set<string>();
let owner = "";

export function claimChatMessageNotification(ownerID: string, chatID: string, messageID: string): boolean {
  if (owner !== ownerID) { receipts.clear(); owner = ownerID; }
  const id = JSON.stringify([chatID, messageID]);
  if (receipts.has(id)) return false;
  receipts.add(id);
  if (receipts.size > 1000) receipts.delete(receipts.values().next().value!);
  return true;
}

/** Thinking/streaming placeholders are not receipts for a completed message. */
export function isFinalizedChatMessage(message: Message | null | undefined): boolean {
  return message?.status === "synced" && !!(message.content || message.encrypted_content);
}

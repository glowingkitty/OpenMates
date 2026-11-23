import { get } from "svelte/store";
import { userProfile } from "../stores/userProfile";
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
/**
 * Records that a chat message was shown on screen or announced. Returns true only the
 * first time it reaches a chat that is not visible, so a reply the user watched arrive
 * (for example during a call) is never announced again as a new message later.
 */
export function announceChatMessageOnce(chatID: string, messageID: string, chatVisible: boolean): boolean {
  const first = claimChatMessageNotification(get(userProfile).user_id || "", chatID, messageID);
  return first && !chatVisible;
}

/** One info line per new-message card: where it came from, never its content. */
export function noteChatMessageCard(source: string, chatID: string): void {
  console.info("[Notifications] Chat message card", { source, chatID });
}

export function isFinalizedChatMessage(message: Message | null | undefined): boolean {
  return message?.status === "synced" && !!(message.content || message.encrypted_content);
}

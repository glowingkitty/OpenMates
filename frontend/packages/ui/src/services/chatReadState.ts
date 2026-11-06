/**
 * Marks a chat read on this device, in IndexedDB and on the server.
 *
 * Callers decide *when* a chat is read: ActiveChat once the last line of the
 * latest reply has been visible, and the send path when the user answers
 * (a reply is assumed read once the user responds to it). The server broadcasts
 * the 0 to the user's other devices.
 */
import { chatDB } from "./db";
import { chatSyncService } from "./chatSyncService";
import { unreadMessagesStore } from "../stores/unreadMessagesStore";

export function hasUnread(chatId: string, persistedUnreadCount: number | undefined): boolean {
  return unreadMessagesStore.getUnreadCount(chatId) > 0 || (persistedUnreadCount ?? 0) > 0;
}

export async function markChatRead(chatId: string, reason = "unspecified"): Promise<void> {
  console.info(`[ChatRead] marking chat ${chatId} read (${reason})`);
  unreadMessagesStore.clearUnread(chatId);
  await chatDB.updateChatReadStatus(chatId, 0);
  await chatSyncService.sendChatReadStatus(chatId, 0);
}

export interface LatestReplyReadCheck {
  chatId: string;
  persistedUnreadCount: number | undefined;
  /** True when the end of the newest rendered message is inside the chat viewport. */
  isLatestMessageEndVisible: () => boolean;
  /** False once the user left this chat while the settle delay ran. */
  isChatStillOpen?: () => boolean;
}

/**
 * The end of the newest reply must stay on screen this long before the chat is
 * marked read. A freshly opened chat lays out its reply progressively and
 * restores the scroll position afterwards; a transient frame where the (still
 * short) reply ends inside the viewport is not the user reading its last line.
 */
export const LAST_LINE_SETTLE_MS = 600;

/**
 * Marks the visible chat read only when its newest reply has been seen to the
 * last line while the page is visible. A chat the user explicitly marked unread
 * stays unread until they leave it. Returns true when the chat was marked read.
 */
export async function markReadIfLatestReplySeen(check: LatestReplyReadCheck): Promise<boolean> {
  if (settlingChatIds.has(check.chatId)) {
    recheckChatIds.add(check.chatId);
    return false;
  }
  settlingChatIds.add(check.chatId);
  try {
    const marked = await markWhenSettled(check);
    if (!marked && recheckChatIds.delete(check.chatId)) {
      settlingChatIds.delete(check.chatId);
      return await markReadIfLatestReplySeen(check);
    }
    return marked;
  } finally {
    settlingChatIds.delete(check.chatId);
    recheckChatIds.delete(check.chatId);
  }
}

/** Chats with a settle delay in flight, so repeated triggers do not stack. */
const settlingChatIds = new Set<string>();
/** Triggers that arrived during a settle delay and must be re-evaluated afterwards. */
const recheckChatIds = new Set<string>();

async function markWhenSettled(check: LatestReplyReadCheck): Promise<boolean> {
  if (typeof document === "undefined" || document.visibilityState !== "visible") return false;
  if (unreadMessagesStore.isManuallyUnread(check.chatId)) return false;
  if (!hasUnread(check.chatId, check.persistedUnreadCount)) return false;
  if (!check.isLatestMessageEndVisible()) return false;
  await new Promise<void>((resolve) => setTimeout(resolve, LAST_LINE_SETTLE_MS));
  if (check.isChatStillOpen && !check.isChatStillOpen()) return false;
  if (document.visibilityState !== "visible") return false;
  if (unreadMessagesStore.isManuallyUnread(check.chatId)) return false;
  if (!hasUnread(check.chatId, check.persistedUnreadCount)) return false;
  if (!check.isLatestMessageEndVisible()) return false;
  await markChatRead(check.chatId, "last line visible");
  return true;
}

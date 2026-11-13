// Read detection contract: a chat is read only once the last line of its newest
// reply has been visible while the page is visible — never merely by opening it.
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  updateChatReadStatus: vi.fn(async () => {}),
  sendChatReadStatus: vi.fn(async () => {}),
}));
vi.mock("../db", () => ({ chatDB: { updateChatReadStatus: mocks.updateChatReadStatus } }));
vi.mock("../chatSyncService", () => ({ chatSyncService: { sendChatReadStatus: mocks.sendChatReadStatus } }));

import { markReadIfLatestReplySeen, LAST_LINE_SETTLE_MS } from "../chatReadState";
import { unreadMessagesStore } from "../../stores/unreadMessagesStore";

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
}

describe("markReadIfLatestReplySeen", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    unreadMessagesStore.clearAll();
    mocks.updateChatReadStatus.mockClear();
    mocks.sendChatReadStatus.mockClear();
    setVisibility("visible");
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  /** Runs the check and lets its settle delay elapse. */
  async function settled(check: Parameters<typeof markReadIfLatestReplySeen>[0]): Promise<boolean> {
    const result = markReadIfLatestReplySeen(check);
    await vi.advanceTimersByTimeAsync(LAST_LINE_SETTLE_MS + 50);
    return result;
  }

  // contract-test: supporting surface=gui.web assertions=chat-unread.reply.read-at-last-line
  it("keeps the chat unread while only the start of the reply is visible", async () => {
    unreadMessagesStore.setUnread("chat-1", 1, "reply-1");
    const marked = await settled({
      chatId: "chat-1", persistedUnreadCount: 1, isLatestMessageEndVisible: () => false,
    });
    expect(marked).toBe(false);
    expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(1);
    expect(mocks.sendChatReadStatus).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chat-unread.reply.read-at-last-line
  it("marks read locally, in IndexedDB and on the server once the last line is visible", async () => {
    unreadMessagesStore.setUnread("chat-1", 1, "reply-1");
    const marked = await settled({
      chatId: "chat-1", persistedUnreadCount: 1, isLatestMessageEndVisible: () => true,
    });
    expect(marked).toBe(true);
    expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(0);
    expect(mocks.updateChatReadStatus).toHaveBeenCalledWith("chat-1", 0);
    expect(mocks.sendChatReadStatus).toHaveBeenCalledWith("chat-1", 0);
  });

  // contract-test: supporting surface=gui.web assertions=chat-unread.reply.read-at-last-line
  it("does not mark read while the tab is hidden", async () => {
    setVisibility("hidden");
    unreadMessagesStore.setUnread("chat-1", 1, "reply-1");
    expect(await settled({
      chatId: "chat-1", persistedUnreadCount: 1, isLatestMessageEndVisible: () => true,
    })).toBe(false);
    expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=chat-unread.manual.mark-unread
  it("respects a manual mark-as-unread on the visible chat", async () => {
    unreadMessagesStore.markManuallyUnread("chat-1");
    expect(await settled({
      chatId: "chat-1", persistedUnreadCount: 1, isLatestMessageEndVisible: () => true,
    })).toBe(false);
    expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(1);
  });

  // contract-test: supporting surface=gui.web assertions=chat-unread.reply.read-at-last-line
  it("sends nothing when the chat is already read", async () => {
    expect(await settled({
      chatId: "chat-1", persistedUnreadCount: 0, isLatestMessageEndVisible: () => true,
    })).toBe(false);
    expect(mocks.sendChatReadStatus).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chat-unread.reply.read-at-last-line
  it("does not mark read when the end of the reply was only on screen transiently", async () => {
    unreadMessagesStore.setUnread("chat-1", 1, "reply-1");
    let visible = true;
    const result = markReadIfLatestReplySeen({
      chatId: "chat-1", persistedUnreadCount: 1, isLatestMessageEndVisible: () => visible,
    });
    visible = false;
    await vi.advanceTimersByTimeAsync(LAST_LINE_SETTLE_MS + 50);
    expect(await result).toBe(false);
    expect(unreadMessagesStore.getUnreadCount("chat-1")).toBe(1);
    expect(mocks.sendChatReadStatus).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chat-unread.reply.read-at-last-line
  it("does not mark read when the user left the chat while the settle delay ran", async () => {
    unreadMessagesStore.setUnread("chat-1", 1, "reply-1");
    let open = true;
    const result = markReadIfLatestReplySeen({
      chatId: "chat-1", persistedUnreadCount: 1, isLatestMessageEndVisible: () => true, isChatStillOpen: () => open,
    });
    open = false;
    await vi.advanceTimersByTimeAsync(LAST_LINE_SETTLE_MS + 50);
    expect(await result).toBe(false);
    expect(mocks.sendChatReadStatus).not.toHaveBeenCalled();
  });
});

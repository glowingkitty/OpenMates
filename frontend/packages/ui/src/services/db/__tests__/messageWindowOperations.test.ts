// frontend/packages/ui/src/services/db/__tests__/messageWindowOperations.test.ts
// Synthetic tests for bounded chat message window reads.
//
// These tests intentionally seed in-memory message rows instead of triggering
// AI inference or creating real 1000-message chats. They guard the scalable
// loading contract: cursor reads and decryption must stay bounded.

import { describe, expect, it, vi } from "vitest";
import type { Message } from "../../../types/chat";
import {
  evictStaleMessageWindowPages,
  getMessageWindowPagesForChat,
  getMessageWindowForChat,
  isContentDuplicate,
  recordMessageWindowPage,
  shouldUpdateMessage,
  type MessageWindowResult,
} from "../messageOperations";

type CursorDirection = "next" | "prev";

class TestKeyRange {
  constructor(
    readonly lower: [string, number],
    readonly upper: [string, number],
    readonly lowerOpen: boolean,
    readonly upperOpen: boolean,
  ) {}

  static bound(
    lower: [string, number],
    upper: [string, number],
    lowerOpen = false,
    upperOpen = false,
  ): TestKeyRange {
    return new TestKeyRange(lower, upper, lowerOpen, upperOpen);
  }

  includes(message: Message): boolean {
    const lowerOk = this.lowerOpen
      ? message.chat_id === this.lower[0] && message.created_at > this.lower[1]
      : message.chat_id === this.lower[0] && message.created_at >= this.lower[1];
    const upperOk = this.upperOpen
      ? message.chat_id === this.upper[0] && message.created_at < this.upper[1]
      : message.chat_id === this.upper[0] && message.created_at <= this.upper[1];
    return lowerOk && upperOk;
  }
}

class TestRequest<T> {
  onsuccess: (() => void) | null = null;
  onerror: (() => void) | null = null;
  error: Error | null = null;

  constructor(public result: T) {}
}

class TestCursor {
  constructor(
    private readonly request: TestRequest<TestCursor | null>,
    private readonly rows: Message[],
    private index: number,
  ) {}

  get value(): Message {
    return this.rows[this.index];
  }

  continue(): void {
    this.index += 1;
    this.request.result = this.index < this.rows.length ? this : null;
    queueMicrotask(() => this.request.onsuccess?.());
  }
}

function makeMessages(count: number, chatId = "chat-window"): Message[] {
  return Array.from({ length: count }, (_, index) => ({
    message_id: `msg-${index + 1}`,
    chat_id: chatId,
    role: index % 2 === 0 ? "user" : "assistant",
    created_at: index + 1,
    status: "synced",
    encrypted_content: `encrypted-${index + 1}`,
  }));
}

function makeDb(messages: Message[]) {
  const decryptMessageFields = vi.fn(async (message: Message) => ({
    ...message,
    content: `decrypted-${message.message_id}`,
  }));
  const sorted = [...messages].sort((a, b) =>
    a.created_at - b.created_at || a.message_id.localeCompare(b.message_id),
  );
  const store = {
    get(messageId: string) {
      const request = new TestRequest<Message | undefined>(
        sorted.find((message) => message.message_id === messageId),
      );
      queueMicrotask(() => request.onsuccess?.());
      return request;
    },
    index() {
      return {
        openCursor(range: TestKeyRange, direction: CursorDirection) {
          const rows = sorted.filter((message) => range.includes(message));
          if (direction === "prev") rows.reverse();
          const request = new TestRequest<TestCursor | null>(null);
          request.result = rows.length > 0 ? new TestCursor(request, rows, 0) : null;
          queueMicrotask(() => request.onsuccess?.());
          return request;
        },
      };
    },
  };

  return {
    decryptMessageFields,
    init: vi.fn(async () => undefined),
    getTransaction: vi.fn(async () => ({
      objectStore: () => store,
    })),
  };
}

function makeWindowResult(messages: Message[]): MessageWindowResult {
  return {
    messages,
    hasMoreBefore: true,
    hasMoreAfter: false,
    startCursor: messages[0]?.created_at ?? null,
    startCursorMessageId: messages[0]?.message_id ?? null,
    endCursor: messages[messages.length - 1]?.created_at ?? null,
    endCursorMessageId: messages[messages.length - 1]?.message_id ?? null,
    anchorFound: true,
  };
}

function makePageCacheDb(messages: Message[]) {
  const messagesById = new Map(messages.map((message) => [message.message_id, message]));
  const pagesById = new Map<string, Record<string, unknown>>();

  const messageStore = {
    get(messageId: string) {
      const request = new TestRequest<Message | undefined>(messagesById.get(messageId));
      queueMicrotask(() => request.onsuccess?.());
      return request;
    },
    delete(messageId: string) {
      messagesById.delete(messageId);
      const request = new TestRequest<undefined>(undefined);
      queueMicrotask(() => request.onsuccess?.());
      return request;
    },
  };

  const pageStore = {
    get(pageId: string) {
      const request = new TestRequest<Record<string, unknown> | undefined>(pagesById.get(pageId));
      queueMicrotask(() => request.onsuccess?.());
      return request;
    },
    put(page: Record<string, unknown>) {
      pagesById.set(String(page.id), page);
      const request = new TestRequest<undefined>(undefined);
      queueMicrotask(() => request.onsuccess?.());
      return request;
    },
    delete(pageId: string) {
      pagesById.delete(pageId);
      const request = new TestRequest<undefined>(undefined);
      queueMicrotask(() => request.onsuccess?.());
      return request;
    },
    index() {
      return {
        getAll(range: TestKeyRange) {
          const chatId = range.lower[0];
          const pages = Array.from(pagesById.values())
            .filter((page) => page.chat_id === chatId)
            .sort((a, b) => Number(a.last_accessed_at) - Number(b.last_accessed_at));
          const request = new TestRequest<Record<string, unknown>[]>(pages);
          queueMicrotask(() => request.onsuccess?.());
          return request;
        },
      };
    },
  };

  return {
    messagesById,
    pagesById,
    db: {
      init: vi.fn(async () => undefined),
      getTransaction: vi.fn(async () => ({
        objectStore: (storeName: string) =>
          storeName === "message_window_pages" ? pageStore : messageStore,
      })),
      encryptMessageFields: vi.fn(async (message: Message) => message),
      decryptMessageFields: vi.fn(async (message: Message) => message),
    },
  };
}

describe("isContentDuplicate", () => {
  it("does not treat two decrypted messages with missing encrypted content as duplicates", () => {
    const existing = {
      message_id: "message-1",
      chat_id: "chat-1",
      role: "user",
      content: "First message",
      created_at: 10,
      status: "synced",
      sender_name: "user",
    } as Message;
    const incoming = {
      message_id: "message-2",
      chat_id: "chat-1",
      role: "user",
      content: "Second message",
      created_at: 11,
      status: "sending",
      sender_name: "user",
    } as Message;

    expect(isContentDuplicate(existing, incoming)).toBe(false);
  });

  it("matches decrypted duplicate content when encrypted content is unavailable", () => {
    const existing = {
      message_id: "message-1",
      chat_id: "chat-1",
      role: "assistant",
      content: "Same response",
      created_at: 10,
      status: "synced",
    } as Message;
    const incoming = {
      message_id: "message-2",
      chat_id: "chat-1",
      role: "assistant",
      content: "Same response",
      created_at: 11,
      status: "synced",
    } as Message;

    expect(isContentDuplicate(existing, incoming)).toBe(true);
  });
});

describe("shouldUpdateMessage", () => {
  it("updates an interrupted streaming assistant message when batch sync delivers it", () => {
    const existing = {
      message_id: "ai-task-1",
      chat_id: "chat-1",
      role: "assistant",
      created_at: 10,
      status: "streaming",
      encrypted_content: "encrypted-partial",
    } as Message;
    const incoming = {
      ...existing,
      status: "delivered",
      encrypted_content: "encrypted-complete",
    } as Message;

    expect(shouldUpdateMessage(existing, incoming)).toBe(true);
  });

  it("does not update a same-id synced assistant message just because plaintext differs", () => {
    const existing = {
      message_id: "ai-task-1",
      chat_id: "chat-1",
      role: "assistant",
      content: "Partial response",
      created_at: 10,
      status: "synced",
    } as Message;
    const incoming = {
      ...existing,
      content: "Partial response with the final paragraph",
      status: "synced",
    } as Message;

    expect(shouldUpdateMessage(existing, incoming)).toBe(false);
  });

  it("does not update a same-id user message just because plaintext differs", () => {
    const existing = {
      message_id: "user-message-1",
      chat_id: "chat-1",
      role: "user",
      content: "Original user message",
      created_at: 10,
      status: "synced",
    } as Message;
    const incoming = {
      ...existing,
      content: "Different user message",
    } as Message;

    expect(shouldUpdateMessage(existing, incoming)).toBe(false);
  });

  it("preserves waiting_for_user even when sync delivers completed content", () => {
    const existing = {
      message_id: "ai-task-1",
      chat_id: "chat-1",
      role: "assistant",
      content: "Buy credits to continue",
      created_at: 10,
      status: "waiting_for_user",
    } as Message;
    const incoming = {
      ...existing,
      content: "Completed response",
      status: "synced",
    } as Message;

    expect(shouldUpdateMessage(existing, incoming)).toBe(false);
  });

  it("does not update a completed duplicate when content already matches", () => {
    const existing = {
      message_id: "ai-task-1",
      chat_id: "chat-1",
      role: "assistant",
      content: "Complete response",
      created_at: 10,
      status: "synced",
    } as Message;
    const incoming = { ...existing } as Message;

    expect(shouldUpdateMessage(existing, incoming)).toBe(false);
  });
});

describe("getMessageWindowForChat", () => {
  it("uses the 30-message default for latest windows", async () => {
    vi.stubGlobal("IDBKeyRange", TestKeyRange);
    const db = makeDb(makeMessages(101));

    const result = await getMessageWindowForChat(db as never, "chat-window");

    expect(result.messages).toHaveLength(30);
    expect(result.messages[0]?.message_id).toBe("msg-72");
    expect(result.messages[result.messages.length - 1]?.message_id).toBe("msg-101");
    expect(result.hasMoreBefore).toBe(true);
    expect(result.hasMoreAfter).toBe(false);
    expect(db.decryptMessageFields).toHaveBeenCalledTimes(30);
  });

  it("returns a bounded latest window without decrypting the whole chat", async () => {
    vi.stubGlobal("IDBKeyRange", TestKeyRange);
    const db = makeDb(makeMessages(1000));

    const result = await getMessageWindowForChat(db as never, "chat-window", {
      direction: "latest",
      limit: 40,
    });

    expect(result.messages.map((message) => message.message_id)).toEqual(
      Array.from({ length: 40 }, (_, index) => `msg-${961 + index}`),
    );
    expect(result.hasMoreBefore).toBe(true);
    expect(result.hasMoreAfter).toBe(false);
    expect(db.decryptMessageFields).toHaveBeenCalledTimes(40);
  });

  it("loads the next older active page behind an explicit cursor", async () => {
    vi.stubGlobal("IDBKeyRange", TestKeyRange);
    const db = makeDb(makeMessages(101));

    const latest = await getMessageWindowForChat(db as never, "chat-window");
    const older = await getMessageWindowForChat(db as never, "chat-window", {
      direction: "before",
      beforeTimestamp: latest.startCursor ?? undefined,
      beforeMessageId: latest.startCursorMessageId ?? undefined,
    });

    expect(older.messages).toHaveLength(30);
    expect(older.messages.map((message) => message.message_id)).toEqual(
      Array.from({ length: 30 }, (_, index) => `msg-${42 + index}`),
    );
    expect(older.hasMoreBefore).toBe(true);
    expect(older.hasMoreAfter).toBe(true);
    expect(older.messages.some((message) => message.created_at >= latest.startCursor!)).toBe(false);
  });

  it("returns a bounded target-message window around the anchor", async () => {
    vi.stubGlobal("IDBKeyRange", TestKeyRange);
    const db = makeDb(makeMessages(1000));

    const result = await getMessageWindowForChat(db as never, "chat-window", {
      direction: "around",
      anchorMessageId: "msg-500",
      limit: 11,
    });

    expect(result.anchorFound).toBe(true);
    expect(result.messages.map((message) => message.message_id)).toEqual([
      "msg-495",
      "msg-496",
      "msg-497",
      "msg-498",
      "msg-499",
      "msg-500",
      "msg-501",
      "msg-502",
      "msg-503",
      "msg-504",
      "msg-505",
    ]);
    expect(db.decryptMessageFields).toHaveBeenCalledTimes(11);
  });

  it("excludes forgotten compressed messages from the latest window", async () => {
    vi.stubGlobal("IDBKeyRange", TestKeyRange);
    const db = makeDb(makeMessages(1000));

    const result = await getMessageWindowForChat(db as never, "chat-window", {
      direction: "latest",
      limit: 20,
      compressedUpToTimestamp: 950,
    });

    expect(result.messages[0]?.message_id).toBe("msg-981");
    expect(result.messages[result.messages.length - 1]?.message_id).toBe("msg-1000");
    expect(result.messages.some((message) => message.created_at <= 950)).toBe(false);
    expect(db.decryptMessageFields).toHaveBeenCalledTimes(20);
  });

  it("uses message id as a tie breaker when loading older duplicate timestamps", async () => {
    vi.stubGlobal("IDBKeyRange", TestKeyRange);
    const messages: Message[] = [
      { message_id: "msg-a", chat_id: "chat-window", role: "user", created_at: 10, status: "synced", encrypted_content: "a" },
      { message_id: "msg-b", chat_id: "chat-window", role: "assistant", created_at: 10, status: "synced", encrypted_content: "b" },
      { message_id: "msg-c", chat_id: "chat-window", role: "user", created_at: 10, status: "synced", encrypted_content: "c" },
      { message_id: "msg-d", chat_id: "chat-window", role: "assistant", created_at: 11, status: "synced", encrypted_content: "d" },
    ];
    const db = makeDb(messages);

    const result = await getMessageWindowForChat(db as never, "chat-window", {
      direction: "before",
      beforeTimestamp: 10,
      beforeMessageId: "msg-c",
      limit: 10,
    });

    expect(result.messages.map((message) => message.message_id)).toEqual(["msg-a", "msg-b"]);
  });
});

describe("message window page cache metadata", () => {
  it("records viewed encrypted page ranges separately from message rows", async () => {
    vi.stubGlobal("IDBKeyRange", TestKeyRange);
    const messages = makeMessages(30);
    const { db, pagesById } = makePageCacheDb(messages);

    const record = await recordMessageWindowPage(
      db as never,
      "chat-window",
      makeWindowResult(messages),
      { direction: "latest", now: 1000 },
    );
    const pages = await getMessageWindowPagesForChat(db as never, "chat-window");

    expect(record?.message_ids).toEqual(messages.map((message) => message.message_id));
    expect(pages).toHaveLength(1);
    expect(pages[0]).toMatchObject({
      chat_id: "chat-window",
      page_kind: "normal",
      direction: "latest",
      start_cursor: 1,
      end_cursor: 30,
      cached_at: 1000,
      last_accessed_at: 1000,
    });
    expect(pagesById.size).toBe(1);
  });

  it("evicts least-recent normal pages while preserving unsafe and protected messages", async () => {
    vi.stubGlobal("IDBKeyRange", TestKeyRange);
    const messages = makeMessages(90);
    messages[1] = { ...messages[1], status: "streaming" };
    const { db, messagesById } = makePageCacheDb(messages);

    await recordMessageWindowPage(db as never, "chat-window", makeWindowResult(messages.slice(0, 30)), {
      direction: "latest",
      now: 1000,
    });
    await recordMessageWindowPage(db as never, "chat-window", makeWindowResult(messages.slice(30, 60)), {
      direction: "before",
      now: 2000,
    });
    await recordMessageWindowPage(db as never, "chat-window", makeWindowResult(messages.slice(60, 90)), {
      direction: "before",
      now: 3000,
    });

    const result = await evictStaleMessageWindowPages(db as never, "chat-window", {
      maxPagesPerChat: 2,
      protectedMessageIds: ["msg-3"],
    });
    const remainingPages = await getMessageWindowPagesForChat(db as never, "chat-window");

    expect(result.deletedPageIds).toHaveLength(1);
    expect(remainingPages).toHaveLength(2);
    expect(messagesById.has("msg-1")).toBe(false);
    expect(messagesById.has("msg-2")).toBe(true);
    expect(messagesById.has("msg-3")).toBe(true);
    expect(messagesById.has("msg-31")).toBe(true);
  });

  it("does not evict explicitly revealed forgotten pages", async () => {
    vi.stubGlobal("IDBKeyRange", TestKeyRange);
    const messages = makeMessages(60);
    const { db } = makePageCacheDb(messages);

    await recordMessageWindowPage(db as never, "chat-window", makeWindowResult(messages.slice(0, 30)), {
      direction: "before",
      pageKind: "forgotten",
      now: 1000,
    });
    await recordMessageWindowPage(db as never, "chat-window", makeWindowResult(messages.slice(30, 60)), {
      direction: "latest",
      pageKind: "normal",
      now: 2000,
    });

    const result = await evictStaleMessageWindowPages(db as never, "chat-window", {
      maxPagesPerChat: 1,
    });
    const remainingPages = await getMessageWindowPagesForChat(db as never, "chat-window");

    expect(result.deletedPageIds).toHaveLength(0);
    expect(remainingPages.map((page) => page.page_kind).sort()).toEqual(["forgotten", "normal"]);
  });
});

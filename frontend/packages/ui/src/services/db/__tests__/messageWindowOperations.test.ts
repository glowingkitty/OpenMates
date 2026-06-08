// frontend/packages/ui/src/services/db/__tests__/messageWindowOperations.test.ts
// Synthetic tests for bounded chat message window reads.
//
// These tests intentionally seed in-memory message rows instead of triggering
// AI inference or creating real 1000-message chats. They guard the scalable
// loading contract: cursor reads and decryption must stay bounded.

import { describe, expect, it, vi } from "vitest";
import type { Message } from "../../../types/chat";
import { getMessageWindowForChat } from "../messageOperations";

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
  const sorted = [...messages].sort((a, b) => a.created_at - b.created_at);
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

describe("getMessageWindowForChat", () => {
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
});

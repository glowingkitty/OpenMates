// frontend/packages/ui/src/components/__tests__/chatHistoryWindowPruning.test.ts
// Guards the long-chat decrypted UI window cap used by ChatHistory and ActiveChat.
//
// These tests cover the pure pruning helper rather than mounting the full Svelte
// chat stack, keeping the check fast while proving normal durable rows are capped
// and unsafe rows or forgotten-history boundaries are preserved.

import { describe, expect, it } from "vitest";
import type { ChatCompressionCheckpoint, Message } from "../../types/chat";
import {
  DECRYPTED_WINDOW_HARD_CAP,
  DECRYPTED_WINDOW_TARGET,
  NORMAL_MESSAGE_PAGE_LIMIT,
  pruneDecryptedMessageWindow,
} from "../../utils/messageWindowPruning";

function makeMessages(count: number, offset = 0): Message[] {
  return Array.from({ length: count }, (_, index) => {
    const ordinal = offset + index + 1;
    return {
      message_id: `msg-${ordinal}`,
      chat_id: "chat-window-pruning",
      role: index % 2 === 0 ? "user" : "assistant",
      created_at: ordinal,
      status: "synced",
      content: `message ${ordinal}`,
    } satisfies Message;
  });
}

describe("pruneDecryptedMessageWindow", () => {
  it("keeps decrypted normal state at the 60-message target after exceeding the 90-message hard cap", () => {
    const result = pruneDecryptedMessageWindow(makeMessages(120));

    expect(result.messages).toHaveLength(DECRYPTED_WINDOW_TARGET);
    expect(result.prunedCount).toBe(60);
    expect(result.messages.slice(0, NORMAL_MESSAGE_PAGE_LIMIT).map((message) => message.message_id)).toEqual(
      Array.from({ length: NORMAL_MESSAGE_PAGE_LIMIT }, (_, index) => `msg-${index + 1}`),
    );
    expect(result.messages.slice(-NORMAL_MESSAGE_PAGE_LIMIT).map((message) => message.message_id)).toEqual(
      Array.from({ length: NORMAL_MESSAGE_PAGE_LIMIT }, (_, index) => `msg-${91 + index}`),
    );
  });

  it("preserves unsafe in-flight rows even when they are outside the retained edge pages", () => {
    const messages = makeMessages(120);
    messages[60] = { ...messages[60], status: "streaming" };

    const result = pruneDecryptedMessageWindow(messages);

    expect(result.messages.length).toBeGreaterThan(DECRYPTED_WINDOW_TARGET);
    expect(result.messages.length).toBeLessThanOrEqual(DECRYPTED_WINDOW_HARD_CAP);
    expect(result.messages.some((message) => message.message_id === "msg-61" && message.status === "streaming")).toBe(true);
  });

  it("does not prune forgotten messages behind a compression boundary", () => {
    const checkpoints: ChatCompressionCheckpoint[] = [{
      id: "checkpoint-1",
      chat_id: "chat-window-pruning",
      compressed_up_to_timestamp: 10,
      compressed_message_count: 10,
      created_at: 200,
    }];
    const result = pruneDecryptedMessageWindow(makeMessages(130), {
      compressionCheckpoints: checkpoints,
    });

    expect(result.messages.filter((message) => message.created_at <= 10)).toHaveLength(10);
    expect(result.messages.filter((message) => message.created_at > 10)).toHaveLength(DECRYPTED_WINDOW_TARGET);
  });
});

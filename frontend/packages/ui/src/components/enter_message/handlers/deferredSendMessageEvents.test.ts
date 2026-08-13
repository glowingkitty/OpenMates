/**
 * deferredSendMessageEvents.test.ts
 *
 * Regression coverage for deferred-send message reconciliation.
 * When an upload/transcription-blocked send finalizes, the already-visible
 * optimistic chat message must be updated by stable message_id instead of
 * waiting for a full reload from IndexedDB.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Message } from "../../../types/chat";

const mockChatSyncService = vi.hoisted(() => ({
  dispatchEvent: vi.fn(),
}));

vi.mock("../../../services/chatSyncService", () => ({
  chatSyncService: mockChatSyncService,
}));

import { notifyDeferredMessageFinalized } from "./deferredSendMessageEvents";

describe("notifyDeferredMessageFinalized", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // contract-test: supporting surface=gui.web assertions=chats.local-state.precedence,chats.message.identity-idempotent
  it("emits a stable-id chat update for the finalized deferred message", () => {
    const message: Message = {
      message_id: "message-1",
      chat_id: "chat-1",
      role: "user",
      content: "```json\n{\"type\":\"audio-recording\",\"embed_id\":\"embed-1\"}\n```",
      status: "sending",
      created_at: 100,
      sender_name: "user",
      encrypted_content: null,
    };

    notifyDeferredMessageFinalized(message);

    expect(mockChatSyncService.dispatchEvent).toHaveBeenCalledTimes(1);
    const event = mockChatSyncService.dispatchEvent.mock.calls[0][0] as CustomEvent;
    expect(event.type).toBe("chatUpdated");
    expect(event.detail).toMatchObject({
      chat_id: "chat-1",
      type: "message_updated",
      newMessage: message,
    });
  });
});

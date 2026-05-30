/**
 * frontend/packages/ui/src/components/interactive_questions/utils/__tests__/questionState.test.ts
 *
 * Unit tests for InteractiveQuestions state and submission utilities.
 *
 * Architecture: Svelte 5 / ProseMirror custom node view synchronization
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import { findSubsequentResponse, submitResponse } from "../questionState";
import { chatSyncService } from "../../../../services/chatSyncService";
import type { Message } from "../../../../types/chat";

vi.mock("../../../../services/chatSyncService", () => {
  return {
    chatSyncService: {
      sendNewMessage: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
  };
});

describe("InteractiveQuestions state management", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("findSubsequentResponse", () => {
    it("returns null on undefined, null, or empty history", () => {
      expect(findSubsequentResponse(null, "q1")).toBeNull();
      expect(findSubsequentResponse(undefined, "q1")).toBeNull();
      expect(findSubsequentResponse([], "q1")).toBeNull();
    });

    it("correctly finds the latest matching interactive response in subsequent user messages", () => {
      const chatHistory: Message[] = [
        {
          message_id: "msg-1",
          chat_id: "chat-1",
          role: "assistant",
          created_at: 100,
          status: "synced",
          content: "Here is a question...",
        },
        {
          message_id: "msg-2",
          chat_id: "chat-1",
          role: "user",
          created_at: 101,
          status: "synced",
          content: "Selected: Option 1\n\n```interactive_response\n{\n  \"id\": \"q1\",\n  \"selection\": [\"opt_a\"]\n}\n```",
        },
      ];

      const result = findSubsequentResponse(chatHistory, "q1");
      expect(result).not.toBeNull();
      expect(result!.id).toBe("q1");
      expect((result as any).selection).toEqual(["opt_a"]);
    });

    it("returns null if response contains mismatched question id", () => {
      const chatHistory: Message[] = [
        {
          message_id: "msg-2",
          chat_id: "chat-1",
          role: "user",
          created_at: 101,
          status: "synced",
          content: "Selected: Option 1\n\n```interactive_response\n{\n  \"id\": \"q2\",\n  \"selection\": [\"opt_a\"]\n}\n```",
        },
      ];

      const result = findSubsequentResponse(chatHistory, "q1");
      expect(result).toBeNull();
    });

    it("returns null if message is not from user", () => {
      const chatHistory: Message[] = [
        {
          message_id: "msg-2",
          chat_id: "chat-1",
          role: "assistant",
          created_at: 101,
          status: "synced",
          content: "Selected: Option 1\n\n```interactive_response\n{\n  \"id\": \"q1\",\n  \"selection\": [\"opt_a\"]\n}\n```",
        },
      ];

      const result = findSubsequentResponse(chatHistory, "q1");
      expect(result).toBeNull();
    });

    it("handles malformed JSON gracefully", () => {
      const chatHistory: Message[] = [
        {
          message_id: "msg-2",
          chat_id: "chat-1",
          role: "user",
          created_at: 101,
          status: "synced",
          content: "Selected: Option 1\n\n```interactive_response\n{\n  \"id\": \"q1\",\n  \"selection\":\n```",
        },
      ];

      const result = findSubsequentResponse(chatHistory, "q1");
      expect(result).toBeNull();
    });
  });

  describe("submitResponse", () => {
    it("packages and dispatches a valid Message object through chatSyncService", async () => {
      const mockSend = chatSyncService.sendNewMessage as any;
      mockSend.mockResolvedValue(undefined);

      const chatId = "chat-uuid-1234567890";
      const content = "Test content";

      await submitResponse(chatId, content);

      expect(mockSend).toHaveBeenCalledTimes(1);
      const passedMessage = mockSend.mock.calls[0][0];

      expect(passedMessage.chat_id).toBe(chatId);
      expect(passedMessage.role).toBe("user");
      expect(passedMessage.status).toBe("sending");
      expect(passedMessage.content).toBe(content);
      expect(passedMessage.message_id).toContain(chatId.slice(-10));
    });
  });
});

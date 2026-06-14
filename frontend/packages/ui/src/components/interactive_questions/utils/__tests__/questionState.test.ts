/**
 * frontend/packages/ui/src/components/interactive_questions/utils/__tests__/questionState.test.ts
 *
 * Unit tests for InteractiveQuestions state and submission utilities.
 *
 * Architecture: Svelte 5 / ProseMirror custom node view synchronization
 */

import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  findSubsequentResponse,
  formatInteractiveQuestionUserResponse,
  submitResponse,
} from "../questionState";
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

vi.mock("../../../../services/db", () => {
  return {
    chatDB: {
      saveMessage: vi.fn(),
      getChat: vi.fn().mockResolvedValue(null),
      updateChat: vi.fn(),
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
          content: "```interactive_question\n{\"id\": \"q1\", \"type\": \"choice\", \"question\": \"Pick\", \"options\": [{\"id\": \"opt_a\", \"text\": \"Option 1\"}]}\n```",
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

    it("does not let an older response lock a newer unanswered question with the same id", () => {
      const questionBlock = "```interactive_question\n{\"id\": \"q1\", \"type\": \"choice\", \"question\": \"Pick\", \"options\": [{\"id\": \"opt_a\", \"text\": \"Option 1\"}]}\n```";
      const chatHistory: Message[] = [
        {
          message_id: "question-1",
          chat_id: "chat-1",
          role: "assistant",
          created_at: 100,
          status: "synced",
          content: questionBlock,
        },
        {
          message_id: "answer-1",
          chat_id: "chat-1",
          role: "user",
          created_at: 101,
          status: "synced",
          content: "Option 1\n\n```interactive_response\n{\n  \"id\": \"q1\",\n  \"selection\": [\"opt_a\"]\n}\n```",
        },
        {
          message_id: "question-2",
          chat_id: "chat-1",
          role: "assistant",
          created_at: 102,
          status: "synced",
          content: questionBlock,
        },
      ];

      expect(findSubsequentResponse(chatHistory, "q1")).toBeNull();
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

  describe("formatInteractiveQuestionUserResponse", () => {
    it("formats choice answers as answer-only display text plus hidden protocol", () => {
      const content = formatInteractiveQuestionUserResponse(
        {
          id: "q1",
          type: "choice",
          multiple: false,
          question: "Pick one",
          options: [{ id: "opt_a", text: "Option 1" }],
        },
        { id: "q1", selection: ["opt_a"] }
      );

      expect(content).toMatch(/^Option 1\n\n```interactive_response/);
      expect(content).not.toContain("Selected:");
      expect(content).not.toContain("I selected");
      expect(content).toContain('"id": "q1"');
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
      expect(passedMessage.status).toBe("synced");
      expect(passedMessage.content).toBe(content);
      expect(passedMessage.message_id).toContain(chatId.slice(-10));
    });
  });
});

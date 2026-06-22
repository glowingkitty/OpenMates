/*
 * OpenMates CLI example continuation helpers.
 *
 * Purpose: build the same full-history context that web uses when a user
 * continues from a public example chat.
 * Architecture: pure conversion over bundled public example chat data.
 * Security: only public example transcript fields are serialized; no local
 * private chat data or embed storage internals are included.
 * Tests: frontend/packages/openmates-cli/tests/tuiExampleContinuation.test.ts
 */

import type { ExampleChatConversation } from "./exampleChats.js";
import type { BenchmarkHistoryMessage } from "./client.js";

export type ExampleContinuationHistoryMessage = BenchmarkHistoryMessage & {
  message_id: string;
  chat_id: string;
  sender_name?: string | null;
};

export function buildExampleContinuationHistory(
  conversation: ExampleChatConversation,
): ExampleContinuationHistoryMessage[] {
  return conversation.messages
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message) => ({
      message_id: message.id,
      chat_id: conversation.chat.id,
      role: message.role as "user" | "assistant",
      content: message.content,
      created_at: message.createdAt,
      sender_name: message.senderName ?? message.role,
    }));
}

export function buildAnonymousExampleHistoryPayload(
  conversation: ExampleChatConversation,
): Array<{ role: string; content: string; created_at: number; sender_name: string }> {
  return buildExampleContinuationHistory(conversation).map((message) => ({
    role: message.role,
    content: message.content,
    created_at: message.created_at,
    sender_name: message.sender_name ?? message.role,
  }));
}

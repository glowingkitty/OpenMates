// frontend/packages/ui/src/services/__tests__/chatSyncMergeRecency.test.ts
// Regression coverage for chat recency reconciliation during phased sync.
// Partial server metadata must not demote a chat that was edited more recently
// on the current client, because the welcome screen ranks chats from local IDB.
// This protects the Continue carousel before the history sidebar is opened.

import { describe, expect, it } from "vitest";
import type { Chat } from "../../types/chat";
import { mergeServerChatWithLocal } from "../chatSyncMerge";

describe("chat sync recency merge", () => {
  // contract-test: supporting surface=gui.web assertions=sync.surface.semantic-parity
  it("preserves newer local recency when phased sync sends stale metadata", async () => {
    const localChat = {
      chat_id: "chat-1",
      user_id: "user-1",
      encrypted_chat_key: "encrypted-key",
      created_at: 100,
      updated_at: 300,
      last_edited_overall_timestamp: 300,
      messages_v: 1,
      title_v: 1,
      draft_v: 0,
      unread_count: 0,
    } as Chat;
    const serverChat = {
      id: "chat-1",
      encrypted_chat_key: "encrypted-key",
      updated_at: 200,
      last_edited_overall_timestamp: 200,
    };

    const merged = await mergeServerChatWithLocal(serverChat, localChat, "user-1");

    expect(merged.last_edited_overall_timestamp).toBe(300);
  });
});

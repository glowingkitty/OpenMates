// frontend/packages/ui/src/services/__tests__/chatSyncMergeDraftPromotion.test.ts
// Regression coverage for delayed phased-sync snapshots after a draft is sent.
// Sending promotes the draft-only chat to normal message state and clears its
// encrypted draft locally. Older server metadata must not restore that draft
// after the user message has already been persisted.

import { describe, expect, it } from "vitest";
import type { Chat } from "../../types/chat";
import { mergeServerChatWithLocal } from "../chatSyncMerge";

describe("chat sync draft promotion merge", () => {
  // contract-test: direct surface=gui.web assertions=drafts.draft-only.lifecycle,drafts.sync.version-authoritative
  it("does not restore a stale draft after its message was sent", async () => {
    const localChat = {
      chat_id: "chat-1",
      user_id: "user-1",
      encrypted_chat_key: "encrypted-key",
      created_at: 100,
      updated_at: 300,
      last_edited_overall_timestamp: 300,
      messages_v: 1,
      title_v: 0,
      draft_v: 0,
      unread_count: 0,
      encrypted_draft_md: null,
      encrypted_draft_preview: null,
    } as Chat;
    const staleServerChat = {
      id: "chat-1",
      encrypted_chat_key: "encrypted-key",
      created_at: 100,
      updated_at: 200,
      last_edited_overall_timestamp: 100,
      messages_v: 0,
      draft_v: 1,
      encrypted_draft_md: "stale-encrypted-draft",
      encrypted_draft_preview: "stale-encrypted-preview",
    };

    const merged = await mergeServerChatWithLocal(
      staleServerChat,
      localChat,
      "user-1",
    );

    expect(merged.messages_v).toBe(1);
    expect(merged.draft_v).toBe(0);
    expect(merged.encrypted_draft_md).toBeUndefined();
    expect(merged.encrypted_draft_preview).toBeUndefined();
  });
});

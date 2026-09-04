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
      cleared_draft_v: 1,
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

  // contract-test: direct surface=gui.web assertions=drafts.draft-only.lifecycle,drafts.sync.version-authoritative
  it("accepts a remote draft newer than the local deletion fence", async () => {
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
      cleared_draft_v: 1,
      unread_count: 0,
      encrypted_draft_md: null,
      encrypted_draft_preview: null,
    } as Chat;
    const newerServerChat = {
      id: "chat-1",
      encrypted_chat_key: "encrypted-key",
      messages_v: 1,
      draft_v: 2,
      encrypted_draft_md: "new-encrypted-draft",
      encrypted_draft_preview: "new-encrypted-preview",
    };

    const merged = await mergeServerChatWithLocal(
      newerServerChat,
      localChat,
      "user-1",
    );

    expect(merged.draft_v).toBe(2);
    expect(merged.encrypted_draft_md).toBe("new-encrypted-draft");
    expect(merged.encrypted_draft_preview).toBe("new-encrypted-preview");
  });

  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
  it("records phased deletion before an older draft snapshot arrives", async () => {
    const localDraft = {
      chat_id: "chat-1",
      user_id: "user-1",
      encrypted_title: null,
      encrypted_chat_key: "encrypted-key",
      encrypted_draft_md: "encrypted-draft-v2",
      encrypted_draft_preview: "encrypted-preview-v2",
      created_at: 100,
      updated_at: 200,
      last_edited_overall_timestamp: 100,
      messages_v: 1,
      title_v: 0,
      draft_v: 2,
      unread_count: 0,
    } as Chat;
    const deletion = await mergeServerChatWithLocal(
      {
        id: "chat-1",
        encrypted_chat_key: "encrypted-key",
        draft_v: 0,
        cleared_draft_v: 4,
        encrypted_draft_md: null,
        encrypted_draft_preview: null,
      },
      localDraft,
      "user-1",
    );

    const afterStaleSnapshot = await mergeServerChatWithLocal(
      {
        id: "chat-1",
        encrypted_chat_key: "encrypted-key",
        draft_v: 3,
        encrypted_draft_md: "stale-encrypted-draft-v3",
        encrypted_draft_preview: "stale-encrypted-preview-v3",
      },
      deletion,
      "user-1",
    );

    expect(deletion.cleared_draft_v).toBe(4);
    expect(afterStaleSnapshot.draft_v).toBe(0);
    expect(afterStaleSnapshot.encrypted_draft_md).toBeUndefined();
    expect(afterStaleSnapshot.encrypted_draft_preview).toBeUndefined();
  });

  // contract-test: direct surface=gui.web assertions=drafts.sync.version-authoritative
  it("preserves a local draft newer than a phased deletion snapshot", async () => {
    const localDraft = {
      chat_id: "chat-1",
      user_id: "user-1",
      encrypted_chat_key: "encrypted-key",
      encrypted_draft_md: "new-local-draft-v5",
      encrypted_draft_preview: "new-local-preview-v5",
      created_at: 100,
      updated_at: 300,
      last_edited_overall_timestamp: 300,
      messages_v: 1,
      title_v: 0,
      draft_v: 5,
      unread_count: 0,
    } as Chat;

    const merged = await mergeServerChatWithLocal(
      {
        id: "chat-1",
        encrypted_chat_key: "encrypted-key",
        draft_v: 0,
        cleared_draft_v: 4,
        encrypted_draft_md: null,
        encrypted_draft_preview: null,
      },
      localDraft,
      "user-1",
    );

    expect(merged.draft_v).toBe(5);
    expect(merged.encrypted_draft_md).toBe("new-local-draft-v5");
    expect(merged.encrypted_draft_preview).toBe("new-local-preview-v5");
  });
});

// frontend/packages/ui/src/services/__tests__/chatSyncMerge.test.ts
// Regression tests for phased-sync chat metadata merge policy.
// The merge layer must never pair one encrypted_chat_key with ciphertext that
// was preserved from a different local key. That mixed state caused regular
// content decryption errors after reload, before candidate fallback could help.

import { describe, expect, it } from "vitest";
import type { Chat } from "../../types/chat";
import {
  hasEncryptedChatKeyMismatch,
  mergeServerChatWithLocal,
} from "../chatSyncMerge";

function makeChat(overrides: Partial<Chat> = {}): Chat {
  return {
    chat_id: "chat-1",
    user_id: "user-1",
    encrypted_title: "local-title-k1",
    encrypted_icon: "local-icon-k1",
    encrypted_category: "local-category-k1",
    encrypted_chat_key: "local-key-k1",
    candidate_encrypted_keys: null,
    encrypted_draft_md: "local-draft-k1",
    encrypted_draft_preview: "local-draft-preview-k1",
    messages_v: 6,
    title_v: 10,
    draft_v: 4,
    unread_count: 0,
    created_at: 100,
    updated_at: 200,
    last_edited_overall_timestamp: 200,
    ...overrides,
  } as Chat;
}

describe("chat sync merge", () => {
  it("reproduces and prevents mixed-key merge when server key differs", async () => {
    const localChat = makeChat();
    const serverChat = {
      id: "chat-1",
      encrypted_chat_key: "server-key-k2",
      encrypted_title: "server-title-k2",
      encrypted_icon: "server-icon-k2",
      encrypted_category: "server-category-k2",
      messages_v: 6,
      title_v: 10,
      draft_v: 0,
      created_at: 100,
      updated_at: 300,
      last_edited_overall_timestamp: 300,
    };

    expect(hasEncryptedChatKeyMismatch(serverChat, localChat)).toBe(true);

    const merged = await mergeServerChatWithLocal(serverChat, localChat, "user-1");

    expect(merged.encrypted_chat_key).toBe("server-key-k2");
    expect(merged.encrypted_title).toBe("server-title-k2");
    expect(merged.encrypted_icon).toBe("server-icon-k2");
    expect(merged.encrypted_category).toBe("server-category-k2");
    expect(merged.encrypted_draft_md).toBeUndefined();
    expect(merged.encrypted_draft_preview).toBeUndefined();
    expect(merged.messages_v).toBe(0);
    expect(merged.candidate_encrypted_keys).toEqual(["local-key-k1"]);
  });

  it("still preserves equal-version local title when the key is unchanged", async () => {
    const localChat = makeChat();
    const serverChat = {
      id: "chat-1",
      encrypted_chat_key: "local-key-k1",
      encrypted_title: "server-title-same-key",
      messages_v: 6,
      title_v: 10,
      draft_v: 0,
    };

    const merged = await mergeServerChatWithLocal(serverChat, localChat, "user-1");

    expect(merged.encrypted_chat_key).toBe("local-key-k1");
    expect(merged.encrypted_title).toBe("local-title-k1");
    expect(merged.encrypted_draft_md).toBe("local-draft-k1");
    expect(merged.messages_v).toBe(6);
  });
});

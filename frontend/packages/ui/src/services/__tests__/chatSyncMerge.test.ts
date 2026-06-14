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
    const localChat = makeChat({
      candidate_encrypted_keys: ["local-candidate-k0"],
      key_fingerprint: "local-fp-k1",
      encrypted_shared_short_url: "local-short-url-k1",
    });
    const serverChat = {
      id: "chat-1",
      encrypted_chat_key: "server-key-k2",
      key_fingerprint: "server-fp-k2",
      encrypted_title: "server-title-k2",
      encrypted_icon: "server-icon-k2",
      encrypted_category: "server-category-k2",
      candidate_encrypted_keys: ["server-candidate-k3"],
      messages_v: 6,
      title_v: 10,
      draft_v: 0,
      created_at: 100,
      updated_at: 300,
      last_edited_overall_timestamp: 300,
    };

    expect(hasEncryptedChatKeyMismatch(serverChat, localChat)).toBe(true);

    const merged = await mergeServerChatWithLocal(serverChat, localChat, "user-1");

    expect(merged.encrypted_chat_key).toBe("local-key-k1");
    expect(merged.encrypted_title).toBe("local-title-k1");
    expect(merged.encrypted_icon).toBe("local-icon-k1");
    expect(merged.encrypted_category).toBe("local-category-k1");
    expect(merged.encrypted_shared_short_url).toBe("local-short-url-k1");
    expect(merged.encrypted_draft_md).toBeUndefined();
    expect(merged.encrypted_draft_preview).toBeUndefined();
    expect(merged.messages_v).toBe(0);
    expect(merged.candidate_encrypted_keys).toEqual([
      "local-candidate-k0",
      "server-candidate-k3",
      "server-key-k2",
    ]);
  });

  it("does not treat different encrypted key blobs as a mismatch when fingerprints match", async () => {
    const localChat = makeChat({
      encrypted_chat_key: "local-wrapped-key-with-random-iv",
      key_fingerprint: "same-raw-key-fp",
    });
    const serverChat = {
      id: "chat-1",
      encrypted_chat_key: "server-wrapped-key-with-different-random-iv",
      key_fingerprint: "same-raw-key-fp",
      encrypted_title: "server-title-same-key",
      messages_v: 6,
      title_v: 10,
      draft_v: 0,
    };

    expect(hasEncryptedChatKeyMismatch(serverChat, localChat)).toBe(false);

    const merged = await mergeServerChatWithLocal(serverChat, localChat, "user-1");

    expect(merged.encrypted_chat_key).toBe(
      "server-wrapped-key-with-different-random-iv",
    );
    expect(merged.encrypted_title).toBe("local-title-k1");
    expect(merged.messages_v).toBe(6);
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

  it("preserves local encrypted header metadata when Phase 1a sends partial cache data", async () => {
    const localChat = makeChat({
      encrypted_title: "local-title-from-idb",
      encrypted_icon: "local-icon-from-idb",
      encrypted_category: "local-category-from-idb",
      encrypted_chat_key: "same-key",
      title_v: 1,
    });
    const serverChat = {
      id: "chat-1",
      encrypted_chat_key: "same-key",
      encrypted_title: null,
      encrypted_icon: null,
      encrypted_category: null,
      messages_v: 4,
      title_v: 0,
    };

    const merged = await mergeServerChatWithLocal(serverChat, localChat, "user-1");

    expect(merged.encrypted_title).toBe("local-title-from-idb");
    expect(merged.encrypted_icon).toBe("local-icon-from-idb");
    expect(merged.encrypted_category).toBe("local-category-from-idb");
    expect(merged.title_v).toBe(1);
  });

  it("merges encrypted shared short URL from server for owner share UI restore", async () => {
    const localChat = makeChat({
      encrypted_chat_key: "same-key",
      encrypted_shared_short_url: null,
      is_shared: false,
    });
    const serverChat = {
      id: "chat-1",
      encrypted_chat_key: "same-key",
      encrypted_shared_short_url: "server-encrypted-short-url",
      is_shared: true,
      messages_v: 6,
      title_v: 10,
      draft_v: 0,
    };

    const merged = await mergeServerChatWithLocal(serverChat, localChat, "user-1");

    expect(merged.encrypted_shared_short_url).toBe("server-encrypted-short-url");
    expect(merged.is_shared).toBe(true);
  });
});

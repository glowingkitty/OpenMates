// frontend/packages/ui/src/services/__tests__/chatKeyConsistency.test.ts
// Regression tests for outbound chat-key consistency checks.
// The send path must abort if it would encrypt content with one raw key while
// attaching an encrypted_chat_key that unwraps to another raw key. That mixed
// payload was the upstream cause of regular content decryption failures.

import { describe, expect, it, vi } from "vitest";
import {
  chatKeysEqual,
  encryptedChatKeyMatchesRawKey,
} from "../chatKeyConsistency";

function key(seed: number): Uint8Array {
  return new Uint8Array(32).fill(seed);
}

describe("chat key consistency", () => {
  it("detects equal raw chat keys", () => {
    expect(chatKeysEqual(key(1), key(1))).toBe(true);
    expect(chatKeysEqual(key(1), key(2))).toBe(false);
  });

  it("reproduces outbound mixed-key risk before send", async () => {
    const cachedRawKey = key(1);
    const persistedEncryptedKey = "encrypted-key-for-k2";
    const decrypt = vi.fn().mockResolvedValue(key(2));

    const matches = await encryptedChatKeyMatchesRawKey(
      persistedEncryptedKey,
      cachedRawKey,
      decrypt,
    );

    expect(matches).toBe(false);
    expect(decrypt).toHaveBeenCalledWith(persistedEncryptedKey);
  });

  it("treats undecryptable key wrappers as unknown, not matching", async () => {
    const matches = await encryptedChatKeyMatchesRawKey(
      "hidden-or-corrupt-key-wrapper",
      key(1),
      vi.fn().mockResolvedValue(null),
    );

    expect(matches).toBeNull();
  });
});

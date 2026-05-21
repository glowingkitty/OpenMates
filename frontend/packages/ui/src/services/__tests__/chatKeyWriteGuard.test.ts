// frontend/packages/ui/src/services/__tests__/chatKeyWriteGuard.test.ts
// Regression tests for outbound encrypted-write key safety. A chat with
// candidate/conflicting encrypted keys must not keep writing new ciphertext
// from a stale local key while recovery is unresolved.

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notificationError: vi.fn(),
  getChat: vi.fn(),
  getEncryptedChatKey: vi.fn(),
}));

vi.mock("../../stores/notificationStore", () => ({
  notificationStore: {
    error: mocks.notificationError,
  },
}));

vi.mock("../db", () => ({
  chatDB: {
    getChat: mocks.getChat,
    getEncryptedChatKey: mocks.getEncryptedChatKey,
  },
}));

vi.mock("../db/chatCrudOperations", () => ({
  addCandidateKey: vi.fn(),
}));

vi.mock("../encryption/MetadataEncryptor", () => ({
  decryptChatKeyWithMasterKey: vi.fn(),
}));

vi.mock("../encryption/ChatKeyManager", () => ({
  computeKeyFingerprint: (key: Uint8Array) => `fp-${key[0]}`,
}));

describe("chat key write guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  it("refuses encrypted writes while candidate keys are pending recovery", async () => {
    const { ensureChatKeySafeForWrite } = await import("../chatKeyWriteGuard");

    mocks.getChat.mockResolvedValue({
      id: "chat-123",
      encrypted_chat_key: "server-key-wrapper",
      key_fingerprint: "fp-1",
      candidate_encrypted_keys: ["local-stale-key-wrapper"],
    });

    const allowed = await ensureChatKeySafeForWrite(
      "chat-123",
      new Uint8Array([1]),
      "assistant completion encryption",
    );

    expect(allowed).toBe(false);
    expect(mocks.getEncryptedChatKey).not.toHaveBeenCalled();
    expect(mocks.notificationError).toHaveBeenCalledWith(
      "We could not safely store this update because this chat has conflicting encryption keys. Please reload and try again.",
    );
  });
});

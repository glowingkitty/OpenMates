// frontend/packages/ui/src/services/__tests__/chatKeyWriteGuard.test.ts
// Regression tests for outbound encrypted-write key safety. A chat with
// candidate/conflicting encrypted keys must not keep writing new ciphertext
// from a stale local key while recovery is unresolved.

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notificationError: vi.fn(),
  getChat: vi.fn(),
  getEncryptedChatKey: vi.fn(),
  decryptChatKeyWithMasterKey: vi.fn(),
  unwrapTeamChatKey: vi.fn(),
  addCandidateKey: vi.fn(),
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
  addCandidateKey: mocks.addCandidateKey,
}));

vi.mock("../encryption/MetadataEncryptor", () => ({
  decryptChatKeyWithMasterKey: mocks.decryptChatKeyWithMasterKey,
}));

vi.mock("../teamService", () => ({
  unwrapTeamChatKey: mocks.unwrapTeamChatKey,
}));

vi.mock("../encryption/ChatKeyManager", () => ({
  computeKeyFingerprint: (key: Uint8Array) => `fp-${key[0]}`,
}));

describe("chat key write guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  // contract-test: direct surface=gui.web assertions=chats.sync.key-gated-recovery,chats.persistence.client-encrypted
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

  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery,chats.persistence.client-encrypted
  it("lets retrying callers suppress user-visible reporting for pending recovery", async () => {
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
      "retryable embed processing",
      { reportFailure: false },
    );

    expect(allowed).toBe(false);
    expect(console.error).not.toHaveBeenCalled();
    expect(mocks.notificationError).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked,chats.persistence.client-encrypted
  it("validates Team chat wrappers with the Team key", async () => {
    const { ensureChatKeySafeForWrite } = await import("../chatKeyWriteGuard");
    const chatKey = new Uint8Array([7]);

    mocks.getChat.mockResolvedValue({
      id: "chat-123",
      team_id: "team-123",
      encrypted_chat_key: "team-key-wrapper",
      key_fingerprint: "fp-7",
    });
    mocks.unwrapTeamChatKey.mockResolvedValue(chatKey);

    const allowed = await ensureChatKeySafeForWrite(
      "chat-123",
      chatKey,
      "chat turn preflight",
    );

    expect(allowed).toBe(true);
    expect(mocks.unwrapTeamChatKey).toHaveBeenCalledWith(
      "team-123",
      "team-key-wrapper",
    );
    expect(mocks.decryptChatKeyWithMasterKey).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked,chats.sync.key-gated-recovery
  it("refuses a Team chat wrapper that unwraps to a different key", async () => {
    const { ensureChatKeySafeForWrite } = await import("../chatKeyWriteGuard");

    mocks.getChat.mockResolvedValue({
      id: "chat-123",
      team_id: "team-123",
      encrypted_chat_key: "team-key-wrapper",
      key_fingerprint: "fp-7",
    });
    mocks.unwrapTeamChatKey.mockResolvedValue(new Uint8Array([8]));

    const allowed = await ensureChatKeySafeForWrite(
      "chat-123",
      new Uint8Array([7]),
      "chat turn preflight",
    );

    expect(allowed).toBe(false);
    expect(mocks.addCandidateKey).toHaveBeenCalledWith(
      expect.anything(),
      "chat-123",
      "team-key-wrapper",
    );
    expect(mocks.notificationError).toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked,chats.sync.key-gated-recovery
  it("fails closed when a Team chat wrapper cannot be unwrapped", async () => {
    const { ensureChatKeySafeForWrite } = await import("../chatKeyWriteGuard");

    mocks.getChat.mockResolvedValue({
      id: "chat-123",
      team_id: "team-123",
      encrypted_chat_key: "team-key-wrapper",
      key_fingerprint: "fp-7",
    });
    mocks.unwrapTeamChatKey.mockRejectedValue(new Error("Team key unavailable"));

    const allowed = await ensureChatKeySafeForWrite(
      "chat-123",
      new Uint8Array([7]),
      "chat turn preflight",
    );

    expect(allowed).toBe(false);
    expect(mocks.addCandidateKey).not.toHaveBeenCalled();
    expect(mocks.notificationError).toHaveBeenCalledWith(
      "We could not safely store this update because this chat key could not be validated. Please reload and try again.",
    );
  });
});

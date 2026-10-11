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
  unwrapDirectTeamChatKey: vi.fn(),
  unwrapAnonymousChatKey: vi.fn(),
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

vi.mock("../directChatService", () => ({
  unwrapTeamOrDirectChatKey: async (teamId: string, chatId: string, wrapper: string, visibility?: string) => {
    if (visibility === "direct" || wrapper.startsWith("OMDM1.")) {
      return mocks.unwrapDirectTeamChatKey(teamId, chatId, wrapper);
    }
    const key = await mocks.unwrapTeamChatKey(teamId, wrapper);
    if (!key) throw new Error("Team chat key could not be unwrapped");
    return key;
  },
}));

vi.mock("../anonymousChatKeyWrapping", () => ({
  unwrapAnonymousChatKey: mocks.unwrapAnonymousChatKey,
}));

vi.mock("../encryption/ChatKeyManager", () => ({
  computeKeyFingerprint: (key: Uint8Array) => `fp-${key[0]}`,
}));

describe("chat key write guard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.addCandidateKey.mockResolvedValue(undefined);
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  // contract-test: direct surface=gui.web assertions=teams.direct-chat.account-key-exchange,teams.direct-chat.participant-isolation
  it("validates a private participant envelope before a human message or embed write", async () => {
    const { ensureChatKeySafeForWrite } = await import("../chatKeyWriteGuard");
    const key = new Uint8Array([7]);
    mocks.getChat.mockResolvedValue({
      chat_id: "private-chat", team_id: "team-123", chat_visibility: "direct",
      encrypted_chat_key: "OMDM1.participant-envelope", key_fingerprint: "fp-7",
    });
    mocks.unwrapDirectTeamChatKey.mockResolvedValue(key);

    expect(await ensureChatKeySafeForWrite("private-chat", key, "human message")).toBe(true);
    expect(mocks.unwrapDirectTeamChatKey).toHaveBeenCalledWith("team-123", "private-chat", "OMDM1.participant-envelope");
    expect(mocks.unwrapTeamChatKey).not.toHaveBeenCalled();
    expect(mocks.decryptChatKeyWithMasterKey).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=teams.direct-chat.account-key-exchange,teams.direct-chat.participant-isolation
  it("rejects a private participant envelope that opens to a different raw key", async () => {
    const { ensureChatKeySafeForWrite } = await import("../chatKeyWriteGuard");
    mocks.getChat.mockResolvedValue({ team_id: "team-123", chat_visibility: "direct", encrypted_chat_key: "OMDM1.envelope" });
    mocks.unwrapDirectTeamChatKey.mockResolvedValue(new Uint8Array([8]));

    expect(await ensureChatKeySafeForWrite("private-chat", new Uint8Array([7]), "embed key")).toBe(false);
    expect(mocks.addCandidateKey).toHaveBeenCalled();
    expect(mocks.unwrapTeamChatKey).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=teams.direct-chat.account-key-exchange,teams.direct-chat.participant-isolation
  it("fails closed when a private envelope or account identity is unavailable", async () => {
    const { ensureChatKeySafeForWrite } = await import("../chatKeyWriteGuard");
    mocks.getChat.mockResolvedValue({ team_id: "team-123", chat_visibility: "direct", encrypted_chat_key: "OMDM1.envelope" });
    mocks.unwrapDirectTeamChatKey.mockRejectedValue(new Error("Identity unavailable"));

    expect(await ensureChatKeySafeForWrite("private-chat", new Uint8Array([7]), "human message")).toBe(false);
    expect(mocks.unwrapTeamChatKey).not.toHaveBeenCalled();
    expect(mocks.addCandidateKey).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=teams.direct-chat.account-key-exchange,teams.direct-chat.participant-isolation
  it("rejects a private envelope without Team context instead of using the Personal fallback", async () => {
    const { ensureChatKeySafeForWrite } = await import("../chatKeyWriteGuard");
    mocks.getChat.mockResolvedValue({ chat_visibility: "direct", encrypted_chat_key: "OMDM1.envelope" });

    expect(await ensureChatKeySafeForWrite("private-chat", new Uint8Array([7]), "human message")).toBe(false);
    expect(mocks.decryptChatKeyWithMasterKey).not.toHaveBeenCalled();
    expect(mocks.unwrapTeamChatKey).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=teams.direct-chat.account-key-exchange,teams.direct-chat.participant-isolation
  it("does not permit a missing private key even when a new ordinary chat may omit its wrapper", async () => {
    const { ensureChatKeySafeForWrite } = await import("../chatKeyWriteGuard");
    mocks.getChat.mockResolvedValue({ team_id: "team-123", chat_visibility: "direct" });
    mocks.getEncryptedChatKey.mockResolvedValue(null);

    expect(await ensureChatKeySafeForWrite("private-chat", new Uint8Array([7]), "human message", { allowMissingEncryptedChatKey: true })).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("accepts an anonymous chat key only when its session wrapper matches", async () => {
    const { ensureChatKeySafeForWrite } = await import("../chatKeyWriteGuard");
    const chatKey = new Uint8Array([7, 8]);
    mocks.getChat.mockResolvedValue({
      chat_id: "anonymous-chat-1",
      is_anonymous: true,
      anonymous_encrypted_chat_key: "session-wrapper",
      encrypted_chat_key: null,
      key_fingerprint: "fp-7",
    });
    mocks.getEncryptedChatKey.mockResolvedValue(null);
    mocks.unwrapAnonymousChatKey.mockResolvedValue(chatKey);

    expect(await ensureChatKeySafeForWrite("anonymous-chat-1", chatKey, "embed key wrapping")).toBe(true);
    expect(mocks.unwrapAnonymousChatKey).toHaveBeenCalledWith("session-wrapper");
    expect(mocks.decryptChatKeyWithMasterKey).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("rejects an anonymous wrapper that unwraps to a different key", async () => {
    const { ensureChatKeySafeForWrite } = await import("../chatKeyWriteGuard");
    mocks.getChat.mockResolvedValue({
      chat_id: "anonymous-chat-1",
      is_anonymous: true,
      anonymous_encrypted_chat_key: "session-wrapper",
      encrypted_chat_key: null,
      key_fingerprint: "fp-7",
    });
    mocks.getEncryptedChatKey.mockResolvedValue(null);
    mocks.unwrapAnonymousChatKey.mockResolvedValue(new Uint8Array([7, 9]));

    expect(await ensureChatKeySafeForWrite("anonymous-chat-1", new Uint8Array([7, 8]), "embed key wrapping")).toBe(false);
    expect(mocks.notificationError).toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("rejects an anonymous write when its session key is unavailable", async () => {
    const { ensureChatKeySafeForWrite } = await import("../chatKeyWriteGuard");
    mocks.getChat.mockResolvedValue({
      chat_id: "anonymous-chat-1",
      is_anonymous: true,
      anonymous_encrypted_chat_key: "session-wrapper",
      encrypted_chat_key: null,
      key_fingerprint: "fp-7",
    });
    mocks.getEncryptedChatKey.mockResolvedValue(null);
    mocks.unwrapAnonymousChatKey.mockResolvedValue(null);

    expect(await ensureChatKeySafeForWrite("anonymous-chat-1", new Uint8Array([7, 8]), "embed key wrapping")).toBe(false);
    expect(mocks.notificationError).not.toHaveBeenCalled();
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

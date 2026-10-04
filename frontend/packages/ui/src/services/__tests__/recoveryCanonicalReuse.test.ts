import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getChat: vi.fn(async () => ({ team_id: null })),
  putEncrypted: vi.fn(async () => undefined),
  storeEmbedKeys: vi.fn(async () => undefined),
  reconstruct: vi.fn(async () => "old-source"),
  historySource: vi.fn(async () => "old-source"),
}));

vi.mock("../db", () => ({ chatDB: { getChat: mocks.getChat } }));
vi.mock("../userDB", () => ({ userDB: {} }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: {} }));
vi.mock("../chatKeyWriteGuard", () => ({ ensureChatKeySafeForWrite: vi.fn() }));
vi.mock("../../stores/aiTypingStore", () => ({ aiTypingStore: {} }));
vi.mock("../../stores/notificationStore", () => ({ notificationStore: {} }));
vi.mock("../../stores/unreadMessagesStore", () => ({ unreadMessagesStore: {} }));
vi.mock("../chatNotificationVisibility", () => ({ isChatVisiblyActive: vi.fn() }));
vi.mock("../../utils/chatCompletionRecovery", () => ({
  deriveChatCompletionRecoveryKeypair: vi.fn(), openChatCompletionRecoveryEnvelope: vi.fn(),
  openRecoveryOutputEnvelope: vi.fn(),
}));
vi.mock("../encryption/MessageEncryptor", () => ({ encryptWithChatKey: vi.fn() }));
vi.mock("../chatRecoveryVersionRefresh", () => ({ refreshRecoveryChatVersion: vi.fn() }));
vi.mock("../embedStore", () => ({ embedStore: {
  putEncrypted: mocks.putEncrypted, storeEmbedKeys: mocks.storeEmbedKeys,
} }));
vi.mock("../encryption/MetadataEncryptor", () => ({
  decryptWithEmbedKey: vi.fn(async (cipher: string) => cipher === "type-cipher" ? "code" : "new-source"),
  unwrapEmbedKeyWithMasterKey: vi.fn(async () => new Uint8Array([1, 2])),
  unwrapEmbedKeyWithChatKey: vi.fn(async () => new Uint8Array([1, 2])),
}));
vi.mock("../../message_parsing/utils", () => ({
  computeSHA256: vi.fn(async (value: string) => `hash:${value}`),
}));
vi.mock("../embedDiffStore", () => ({ reconstructEncryptedVersionRows: mocks.reconstruct }));
vi.mock("../recoveryEmbedSource", () => ({
  historySourceFromSealedEmbed: mocks.historySource,
  catalogContextFromSealedEmbed: vi.fn(async () => ({ app_id: "code", skill_id: "code" })),
}));
vi.mock("../websocketService", () => ({ webSocketService: {
  on: vi.fn(), off: vi.fn(), sendMessage: vi.fn(),
} }));

import { markAcknowledgedRecoveredEmbed, withCanonicalEmbedWrite } from "../canonicalEmbedWriteCoordinator";
const { reuseAcknowledgedRecoveredEmbed } = await import("../chatSyncServiceHandlersRecovery");

const embed = {
  embed_id: "embed-1", hashed_chat_id: "hash:chat-1", hashed_message_id: "hash:message-1",
  encrypted_type: "type-cipher", encrypted_content: "head-v2-cipher", version_number: 2,
  status: "finished", created_at: 1, updated_at: 2,
};
const wrappers = [
  { hashed_embed_id: "hash:embed-1", key_type: "master", hashed_chat_id: null,
    encrypted_embed_key: "master-wrap", hashed_user_id: "owner", created_at: 1 },
  { hashed_embed_id: "hash:embed-1", key_type: "chat", hashed_chat_id: "hash:chat-1",
    encrypted_embed_key: "chat-wrap", hashed_user_id: "owner", created_at: 1 },
];

describe("ordinary finalized embed after exact typed recovery ACK", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
      ok: true, status: 200,
      json: async () => url.includes("/versions/1")
        ? { embed_id: "embed-1", version_number: 1,
            rows: [{ version_number: 1, encrypted_snapshot: "old-snapshot", encrypted_patch: null }] }
        : { embed, embed_keys: wrappers },
    })));
  });

  afterEach(() => vi.unstubAllGlobals());

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("reuses the verified v2 head and wrappers for a late v1 event without regressing the head", async () => {
    await withCanonicalEmbedWrite("embed-1", async (lease) => {
      markAcknowledgedRecoveredEmbed(lease, "chat-1", 2);
      expect(await reuseAcknowledgedRecoveredEmbed(lease, {
        embed_id: "embed-1", chat_id: "chat-1", message_id: "message-1",
        type: "code", content: "sealed-v1-toon", version_number: 1,
      }, new Uint8Array([1, 2]), new Uint8Array([1, 2]))).toBe(true);
    });
    expect(mocks.storeEmbedKeys).toHaveBeenCalledWith(wrappers);
    expect(mocks.putEncrypted).toHaveBeenCalledWith(
      "embed:embed-1", expect.objectContaining({
        encrypted_content: "head-v2-cipher", version_number: 2,
      }), "code", undefined, { app_id: "code", skill_id: "code" },
    );
  });

  // contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("retains the original path when there is no matching ACK and refuses a mismatched history", async () => {
    await withCanonicalEmbedWrite("embed-1", async (lease) => {
      expect(await reuseAcknowledgedRecoveredEmbed(lease, {
        embed_id: "embed-1", chat_id: "other-chat", message_id: "message-1",
        type: "code", content: "sealed-v1-toon", version_number: 1,
      }, new Uint8Array([1, 2]), new Uint8Array([1, 2]))).toBe(false);
    });
    expect(mocks.putEncrypted).not.toHaveBeenCalled();
    mocks.reconstruct.mockResolvedValueOnce("different-source");
    await expect(withCanonicalEmbedWrite("embed-1", async (lease) => {
      markAcknowledgedRecoveredEmbed(lease, "chat-1", 2);
      return reuseAcknowledgedRecoveredEmbed(lease, {
        embed_id: "embed-1", chat_id: "chat-1", message_id: "message-1",
        type: "code", content: "sealed-v1-toon", version_number: 1,
      }, new Uint8Array([1, 2]), new Uint8Array([1, 2]));
    })).rejects.toThrow(/historical embed content differs/);
    expect(mocks.putEncrypted).not.toHaveBeenCalled();
  });
});

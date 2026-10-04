import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  chatDB: {
    getMessage: vi.fn(), getChat: vi.fn(), saveMessage: vi.fn(),
    updateChat: vi.fn(), getEncryptedFields: vi.fn(),
  },
  chatKeyManager: { getKey: vi.fn(), onKeyReady: vi.fn(() => () => undefined) },
  ensureChatKeySafeForWrite: vi.fn(),
  webSocketService: { on: vi.fn(), off: vi.fn(), sendMessage: vi.fn() },
  deriveChatCompletionRecoveryKeypair: vi.fn(),
  openChatCompletionRecoveryEnvelope: vi.fn(),
}));

vi.mock("../db", () => ({ chatDB: mocks.chatDB }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: mocks.chatKeyManager }));
vi.mock("../chatKeyWriteGuard", () => ({ ensureChatKeySafeForWrite: mocks.ensureChatKeySafeForWrite }));
vi.mock("../websocketService", () => ({ webSocketService: mocks.webSocketService }));
vi.mock("../../utils/chatCompletionRecovery", () => ({
  deriveChatCompletionRecoveryKeypair: mocks.deriveChatCompletionRecoveryKeypair,
  openChatCompletionRecoveryEnvelope: mocks.openChatCompletionRecoveryEnvelope,
}));

const { sendEmbedStoreWithReceipt } = await import("../chatSyncServiceHandlersRecovery");

describe("recovered embed receipt errors", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    vi.spyOn(globalThis.crypto, "randomUUID").mockImplementation(
      () => "11111111-1111-4111-8111-111111111111",
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // contract-test: supporting surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("rejects only the matching recovered embed storage error and clears receipt listeners", async () => {
    const handlers = new Map<string, (payload: Record<string, unknown>) => void>();
    mocks.webSocketService.on.mockImplementation((type: string, handler: (payload: Record<string, unknown>) => void) => {
      handlers.set(type, handler);
    });
    mocks.webSocketService.off.mockImplementation((type: string, handler: (payload: Record<string, unknown>) => void) => {
      if (handlers.get(type) === handler) handlers.delete(type);
    });
    mocks.webSocketService.sendMessage.mockResolvedValue(undefined);

    const pending = sendEmbedStoreWithReceipt(
      "store_embed", "store_embed_confirmed", { encrypted_content: "ciphertext" },
      "embed-1", undefined, "record-1",
    );
    let settled = false;
    void pending.finally(() => { settled = true; }).catch(() => undefined);
    await vi.advanceTimersByTimeAsync(0);
    const sent = (mocks.webSocketService.sendMessage.mock.calls as unknown[][])[0][1] as Record<string, unknown>;
    expect(sent).toMatchObject({
      request_id: "11111111-1111-4111-8111-111111111111", recovery_record_id: "record-1",
    });

    handlers.get("error")?.({ request_id: "22222222-2222-4222-8222-222222222222", code: "embed_storage_failed" });
    await vi.advanceTimersByTimeAsync(0);
    expect(settled).toBe(false);

    handlers.get("error")?.({ request_id: sent.request_id, code: "embed_storage_failed" });
    await expect(pending).rejects.toMatchObject({ code: "embed_storage_failed" });
    expect(handlers.has("store_embed_confirmed")).toBe(false);
    expect(handlers.has("error")).toBe(false);
    expect(vi.getTimerCount()).toBe(0);
  });
});

/**
 * Recovery request-correlation tests.
 *
 * Verifies that delayed WebSocket frames from an earlier recovery attempt cannot
 * complete or abort a newer retry for the same sealed completion job.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  chatDB: {
    getMessage: vi.fn(),
    getChat: vi.fn(),
    saveMessage: vi.fn(),
    updateChat: vi.fn(),
    getEncryptedFields: vi.fn(),
  },
  chatKeyManager: {
    getKey: vi.fn(),
  },
  ensureChatKeySafeForWrite: vi.fn(),
  webSocketService: {
    on: vi.fn(),
    off: vi.fn(),
    sendMessage: vi.fn(),
  },
  deriveChatCompletionRecoveryKeypair: vi.fn(),
  openChatCompletionRecoveryEnvelope: vi.fn(),
}));

vi.mock("../db", () => ({ chatDB: mocks.chatDB }));
vi.mock("../encryption/ChatKeyManager", () => ({
  chatKeyManager: mocks.chatKeyManager,
}));
vi.mock("../chatKeyWriteGuard", () => ({
  ensureChatKeySafeForWrite: mocks.ensureChatKeySafeForWrite,
}));
vi.mock("../websocketService", () => ({
  webSocketService: mocks.webSocketService,
}));
vi.mock("../../utils/chatCompletionRecovery", () => ({
  deriveChatCompletionRecoveryKeypair: mocks.deriveChatCompletionRecoveryKeypair,
  openChatCompletionRecoveryEnvelope: mocks.openChatCompletionRecoveryEnvelope,
}));

const { handleRecoveryJobsAvailableImpl } = await import("../chatSyncServiceHandlersRecovery.ts");

describe("recovery job request correlation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    let requestCounter = 0;
    vi.spyOn(globalThis.crypto, "randomUUID").mockImplementation(
      () => `recovery-request-${requestCounter += 1}`,
    );
    globalThis.window = globalThis;
    mocks.chatKeyManager.getKey.mockResolvedValue(new Uint8Array([1, 2, 3]));
    mocks.ensureChatKeySafeForWrite.mockResolvedValue(true);
    mocks.chatDB.getEncryptedFields.mockResolvedValue({
      encrypted_content: "encrypted-content",
      encrypted_sender_name: "encrypted-sender",
      encrypted_category: "encrypted-category",
      encrypted_model_name: "encrypted-model",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("ignores delayed claim and persist frames from an earlier attempt", async () => {
    const handlers = new Map();
    let claimAttempts = 0;
    let persistAttempts = 0;
    let firstClaimRequestId;
    let secondClaimRequestId;
    let firstPersistRequestId;
    let secondPersistRequestId;
    const sendClaimed = (requestId) => {
      handlers.get("recovery_job_claimed")?.({
        job_id: "job-1",
        request_id: requestId,
        state: "LEASED",
        lease_token: "lease-token",
        lease_generation: 2,
        sealed_payload: '{"v":1}',
        chat_id: "chat-1",
        turn_id: "turn-1",
        assistant_message_id: "assistant-1",
        chat_key_version: 1,
      });
    };
    const sendPersisted = (requestId) => {
      handlers.get("recovery_job_persisted")?.({
        job_id: "job-1",
        request_id: requestId,
        state: "TERMINAL",
        committed_messages_v: 3,
      });
    };
    mocks.webSocketService.on.mockImplementation((type, handler) => {
      handlers.set(type, handler);
    });
    mocks.webSocketService.off.mockImplementation((type) => {
      handlers.delete(type);
    });
    mocks.webSocketService.sendMessage.mockImplementation(async (type, payload) => {
      if (type === "recovery_job_claim") {
        claimAttempts += 1;
        if (claimAttempts === 1) firstClaimRequestId = payload.request_id;
        else secondClaimRequestId = payload.request_id;
      }
      if (type === "recovery_job_persist") {
        persistAttempts += 1;
        if (persistAttempts === 1) firstPersistRequestId = payload.request_id;
        else secondPersistRequestId = payload.request_id;
      }
    });
    mocks.chatDB.getMessage.mockResolvedValue(undefined);
    mocks.chatDB.getChat.mockResolvedValue({
      chat_id: "chat-1",
      user_id: "user-1",
      messages_v: 2,
    });
    mocks.deriveChatCompletionRecoveryKeypair.mockResolvedValue({ privateKey: "private-key" });
    mocks.openChatCompletionRecoveryEnvelope.mockResolvedValue(
      new TextEncoder().encode(JSON.stringify({
        assistant_message_id: "assistant-1",
        category: "general",
        chat_id: "chat-1",
        content: "Recovered response",
        job_id: "job-1",
        key_version: 1,
        model_name: "model-1",
        turn_id: "turn-1",
      })),
    );
    const service = {
      dispatchEvent: vi.fn(),
      hasCompletedInitialSync_FOR_HANDLERS_ONLY: true,
      requestChatContentBatch_FOR_HANDLERS_ONLY: vi.fn().mockResolvedValue(undefined),
    };

    let recoverySettled = false;
    const recovery = handleRecoveryJobsAvailableImpl(service, {
      jobs: [{
        job_id: "job-1",
        chat_id: "chat-1",
        turn_id: "turn-1",
        assistant_message_id: "assistant-1",
        chat_key_version: 1,
      }],
    }).then(() => {
      recoverySettled = true;
    });

    await vi.advanceTimersByTimeAsync(20_000);
    sendClaimed(firstClaimRequestId);
    handlers.get("error")?.({
      code: "recovery_job_expired",
      job_id: "job-1",
      request_id: firstClaimRequestId,
      message: "Late error for the original claim.",
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(persistAttempts).toBe(0);

    await vi.advanceTimersByTimeAsync(61_000);
    expect(secondClaimRequestId).toEqual(expect.any(String));
    expect(secondClaimRequestId).not.toBe(firstClaimRequestId);
    expect(recoverySettled).toBe(false);
    sendClaimed(secondClaimRequestId);
    await vi.advanceTimersByTimeAsync(0);

    await vi.advanceTimersByTimeAsync(20_000);
    sendPersisted(firstPersistRequestId);
    handlers.get("error")?.({
      code: "stale_lease",
      job_id: "job-1",
      request_id: firstPersistRequestId,
      message: "Late error for the original persistence request.",
    });
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.chatDB.saveMessage).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(61_000);
    expect(secondPersistRequestId).toEqual(expect.any(String));
    expect(secondPersistRequestId).not.toBe(firstPersistRequestId);
    expect(recoverySettled).toBe(false);
    sendPersisted(secondPersistRequestId);
    await recovery;

    expect(mocks.chatDB.saveMessage).toHaveBeenCalledTimes(1);
    expect(claimAttempts).toBe(2);
    expect(persistAttempts).toBe(2);
    expect(mocks.chatDB.updateChat).toHaveBeenCalledWith(
      expect.objectContaining({ messages_v: 3 }),
    );
  });
});

// frontend/packages/ui/src/services/__tests__/chatSyncPhasedRetry.test.ts
// Silent bounded retry for typed phased_sync_retryable_error frames.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  notificationStore: { info: vi.fn(), error: vi.fn() },
  phasedSyncState: { markSyncCompleted: vi.fn() },
}));
vi.mock("../../stores/notificationStore", () => ({ notificationStore: mocks.notificationStore }));
vi.mock("../../stores/phasedSyncStateStore", () => ({ phasedSyncState: mocks.phasedSyncState }));

import {
  PHASED_SYNC_RETRY_MAX_ATTEMPTS,
  computePhasedSyncRetryDelayMs,
  handlePhasedSyncRetryableErrorImpl,
  resetPhasedSyncRetry,
} from "../chatSyncPhasedRetry";

function service() {
  return {
    clearPhasedSyncTimeout: vi.fn(),
    startPhasedSync: vi.fn(async () => undefined),
    dispatchEvent: vi.fn(),
    webSocketConnected_FOR_SENDERS_ONLY: true,
  };
}

describe("phased sync retryable error", () => {
  beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); resetPhasedSyncRetry(); });
  afterEach(() => { resetPhasedSyncRetry(); vi.useRealTimers(); });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("backs off exponentially with a cap", () => {
    expect(computePhasedSyncRetryDelayMs(1, 3000)).toBe(3000);
    expect(computePhasedSyncRetryDelayMs(3, 3000)).toBe(12000);
    expect(computePhasedSyncRetryDelayMs(9, 3000)).toBe(30000);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("retries silently without toast or completion", () => {
    const svc = service();
    handlePhasedSyncRetryableErrorImpl(svc as never, { retryable: true, retry_after_ms: 3000 });
    expect(svc.startPhasedSync).not.toHaveBeenCalled();
    vi.advanceTimersByTime(3000);
    expect(svc.startPhasedSync).toHaveBeenCalledTimes(1);
    expect(mocks.notificationStore.error).not.toHaveBeenCalled();
    expect(mocks.notificationStore.info).not.toHaveBeenCalled();
    expect(svc.dispatchEvent).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("ignores non-retryable payloads", () => {
    const svc = service();
    handlePhasedSyncRetryableErrorImpl(svc as never, { retryable: false });
    vi.advanceTimersByTime(60000);
    expect(svc.startPhasedSync).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("after the budget shows one non-alarming message and unblocks sync", () => {
    const svc = service();
    for (let i = 0; i < PHASED_SYNC_RETRY_MAX_ATTEMPTS; i++) {
      handlePhasedSyncRetryableErrorImpl(svc as never, { retryable: true });
      vi.advanceTimersByTime(30000);
    }
    expect(svc.startPhasedSync).toHaveBeenCalledTimes(PHASED_SYNC_RETRY_MAX_ATTEMPTS);
    handlePhasedSyncRetryableErrorImpl(svc as never, { retryable: true });
    expect(mocks.notificationStore.info).toHaveBeenCalledTimes(1);
    expect(mocks.notificationStore.error).not.toHaveBeenCalled();
    expect(mocks.phasedSyncState.markSyncCompleted).toHaveBeenCalled();
    expect(svc.dispatchEvent).toHaveBeenCalledTimes(1);
  });
});

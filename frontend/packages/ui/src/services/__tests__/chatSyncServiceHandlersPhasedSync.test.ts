// frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersPhasedSync.test.ts
// Regression tests for phased sync status handling.
// These guard the cold-boot path where production users have server chats,
// but local IndexedDB is empty and the cache primed flag has expired.
// The frontend must retry after backend rewarming instead of staying empty.

import { describe, expect, it, vi } from "vitest";
import type { ChatSynchronizationService } from "../chatSyncService";
import {
  ChatSynchronizationService as ChatSynchronizationServiceClass,
} from "../chatSyncService";
import { handleSyncStatusResponseImpl } from "../chatSyncServiceHandlersPhasedSync";

type ServiceStub = {
  cachePrimed_FOR_HANDLERS_ONLY: boolean;
  initialSyncAttempted_FOR_HANDLERS_ONLY: boolean;
  webSocketConnected_FOR_SENDERS_ONLY: boolean;
  cacheStatusServerChatCount_FOR_HANDLERS_ONLY: number;
  attemptInitialSync_FOR_HANDLERS_ONLY: ReturnType<typeof vi.fn>;
  scheduleCacheStatusRetry_FOR_HANDLERS_ONLY: ReturnType<typeof vi.fn>;
  dispatchEvent: ReturnType<typeof vi.fn>;
};

type RetryServiceHarness = Pick<
  ChatSynchronizationService,
  "scheduleCacheStatusRetry_FOR_HANDLERS_ONLY"
> & {
  cachePrimed: boolean;
  cacheStatusRetryCount: number;
  cacheStatusServerChatCount: number;
  cacheStatusRetryTimer: ReturnType<typeof setTimeout> | null;
  dispatchSyncTimeoutComplete: ReturnType<typeof vi.fn>;
  webSocketConnected: boolean;
  requestCacheStatus: ReturnType<typeof vi.fn>;
};

function createService(overrides: Partial<ServiceStub> = {}): ServiceStub {
  return {
    cachePrimed_FOR_HANDLERS_ONLY: false,
    initialSyncAttempted_FOR_HANDLERS_ONLY: false,
    webSocketConnected_FOR_SENDERS_ONLY: true,
    cacheStatusServerChatCount_FOR_HANDLERS_ONLY: 0,
    attemptInitialSync_FOR_HANDLERS_ONLY: vi.fn(),
    scheduleCacheStatusRetry_FOR_HANDLERS_ONLY: vi.fn(),
    dispatchEvent: vi.fn(),
    ...overrides,
  };
}

describe("handleSyncStatusResponseImpl", () => {
  it("retries cache status when sync status reports an unprimed cache", async () => {
    const service = createService();

    await handleSyncStatusResponseImpl(service as unknown as ChatSynchronizationService, {
      is_primed: false,
      chat_count: 1,
      timestamp: 1778683517,
    });

    expect(service.cachePrimed_FOR_HANDLERS_ONLY).toBe(false);
    expect(service.cacheStatusServerChatCount_FOR_HANDLERS_ONLY).toBe(1);
    expect(service.scheduleCacheStatusRetry_FOR_HANDLERS_ONLY).toHaveBeenCalledTimes(1);
    expect(service.attemptInitialSync_FOR_HANDLERS_ONLY).not.toHaveBeenCalled();
  });

  it("starts initial sync when sync status reports a primed cache", async () => {
    const service = createService();

    await handleSyncStatusResponseImpl(service as unknown as ChatSynchronizationService, {
      is_primed: true,
      chat_count: 1,
      timestamp: 1778683517,
    });

    expect(service.cachePrimed_FOR_HANDLERS_ONLY).toBe(true);
    expect(service.attemptInitialSync_FOR_HANDLERS_ONLY).toHaveBeenCalledTimes(1);
    expect(service.scheduleCacheStatusRetry_FOR_HANDLERS_ONLY).not.toHaveBeenCalled();
  });
});

describe("ChatSynchronizationService cache status retry", () => {
  it("does not mark sync complete when cache is cold but server reports chats", () => {
    vi.useFakeTimers();
    const service = Object.create(
      ChatSynchronizationServiceClass.prototype,
    ) as RetryServiceHarness;

    service.cachePrimed = false;
    service.cacheStatusRetryCount = 10;
    service.cacheStatusServerChatCount = 1;
    service.cacheStatusRetryTimer = null;
    service.webSocketConnected = true;
    service.dispatchSyncTimeoutComplete = vi.fn();
    service.requestCacheStatus = vi.fn();

    service.scheduleCacheStatusRetry_FOR_HANDLERS_ONLY();

    expect(service.dispatchSyncTimeoutComplete).not.toHaveBeenCalled();
    expect(service.cacheStatusRetryCount).toBe(1);

    vi.runOnlyPendingTimers();
    expect(service.requestCacheStatus).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});

/**
 * frontend/packages/ui/src/stores/__tests__/serverStatusStore.test.ts
 *
 * Regression coverage for signup Free testing promotion visibility. The public
 * server status remains raw/safe metadata, while signup display is gated by a
 * first-party device flag after the browser/account has received a grant.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import {
  FREE_TESTING_CREDITS_DEVICE_GRANT_STORAGE_KEY,
  freeTestingCreditsDeviceGrantReceived,
  freeTestingCreditsPromotion,
  hasDeviceReceivedFreeTestingCredits,
  markDeviceReceivedFreeTestingCredits,
  markDeviceReceivedFreeTestingCreditsFromNotification,
  refreshFreeTestingCreditsDeviceGrantFromStorage,
  serverStatusStore,
  signupFreeTestingCreditsPromotion,
} from "../serverStatusStore";

function installLocalStorageMock() {
  const values = new Map<string, string>();
  const storage = {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      values.set(key, value);
    }),
    removeItem: vi.fn((key: string) => {
      values.delete(key);
    }),
    clear: vi.fn(() => {
      values.clear();
    }),
  } as unknown as Storage;

  Object.defineProperty(globalThis, "localStorage", {
    value: storage,
    configurable: true,
  });
  return storage;
}

function setActivePromotion(): void {
  serverStatusStore.set({
    status: {
      is_self_hosted: false,
      payment_enabled: true,
      server_edition: "development",
      domain: "app.dev.openmates.org",
      ai_models_configured: true,
      free_testing_credits: {
        active: true,
        grant_credits: 1000,
      },
    },
    initialized: true,
    loading: false,
    error: null,
  });
}

describe("serverStatusStore Free testing promotion", () => {
  let storage: Storage;

  beforeEach(() => {
    vi.restoreAllMocks();
    storage = installLocalStorageMock();
    freeTestingCreditsDeviceGrantReceived.set(false);
    serverStatusStore.set({
      status: null,
      initialized: false,
      loading: false,
      error: null,
    });
  });

  it("shows active public promotion when the local device flag is absent", () => {
    setActivePromotion();

    expect(get(freeTestingCreditsPromotion)).toEqual({
      active: true,
      grant_credits: 1000,
    });
    expect(get(signupFreeTestingCreditsPromotion)).toEqual({
      active: true,
      grant_credits: 1000,
    });
  });

  it("hides signup promotion after the device is marked as already granted", () => {
    setActivePromotion();

    markDeviceReceivedFreeTestingCredits();

    expect(storage.getItem(FREE_TESTING_CREDITS_DEVICE_GRANT_STORAGE_KEY)).toBe("true");
    expect(hasDeviceReceivedFreeTestingCredits()).toBe(true);
    expect(get(freeTestingCreditsPromotion)).toEqual({
      active: true,
      grant_credits: 1000,
    });
    expect(get(signupFreeTestingCreditsPromotion)).toBeNull();
  });

  it("marks the device when the Free testing grant notification is observed", () => {
    setActivePromotion();

    markDeviceReceivedFreeTestingCreditsFromNotification("signup.free_testing_credits_received");

    expect(hasDeviceReceivedFreeTestingCredits()).toBe(true);
    expect(get(signupFreeTestingCreditsPromotion)).toBeNull();
  });

  it("fails closed when localStorage reads throw", () => {
    setActivePromotion();
    vi.mocked(storage.getItem).mockImplementation(() => {
      throw new Error("blocked storage");
    });

    refreshFreeTestingCreditsDeviceGrantFromStorage();

    expect(hasDeviceReceivedFreeTestingCredits()).toBe(false);
    expect(get(signupFreeTestingCreditsPromotion)).toEqual({
      active: true,
      grant_credits: 1000,
    });
  });
});

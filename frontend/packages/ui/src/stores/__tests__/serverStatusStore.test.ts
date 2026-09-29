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
  PENDING_GIFT_CARD_CODE_STORAGE_KEY,
  anonymousFreeUsageStatus,
  clearPendingGiftCardRedemption,
  freeTestingCreditsDeviceGrantReceived,
  freeTestingCreditsPromotion,
  getPendingGiftCardRedemptionCode,
  hasDeviceReceivedFreeTestingCredits,
  markDeviceReceivedFreeTestingCredits,
  markDeviceReceivedFreeTestingCreditsFromNotification,
  markPendingGiftCardRedemption,
  pendingGiftCardRedemption,
  refreshFreeTestingCreditsDeviceGrantFromStorage,
  refreshAnonymousFreeUsageStatus,
  refreshPendingGiftCardRedemptionFromStorage,
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

function installSessionStorageMock() {
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

  Object.defineProperty(globalThis, "sessionStorage", {
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
  let sessionStorageMock: Storage;

  beforeEach(() => {
    vi.restoreAllMocks();
    storage = installLocalStorageMock();
    sessionStorageMock = installSessionStorageMock();
    freeTestingCreditsDeviceGrantReceived.set(false);
    pendingGiftCardRedemption.set(false);
    serverStatusStore.set({
      status: null,
      initialized: false,
      loading: false,
      error: null,
    });
  });

  // contract-test: supporting surface=gui.web assertions=billing.purchase.provider-routing
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

  // contract-test: supporting surface=gui.web assertions=billing.purchase.provider-routing
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

  // contract-test: supporting surface=gui.web assertions=billing.purchase.provider-routing
  it("marks the device when the Free testing grant notification is observed", () => {
    setActivePromotion();

    markDeviceReceivedFreeTestingCreditsFromNotification("signup.free_testing_credits_received");

    expect(hasDeviceReceivedFreeTestingCredits()).toBe(true);
    expect(get(signupFreeTestingCreditsPromotion)).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=billing.purchase.provider-routing
  it("hides signup promotion while a gift-card redemption is pending", () => {
    setActivePromotion();

    markPendingGiftCardRedemption("AB23-CDEF-4567");

    expect(sessionStorageMock.getItem(PENDING_GIFT_CARD_CODE_STORAGE_KEY)).toBe("AB23-CDEF-4567");
    expect(getPendingGiftCardRedemptionCode()).toBe("AB23-CDEF-4567");
    expect(get(pendingGiftCardRedemption)).toBe(true);
    expect(get(signupFreeTestingCreditsPromotion)).toBeNull();

    clearPendingGiftCardRedemption();

    expect(sessionStorageMock.getItem(PENDING_GIFT_CARD_CODE_STORAGE_KEY)).toBeNull();
    expect(get(pendingGiftCardRedemption)).toBe(false);
    expect(get(signupFreeTestingCreditsPromotion)).toEqual({
      active: true,
      grant_credits: 1000,
    });
  });

  // contract-test: supporting surface=gui.web assertions=billing.purchase.provider-routing
  it("refreshes pending gift-card state from sessionStorage", () => {
    setActivePromotion();
    sessionStorageMock.setItem(PENDING_GIFT_CARD_CODE_STORAGE_KEY, "AB23-CDEF-4567");

    refreshPendingGiftCardRedemptionFromStorage();

    expect(get(pendingGiftCardRedemption)).toBe(true);
    expect(get(signupFreeTestingCreditsPromotion)).toBeNull();
  });

  // contract-test: supporting surface=gui.web assertions=billing.purchase.provider-routing
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

describe("serverStatusStore anonymous free usage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    installLocalStorageMock();
    serverStatusStore.set({
      status: {
        is_self_hosted: false,
        server_edition: "development",
        domain: "app.dev.openmates.org",
        ai_models_configured: true,
        anonymous_free_usage: { active: true },
      },
      initialized: true,
      loading: false,
      error: null,
    });
  });

  // contract-test: supporting surface=gui.web assertions=billing.self-host.cloud-guard
  it("leaves anonymous usage unavailable without requesting the cloud endpoint on self-host", async () => {
    serverStatusStore.update((state) => ({
      ...state,
      status: state.status ? { ...state.status, is_self_hosted: true } : null,
    }));
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(await refreshAnonymousFreeUsageStatus()).toBeNull();
    expect(get(anonymousFreeUsageStatus)).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=billing.self-host.cloud-guard
  it("treats an in-flight self-host 404 as unavailable", async () => {
    let resolveResponse!: (response: Response) => void;
    vi.spyOn(globalThis, "fetch").mockImplementation(() => new Promise(resolve => {
      resolveResponse = resolve;
    }));
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    const refresh = refreshAnonymousFreeUsageStatus();
    serverStatusStore.update((state) => ({
      ...state,
      status: state.status ? { ...state.status, is_self_hosted: true } : null,
    }));
    resolveResponse({ ok: false, status: 404 } as Response);

    expect(await refresh).toBeNull();
    expect(get(anonymousFreeUsageStatus)).toBeNull();
    expect(errorSpy).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=billing.anonymous.daily-remaining-percent
  it.each([404, 500])("still reports cloud HTTP %i failures", async (status) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: false, status } as Response);
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(await refreshAnonymousFreeUsageStatus()).toBeNull();
    expect(errorSpy).toHaveBeenCalledWith(
      "[ServerStatusStore] Error fetching anonymous free usage status:",
      `Failed to fetch anonymous free usage status: ${status}`,
    );
  });
});

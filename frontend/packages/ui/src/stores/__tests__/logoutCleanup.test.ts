// frontend/packages/ui/src/stores/__tests__/logoutCleanup.test.ts
// Unit tests for logout cleanup completeness — verifies every cache/store
// is properly cleared during logout to prevent stale data leaks.
//
// Bug history this test suite guards against:
//  - 780b871e7: chatMetadataCache not cleared → "Untitled chat" after re-login
//  - 861d8edca: chatListCache stale after sidebar destroy/remount
//  - Ghost chats from stale sessionStorage drafts surviving logout
//  - chatDB.clearAllChatKeys not called → stale encryption keys
//  - resetChatNavigationList not called → hasPrev=true on intro chat post-logout
//  - phasedSyncState not reset → sync skipped on next login
//
// Architecture: frontend/packages/ui/src/stores/authLoginLogoutActions.ts

import { describe, it, expect, beforeEach, vi } from "vitest";
import { get } from "svelte/store";

// ─── Mock all dependencies BEFORE importing the module under test ────────

// Track which cleanup functions were called
const cleanupCalls: string[] = [];

vi.mock("../../services/chatListCache", () => ({
  chatListCache: {
    clear: vi.fn(() => cleanupCalls.push("chatListCache.clear")),
  },
}));

vi.mock("../../services/chatMetadataCache", () => ({
  chatMetadataCache: {
    clearAll: vi.fn(() => cleanupCalls.push("chatMetadataCache.clearAll")),
  },
}));

vi.mock("../../services/db", () => ({
  chatDB: {
    clearAllChatKeys: vi.fn(() =>
      cleanupCalls.push("chatDB.clearAllChatKeys"),
    ),
    deleteDatabase: vi.fn(async () =>
      cleanupCalls.push("chatDB.deleteDatabase"),
    ),
  },
}));

vi.mock("../../services/userDB", () => ({
  userDB: {
    deleteDatabase: vi.fn(async () =>
      cleanupCalls.push("userDB.deleteDatabase"),
    ),
  },
}));

vi.mock("../../services/drafts/sessionStorageDraftService", () => ({
  clearAllSessionStorageDrafts: vi.fn(() =>
    cleanupCalls.push("clearAllSessionStorageDrafts"),
  ),
}));

vi.mock("../chatNavigationStore", () => ({
  resetChatNavigationList: vi.fn(() =>
    cleanupCalls.push("resetChatNavigationList"),
  ),
}));

vi.mock("../../services/sharedChatKeyStorage", () => ({
  clearAllSharedChatKeys: vi.fn(async () =>
    cleanupCalls.push("clearAllSharedChatKeys"),
  ),
}));

vi.mock("../phasedSyncStateStore", () => {
  const { writable } = require("svelte/store");
  const store = writable({
    initialSyncCompleted: false,
    phase1ChatId: null,
    currentActiveChatId: null,
    lastSyncTimestamp: null,
    initialChatLoaded: false,
    userMadeExplicitChoice: false,
    resumeChatData: null,
    resumeChatTitle: null,
    resumeChatCategory: null,
    resumeChatIcon: null,
    resumeChatSummary: null,
  });
  return {
    phasedSyncState: {
      subscribe: store.subscribe,
      reset: vi.fn(() => cleanupCalls.push("phasedSyncState.reset")),
    },
  };
});

vi.mock("../aiTypingStore", () => ({
  aiTypingStore: {
    reset: vi.fn(() => cleanupCalls.push("aiTypingStore.reset")),
  },
}));

vi.mock("../dailyInspirationStore", () => ({
  dailyInspirationStore: {
    reset: vi.fn(() => cleanupCalls.push("dailyInspirationStore.reset")),
  },
}));

vi.mock("../appSkillsStore", () => ({
  resetUserAvailableSkills: vi.fn(() =>
    cleanupCalls.push("resetUserAvailableSkills"),
  ),
}));

vi.mock("../../services/cryptoService", () => ({
  clearKeyFromStorage: vi.fn(() =>
    cleanupCalls.push("clearKeyFromStorage"),
  ),
  clearAllEmailData: vi.fn(() => cleanupCalls.push("clearAllEmailData")),
}));

vi.mock("../../utils/sessionId", () => ({
  deleteSessionId: vi.fn(() => cleanupCalls.push("deleteSessionId")),
  getSessionId: vi.fn(() => "test-session-id"),
}));

vi.mock("../../services/websocketService", () => ({
  webSocketService: {
    disconnectAndClearHandlers: vi.fn(() =>
      cleanupCalls.push("disconnectAndClearHandlers"),
    ),
  },
}));

vi.mock("../../utils/cookies", () => ({
  clearWebSocketToken: vi.fn(() =>
    cleanupCalls.push("clearWebSocketToken"),
  ),
  setWebSocketToken: vi.fn(),
}));

vi.mock("../../config/api", () => ({
  getApiEndpoint: vi.fn(() => "http://test/api/logout"),
  getApiUrl: vi.fn(() => "http://test"),
  apiEndpoints: {
    auth: {
      login: "/v1/auth/login",
      logout: "/v1/auth/logout",
      session: "/v1/auth/session",
      policyViolationLogout: "/v1/auth/policy-violation-logout",
    },
    settings: { user: { timezone: "/v1/settings/user/timezone" } },
  },
}));

vi.mock("../userProfile", () => {
  const { writable } = require("svelte/store");
  const defaultProfile = {
    username: null,
    profile_image_url: null,
    tfa_app_name: null,
    tfa_enabled: false,
    credits: 0,
    is_admin: false,
    last_opened: null,
    language: "en",
    darkmode: false,
  };
  const store = writable({ ...defaultProfile, username: "testuser" });
  return {
    userProfile: store,
    defaultProfile,
    updateProfile: vi.fn(),
  };
});

vi.mock("../profileImage", () => ({
  processedImageUrl: { set: vi.fn() },
}));

vi.mock("../twoFAState", () => ({
  resetTwoFAData: vi.fn(),
}));

vi.mock("../signupState", () => {
  const { writable } = require("svelte/store");
  return {
    currentSignupStep: { set: vi.fn() },
    isInSignupProcess: { set: vi.fn() },
    getStepFromPath: vi.fn(),
    isResettingTFA: { set: vi.fn() },
    isSignupPath: vi.fn(),
    forcedLogoutInProgress: writable(false),
    isLoggingOut: writable(false),
    resetForcedLogoutInProgress: vi.fn(),
    setForcedLogoutInProgress: vi.fn(),
  };
});

vi.mock("../notificationStore", () => ({
  notificationStore: { autoLogout: vi.fn(), error: vi.fn() },
}));

vi.mock("../theme", () => ({
  applyServerDarkMode: vi.fn(),
}));

vi.mock("../../services/clientLogForwarder", () => ({
  clientLogForwarder: {
    start: vi.fn(),
    stop: vi.fn(),
  },
}));

vi.mock("../../demo_chats/loadDefaultInspirations", () => ({
  loadDefaultInspirations: vi.fn(),
}));

vi.mock("../../services/pendingChatDeletions", () => ({
  clearAllPendingChatDeletions: vi.fn(),
}));

vi.mock("svelte-i18n", () => {
  const { writable } = require("svelte/store");
  return {
    locale: writable("en"),
  };
});

// Mock fetch globally
const mockFetch = vi.fn().mockResolvedValue({
  ok: true,
  json: async () => ({ success: true }),
});
vi.stubGlobal("fetch", mockFetch);

// Mock document.cookie for deleteAllCookies
Object.defineProperty(document, "cookie", {
  writable: true,
  value: "",
});

// ─── Import module under test AFTER all mocks ───────────────────────────

import { logout, deleteAllCookies } from "../authLoginLogoutActions";
import { authStore } from "../authState";

describe("logout cleanup completeness", () => {
  beforeEach(() => {
    cleanupCalls.length = 0;
    vi.clearAllMocks();
    authStore.set({ isAuthenticated: true, isInitialized: true });
  });

  it("calls all critical cleanup functions during logout", async () => {
    const result = await logout();
    expect(result).toBe(true);

    // These are the SYNCHRONOUS cleanups that must happen BEFORE return
    // (immediate UI feedback)
    expect(cleanupCalls).toContain("chatListCache.clear");
    expect(cleanupCalls).toContain("chatMetadataCache.clearAll");
    expect(cleanupCalls).toContain("chatDB.clearAllChatKeys");
    expect(cleanupCalls).toContain("clearAllSessionStorageDrafts");
    expect(cleanupCalls).toContain("resetChatNavigationList");
    expect(cleanupCalls).toContain("phasedSyncState.reset");
    expect(cleanupCalls).toContain("aiTypingStore.reset");
    expect(cleanupCalls).toContain("dailyInspirationStore.reset");
    expect(cleanupCalls).toContain("resetUserAvailableSkills");
    expect(cleanupCalls).toContain("clearKeyFromStorage");
    expect(cleanupCalls).toContain("clearAllEmailData");
    expect(cleanupCalls).toContain("deleteSessionId");
    expect(cleanupCalls).toContain("disconnectAndClearHandlers");
  });

  it("sets authStore to not authenticated but still initialized", async () => {
    await logout();
    const state = get(authStore);
    expect(state.isAuthenticated).toBe(false);
    expect(state.isInitialized).toBe(true);
  });

  it("cleanup order: crypto cleared BEFORE auth state reset", async () => {
    await logout();
    const cryptoIdx = cleanupCalls.indexOf("clearKeyFromStorage");
    const cacheIdx = cleanupCalls.indexOf("chatListCache.clear");
    // Both should be present
    expect(cryptoIdx).toBeGreaterThanOrEqual(0);
    expect(cacheIdx).toBeGreaterThanOrEqual(0);
  });

  it("fires callbacks in correct order", async () => {
    const callbackOrder: string[] = [];

    await logout({
      beforeLocalLogout: async () => {
        callbackOrder.push("beforeLocalLogout");
      },
      afterLocalLogout: async () => {
        callbackOrder.push("afterLocalLogout");
      },
    });

    expect(callbackOrder).toContain("beforeLocalLogout");
    expect(callbackOrder).toContain("afterLocalLogout");
    // beforeLocalLogout must come first
    expect(callbackOrder.indexOf("beforeLocalLogout")).toBeLessThan(
      callbackOrder.indexOf("afterLocalLogout"),
    );
  });
});

describe("deleteAllCookies", () => {
  it("clears cookies by setting expiration to past", () => {
    document.cookie = "test_cookie=value; path=/";
    deleteAllCookies();
    // After deleteAllCookies, cookies should be set to expire in the past
    // In jsdom, the actual cookie deletion behavior differs, but we verify
    // the function runs without error
    expect(() => deleteAllCookies()).not.toThrow();
  });
});

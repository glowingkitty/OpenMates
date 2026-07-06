// frontend/packages/ui/src/stores/__tests__/authSessionAutoLogoutCleanup.test.ts
// Regression coverage for session-expiry logout cleanup.
//
// Bug history this test guards against:
//  - X6EPA: /auth/session returned unauthenticated after token refresh failure,
//    but the old private chat stayed rendered because auto logout did not reset
//    the same in-memory chat/phased-sync state as manual logout.
//
// Architecture: frontend/packages/ui/src/stores/authSessionActions.ts

import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";

const cleanupCalls: string[] = [];

vi.mock("../../config/api", () => ({
  getApiEndpoint: vi.fn(() => "http://test/v1/auth/session"),
  getApiUrl: vi.fn(() => "http://test"),
  isDevEnvironment: vi.fn(() => false),
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

vi.mock("../signupRequirements", async () => {
  const { writable } = await import("svelte/store");
  return { requireInviteCode: writable(false) };
});

vi.mock("../../services/userDB", () => ({
  userDB: {
    deleteDatabase: vi.fn(async () => cleanupCalls.push("userDB.deleteDatabase")),
  },
}));

vi.mock("../../services/db", () => ({
  chatDB: {
    clearAllChatKeys: vi.fn(() => cleanupCalls.push("chatDB.clearAllChatKeys")),
    deleteDatabase: vi.fn(async () => cleanupCalls.push("chatDB.deleteDatabase")),
  },
}));

vi.mock("../userProfile", async () => {
  const { writable } = await import("svelte/store");
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
  const userProfile = writable({
    ...defaultProfile,
    username: "previous-user",
    user_id: "user-1",
  });
  return {
    userProfile,
    defaultProfile,
    updateProfile: vi.fn((profile) => {
      cleanupCalls.push("updateProfile");
      userProfile.update((current) => ({ ...current, ...profile }));
    }),
    loadUserProfileFromDB: vi.fn(),
  };
});

vi.mock("svelte-i18n", async () => {
  const { writable } = await import("svelte/store");
  return { locale: writable("en") };
});

vi.mock("../../services/cryptoService", () => ({
  getKeyFromStorage: vi.fn(async () => "stored-master-key"),
  clearKeyFromStorage: vi.fn(() => cleanupCalls.push("clearKeyFromStorage")),
  clearAllEmailData: vi.fn(() => cleanupCalls.push("clearAllEmailData")),
}));

vi.mock("../../utils/sessionId", () => ({
  getSessionId: vi.fn(() => "session-1"),
  deleteSessionId: vi.fn(() => cleanupCalls.push("deleteSessionId")),
}));

vi.mock("../../utils/cookies", () => ({
  setWebSocketToken: vi.fn(),
  clearWebSocketToken: vi.fn(() => cleanupCalls.push("clearWebSocketToken")),
}));

vi.mock("../notificationStore", () => ({
  notificationStore: {
    autoLogout: vi.fn(() => cleanupCalls.push("notificationStore.autoLogout")),
    error: vi.fn(),
  },
}));

vi.mock("../uiStateStore", async () => {
  const { writable } = await import("svelte/store");
  return {
    loginInterfaceOpen: writable(false),
    loginStayLoggedInRequested: writable(false),
  };
});

vi.mock("../activeChatStore", () => ({
  activeChatStore: {
    clearActiveChat: vi.fn(() => cleanupCalls.push("activeChatStore.clearActiveChat")),
    get: vi.fn(() => null),
    getChatIdFromHash: vi.fn(() => null),
  },
}));

vi.mock("../../services/drafts/sessionStorageDraftService", () => ({
  clearAllSessionStorageDrafts: vi.fn(() =>
    cleanupCalls.push("clearAllSessionStorageDrafts"),
  ),
}));

vi.mock("../signupState", async () => {
  const { writable } = await import("svelte/store");
  return {
    currentSignupStep: { set: vi.fn(() => cleanupCalls.push("currentSignupStep.set")) },
    isInSignupProcess: writable(false),
    getStepFromPath: vi.fn(),
    STEP_ALPHA_DISCLAIMER: "alpha-disclaimer",
    isSignupPath: vi.fn(() => false),
    isLoggingOut: writable(false),
    forcedLogoutInProgress: writable(false),
    setForcedLogoutInProgress: vi.fn(),
    resetForcedLogoutInProgress: vi.fn(),
  };
});

vi.mock("../phasedSyncStateStore", async () => {
  const { writable } = await import("svelte/store");
  const store = writable({
    initialSyncCompleted: true,
    phase1ChatId: null,
    currentActiveChatId: "old-private-chat",
    lastSyncTimestamp: null,
    initialChatLoaded: true,
    userMadeExplicitChoice: true,
    resumeChatData: null,
    resumeChatTitle: null,
    resumeChatCategory: null,
    resumeChatIcon: null,
    resumeChatSummary: null,
    recentChats: [],
  });
  return {
    NEW_CHAT_SENTINEL: "__new_chat__",
    phasedSyncState: {
      subscribe: store.subscribe,
      reset: vi.fn(() => cleanupCalls.push("phasedSyncState.reset")),
      resetForLogin: vi.fn(),
      markSyncCompleted: vi.fn(() => cleanupCalls.push("phasedSyncState.markSyncCompleted")),
      setCurrentActiveChatId: vi.fn((chatId) =>
        cleanupCalls.push(`phasedSyncState.setCurrentActiveChatId:${chatId}`),
      ),
      markUserMadeExplicitChoice: vi.fn(() =>
        cleanupCalls.push("phasedSyncState.markUserMadeExplicitChoice"),
      ),
    },
  };
});

vi.mock("../../i18n/translations", async () => {
  const { writable } = await import("svelte/store");
  return { text: writable((key: string) => key) };
});

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

vi.mock("../../services/sharedChatKeyStorage", () => ({
  clearAllSharedChatKeys: vi.fn(async () => cleanupCalls.push("clearAllSharedChatKeys")),
}));

vi.mock("../../services/clientLogForwarder", () => ({
  clientLogForwarder: {
    start: vi.fn(),
    stop: vi.fn(() => cleanupCalls.push("clientLogForwarder.stop")),
    stopEphemeral: vi.fn(() => cleanupCalls.push("clientLogForwarder.stopEphemeral")),
  },
}));

vi.mock("../appSettingsMemoriesStore", () => ({
  appSettingsMemoriesStore: { loadEntries: vi.fn(async () => undefined) },
}));

vi.mock("../theme", () => ({
  applyServerDarkMode: vi.fn(),
}));

vi.mock("../uiFont", () => ({
  applyServerUiFont: vi.fn(),
}));

vi.mock("../../services/topicPreferencesSync", () => ({
  promoteGuestTopicPreferencesIfNeeded: vi.fn(async () => undefined),
}));

vi.mock("../../services/referralService", () => ({
  captureReferralCodeFromUrl: vi.fn(),
  submitPendingReferralCode: vi.fn(async () => undefined),
}));

vi.mock("../serverStatusStore", () => ({
  markDeviceReceivedFreeTestingCredits: vi.fn(),
}));

vi.mock("../twoFAState", () => ({
  resetTwoFAData: vi.fn(() => cleanupCalls.push("resetTwoFAData")),
}));

vi.mock("../profileImage", () => ({
  processedImageUrl: { set: vi.fn(() => cleanupCalls.push("processedImageUrl.set")) },
}));

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
  resetUserAvailableSkills: vi.fn(() => cleanupCalls.push("resetUserAvailableSkills")),
}));

vi.mock("../chatNavigationStore", () => ({
  resetChatNavigationList: vi.fn(() => cleanupCalls.push("resetChatNavigationList")),
}));

vi.mock("../../services/websocketService", () => ({
  webSocketService: {
    disconnectAndClearHandlers: vi.fn(() =>
      cleanupCalls.push("disconnectAndClearHandlers"),
    ),
  },
}));

vi.mock("../../demo_chats/loadDefaultInspirations", () => ({
  loadDefaultInspirations: vi.fn(async () => cleanupCalls.push("loadDefaultInspirations")),
}));

vi.mock("../../services/pendingChatDeletions", () => ({
  clearAllPendingChatDeletions: vi.fn(() => cleanupCalls.push("clearAllPendingChatDeletions")),
}));

vi.mock("../../services/pendingAIResponses", () => ({
  clearAllPendingAIResponses: vi.fn(() => cleanupCalls.push("clearAllPendingAIResponses")),
}));

const mockFetch = vi.fn();
vi.stubGlobal("fetch", mockFetch);

const mockWindowDispatchEvent = vi.fn((event: { type: string }) => {
  cleanupCalls.push(`window.${event.type}`);
  return true;
});

class TestCustomEvent {
  readonly type: string;
  readonly detail: unknown;

  constructor(type: string, init?: CustomEventInit) {
    this.type = type;
    this.detail = init?.detail;
  }
}

vi.stubGlobal("CustomEvent", TestCustomEvent);
vi.stubGlobal("window", {
  location: {
    hash: "",
    origin: "http://test",
    search: "",
  },
  addEventListener: vi.fn(),
  dispatchEvent: mockWindowDispatchEvent,
  removeEventListener: vi.fn(),
});

function createStorageMock(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: vi.fn(() => values.clear()),
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    key: vi.fn((index: number) => Array.from(values.keys())[index] ?? null),
    removeItem: vi.fn((key: string) => values.delete(key)),
    setItem: vi.fn((key: string, value: string) => values.set(key, value)),
  };
}

vi.stubGlobal("localStorage", createStorageMock());
vi.stubGlobal("sessionStorage", createStorageMock());

import { checkAuth } from "../authSessionActions";
import { authStore } from "../authState";

describe("checkAuth auto logout cleanup", () => {
  beforeEach(() => {
    cleanupCalls.length = 0;
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    authStore.set({ isAuthenticated: true, isInitialized: false });
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ success: false, message: "not authenticated" }),
    });
  });

  it("clears the same in-memory chat state on session expiry as manual logout", async () => {
    const result = await checkAuth(undefined, true);

    expect(result).toBe(false);
    expect(mockWindowDispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: "userLoggingOut" }),
    );
    expect(cleanupCalls).toContain("window.userLoggingOut");
    expect(cleanupCalls).toContain("phasedSyncState.reset");
    expect(cleanupCalls).toContain("activeChatStore.clearActiveChat");
    expect(cleanupCalls).toContain("chatListCache.clear");
    expect(cleanupCalls).toContain("chatMetadataCache.clearAll");
    expect(cleanupCalls).toContain("chatDB.clearAllChatKeys");
    expect(cleanupCalls).toContain("clearAllSessionStorageDrafts");
    expect(cleanupCalls).toContain("resetChatNavigationList");
    expect(cleanupCalls).toContain("aiTypingStore.reset");

    const authState = get(authStore);
    expect(authState.isAuthenticated).toBe(false);
    expect(authState.isInitialized).toBe(true);
  });
});

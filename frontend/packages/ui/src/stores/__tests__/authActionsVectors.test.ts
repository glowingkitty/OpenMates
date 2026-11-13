// contract-test-file: tooling
// TypeScript-generated parity for the shared Rust login-reply and debug-session
// decisions: every login_verdict / debug_session_resume vector in
// webAuthFlowVectors.json is replayed through the deployed `login()` (flag off),
// so the same file pins the TypeScript behaviour and the Rust
// packages/openmates-rust/src/web_auth_actions.rs behaviour.
// Architecture: frontend/packages/ui/src/stores/authLoginLogoutActions.ts

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import vectors from "../../services/rustCore/auth/__tests__/webAuthFlowVectors.json";

// ─── Mock all dependencies BEFORE importing the module under test ────────

// Track which cleanup functions were called
const cleanupCalls: string[] = [];
let currentActiveChatId: string | null = "private-chat-1";
const userDatabaseDeleteGate: Promise<void> | null = null;
const downloadPurgeGate: Promise<void> | null = null;
const startedDebugSessions: string[] = [];

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
    saveUserData: vi.fn(async () => undefined),
    deleteDatabase: vi.fn(async () => {
      cleanupCalls.push("userDB.deleteDatabase");
      if (userDatabaseDeleteGate) await userDatabaseDeleteGate;
    }),
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

vi.mock("../activeChatStore", () => ({
  activeChatStore: {
    get: vi.fn(() => currentActiveChatId),
    clearActiveChat: vi.fn(() => {
      currentActiveChatId = null;
      cleanupCalls.push("activeChatStore.clearActiveChat");
    }),
  },
}));

vi.mock("../../demo_chats/exampleChatStore", () => ({
  isExampleChat: vi.fn((chatId: string) => chatId.startsWith("example-")),
}));

vi.mock("../../services/sharedChatKeyStorage", () => ({
  clearAllSharedChatKeys: vi.fn(async () =>
    cleanupCalls.push("clearAllSharedChatKeys"),
  ),
}));

vi.mock("../../services/projectRemoteDownload", () => ({
  purgeConnectedProjectDownloadStaging: vi.fn(async () => {
    cleanupCalls.push("purgeConnectedProjectDownloadStaging");
    if (downloadPurgeGate) await downloadPurgeGate;
  }),
}));

vi.mock("../phasedSyncStateStore", async () => {
  const { writable } = await import("svelte/store");
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

vi.mock("../workflowWorkspaceStore", () => ({
  workflowWorkspaceStore: {
    reset: vi.fn(() => cleanupCalls.push("workflowWorkspaceStore.reset")),
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

vi.mock("../signupState", async () => {
  const { writable } = await import("svelte/store");
  return {
    currentSignupStep: { set: vi.fn() },
    isInSignupProcess: { set: vi.fn() },
    getStepFromPath: vi.fn(),
    isResettingTFA: { set: vi.fn() },
    isSignupPath: vi.fn(() => false),
    primeSignupLocation: vi.fn(async () => undefined),
    forcedLogoutInProgress: writable(false),
    isLoggingOut: writable(false),
    resetForcedLogoutInProgress: vi.fn(),
    setForcedLogoutInProgress: vi.fn(),
  };
});

vi.mock("../notificationStore", () => ({
  SECURITY_REMINDER_NOTIFICATION_DEDUPE_KEY: "security-reminder",
  notificationStore: {
    autoLogout: vi.fn(),
    error: vi.fn(),
    removeNotificationsByDedupeKey: vi.fn((dedupeKey: string) =>
      cleanupCalls.push(`notificationStore.removeNotificationsByDedupeKey:${dedupeKey}`),
    ),
  },
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

vi.mock("../serverStatusStore", () => ({
  markDeviceReceivedFreeTestingCredits: vi.fn(),
}));

vi.mock("../../services/clientLogForwarder", () => ({
  clientLogForwarder: {
    start: vi.fn(),
    stop: vi.fn(),
    stopEphemeral: vi.fn(),
    startEphemeral: vi.fn(),
    startDebugSession: (id: string) => startedDebugSessions.push(id),
  },
}));

vi.mock("../../demo_chats/loadDefaultInspirations", () => ({
  loadDefaultInspirations: vi.fn(),
  loadGuestOnboardingInspirations: vi.fn(),
}));

vi.mock("../../services/pendingChatDeletions", () => ({
  clearAllPendingChatDeletions: vi.fn(),
}));

vi.mock("svelte-i18n", async () => {
  const { writable } = await import("svelte/store");
  return {
    _: writable((key: string) => key),
    addMessages: vi.fn(),
    getLocaleFromNavigator: vi.fn(() => "en"),
    init: vi.fn(),
    locale: writable("en"),
    register: vi.fn(),
    waitLocale: vi.fn(async () => undefined),
  };
});

// Mock fetch globally
const mockFetch = vi.fn().mockResolvedValue({
  ok: true,
  json: async () => ({ success: true }),
});
vi.stubGlobal("fetch", mockFetch);

// Mock document.cookie for deleteAllCookies
vi.stubGlobal("document", { cookie: "" });
Object.assign(window, {
  location: {
    hash: "",
    origin: "http://test",
    search: "",
  },
});
vi.mock("../../i18n/setup", () => ({
  applyAccountLanguage: vi.fn(async (language: string) => language),
}));
vi.mock("../authBootstrapReadiness", () => ({
  recoverAuthBootstrapAfterConfirmedSession: vi.fn(),
}));
vi.mock("../uiStateStore", () => ({ loginInterfaceOpen: { set: vi.fn() } }));

import { login } from "../authLoginLogoutActions";

interface Vector { op: string; args: Record<string, unknown>; expect: Record<string, unknown> }
const all = vectors.vectors as Vector[];

function reply(status: number, body: string | null) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => JSON.parse(body ?? "null"),
    text: async () => body ?? "",
    clone() { return this; },
  };
}

describe("login reply decisions (login_verdict vectors)", () => {
  beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); });

  it("classifies every vector like the deployed login()", async () => {
    for (const vector of all.filter((v) => v.op === "login_verdict")) {
      mockFetch.mockResolvedValue(reply(vector.args.status as number, vector.args.body as string | null));
      const got = await login("h", "l", vector.args.tfaCodeGiven ? "123456" : undefined, "otp");
      const want = vector.expect;
      const label = JSON.stringify(vector);
      switch (want.kind) {
        case "tfa_required":
          expect(got, label).toEqual({ success: true, tfa_required: true, tfa_app_name: want.tfaAppName ?? undefined });
          break;
        case "success":
          expect(got.success, label).toBe(true);
          expect(got.tfa_required, label).toBe(false);
          expect(got.backup_code_used, label).toBe(want.backupCodeUsed);
          expect(got.remaining_backup_codes, label).toEqual(want.remainingBackupCodes ?? undefined);
          break;
        default:
          expect(got, label).toEqual({ success: false, tfa_required: want.tfaRequired, message: want.message });
      }
    }
  });
});

describe("debug session resume (debug_session_resume vectors)", () => {
  beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); startedDebugSessions.length = 0; });
  afterEach(() => { vi.useRealTimers(); });

  it("starts or drops the stored record like the deployed login()", async () => {
    for (const vector of all.filter((v) => v.op === "debug_session_resume")) {
      localStorage.clear();
      startedDebugSessions.length = 0;
      const record: Record<string, unknown> = { debugging_id: vector.args.debuggingId };
      if (vector.args.hasExpiry) {
        record.expires_at = vector.args.expiresAtMs === null ? "not a date" : new Date(vector.args.expiresAtMs as number).toISOString();
      }
      localStorage.setItem("debug_session", JSON.stringify(record));
      mockFetch.mockResolvedValue(reply(200, JSON.stringify({ success: true, user: { username: "u" } })));
      // Only Date.now() is faked, so login()'s promises still settle.
      vi.useFakeTimers({ toFake: ["Date"] });
      vi.setSystemTime(vector.args.nowMs as number);
      await login("h", "l");
      vi.useRealTimers();
      const label = JSON.stringify(vector);
      if (vector.expect.action === "start") {
        expect(startedDebugSessions, label).toEqual([vector.expect.debuggingId]);
        expect(localStorage.getItem("debug_session"), label).not.toBeNull();
      } else {
        expect(startedDebugSessions, label).toEqual([]);
        expect(localStorage.getItem("debug_session"), label).toBeNull();
      }
    }
  });
});

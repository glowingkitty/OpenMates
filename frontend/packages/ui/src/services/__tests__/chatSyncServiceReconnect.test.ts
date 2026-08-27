// frontend/packages/ui/src/services/__tests__/chatSyncServiceReconnect.test.ts
// Regression coverage for WebSocket reconnect sync state.
// A reconnect after an earlier successful phased sync must still be allowed to
// run phased rediscovery, because the browser may have missed draft-only chats
// that were created while the socket was disconnected.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type WebSocketStatusValue = {
  status: "connecting" | "connected" | "disconnected" | "error" | "reconnecting";
  lastMessage: string | null;
  error: string | null;
};

const mocks = vi.hoisted(() => {
  type Subscriber<T> = (value: T) => void;
  const createReadable = <T>(value: T) => ({
    subscribe: vi.fn((run: Subscriber<T>) => {
      run(value);
      return () => undefined;
    }),
  });

  let websocketState: WebSocketStatusValue = {
    status: "disconnected",
    lastMessage: null,
    error: null,
  };
  const websocketSubscribers = new Set<Subscriber<WebSocketStatusValue>>();

  return {
    websocketStatus: {
      subscribe: vi.fn((run: Subscriber<WebSocketStatusValue>) => {
        websocketSubscribers.add(run);
        run(websocketState);
        return () => websocketSubscribers.delete(run);
      }),
      setStatus: vi.fn(),
      setError: vi.fn(),
      reset: vi.fn(),
    },
    emitWebSocketStatus(status: WebSocketStatusValue["status"]) {
      websocketState = { status, lastMessage: null, error: null };
      websocketSubscribers.forEach((run) => run(websocketState));
    },
    webSocketService: {
      addEventListener: vi.fn(),
      on: vi.fn(),
      sendMessage: vi.fn(),
    },
    chatDB: {
      getAllMessages: vi.fn(async () => []),
    },
    chatKeyManager: {
      getKeySync: vi.fn(),
      injectKey: vi.fn(),
    },
    notificationStore: {
      error: vi.fn(),
      addNotificationWithOptions: vi.fn(),
      removeNotificationsByDedupeKey: vi.fn(),
    },
    aiTypingStore: {
      clearTypingForChat: vi.fn(),
    },
    phasedSyncState: {
      reset: vi.fn(),
      markSyncCompleted: vi.fn(),
      markSyncPending: vi.fn(),
    },
    activeChatFocusStore: {
      setActiveFocus: vi.fn(),
    },
    activeChatStore: {
      clearActiveChat: vi.fn(),
    },
    chatListCache: {
      clear: vi.fn(),
    },
    chatMetadataCache: {
      clearAll: vi.fn(),
    },
    authStore: createReadable({ isAuthenticated: false }),
    forcedLogoutInProgress: createReadable(false),
    isLoggingOut: createReadable(false),
    activeTeamId: createReadable(null),
    activeTeamContext: createReadable({ team: null, teamId: null, epoch: 0 }),
    flushPendingEmbedOperations: vi.fn(async () => undefined),
    sendOfflineChangesImpl: vi.fn(async () => undefined),
    getCachedChatVersionMap: vi.fn(() => new Map()),
  };
});

vi.mock("../db", () => ({ chatDB: mocks.chatDB }));
vi.mock("../db/chatKeyManagement", () => ({
  getCachedChatVersionMap: mocks.getCachedChatVersionMap,
}));
vi.mock("../websocketService", () => ({
  webSocketService: mocks.webSocketService,
}));
vi.mock("../../stores/websocketStatusStore", () => ({
  websocketStatus: mocks.websocketStatus,
}));
vi.mock("../../stores/notificationStore", () => ({
  notificationStore: mocks.notificationStore,
}));
vi.mock("../../stores/aiTypingStore", () => ({
  aiTypingStore: mocks.aiTypingStore,
}));
vi.mock("../../stores/phasedSyncStateStore", () => ({
  phasedSyncState: mocks.phasedSyncState,
}));
vi.mock("../../stores/activeChatFocusStore", () => ({
  activeChatFocusStore: mocks.activeChatFocusStore,
}));
vi.mock("../../stores/activeChatStore", () => ({
  activeChatStore: mocks.activeChatStore,
}));
vi.mock("../../stores/signupState", () => ({
  forcedLogoutInProgress: mocks.forcedLogoutInProgress,
  isLoggingOut: mocks.isLoggingOut,
}));
vi.mock("../../stores/authStore", () => ({
  authStore: mocks.authStore,
}));
vi.mock("../../stores/teamStore", () => ({
  activeTeamId: mocks.activeTeamId,
  activeTeamContext: mocks.activeTeamContext,
  TEAM_CONTEXT_CHANGED_EVENT: "team-context-changed",
}));
vi.mock("../encryption/ChatKeyManager", () => ({
  chatKeyManager: mocks.chatKeyManager,
}));
vi.mock("../chatListCache", () => ({ chatListCache: mocks.chatListCache }));
vi.mock("../chatMetadataCache", () => ({
  chatMetadataCache: mocks.chatMetadataCache,
}));
vi.mock("../teamService", () => ({
  getTeam: vi.fn(),
  unwrapTeamChatKey: vi.fn(),
}));
vi.mock("../embedSenders", () => ({
  flushPendingEmbedOperations: mocks.flushPendingEmbedOperations,
}));
vi.mock("../chatSyncServiceSenders", () => ({
  sendOfflineChangesImpl: mocks.sendOfflineChangesImpl,
}));
vi.mock("../connectedAccountTokenBrokerService", () => ({
  prepareConnectedAccountSendContext: vi.fn(),
}));
vi.mock("../connectedAccountStorageService", () => ({
  buildConnectedAccountSendContext: vi.fn(),
  listConnectedAccounts: vi.fn(),
}));
vi.mock("../chatSyncServiceHandlersRecovery", () => ({
  handleRecoveryJobsAvailableImpl: vi.fn(),
}));
vi.mock("../chatSyncServiceHandlersAI", () => ({}));
vi.mock("../chatSyncServiceHandlersChatUpdates", () => ({}));
vi.mock("../chatSyncServiceHandlersCoreSync", () => ({}));
vi.mock("../chatSyncServiceHandlersPhasedSync", () => ({}));
vi.mock("../chatSyncServiceHandlersAppSettings", () => ({}));
vi.mock("../chatSyncServiceHandlersConnectedAccounts", () => ({}));
vi.mock("../chatSyncServiceHandlersWebhooks", () => ({}));

import { chatSyncService } from "../chatSyncService";

describe("ChatSynchronizationService reconnect sync state", () => {
  beforeEach(async () => {
    vi.clearAllMocks();
    await Promise.resolve();
    mocks.emitWebSocketStatus("disconnected");
    chatSyncService.cachePrimed_FOR_HANDLERS_ONLY = true;
    chatSyncService.initialSyncAttempted_FOR_HANDLERS_ONLY = true;
    chatSyncService.markInitialSyncCompleted();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // contract-test: direct surface=gui.web assertions=sync.startup.bounded-phases,chat-navigation.draft-only.addressable
  it("allows phased sync to run after reconnect even when initial sync already completed", async () => {
    const startPhasedSync = vi
      .spyOn(chatSyncService, "startPhasedSync")
      .mockResolvedValue(undefined);

    mocks.emitWebSocketStatus("disconnected");

    expect(chatSyncService.initialSyncAttempted_FOR_HANDLERS_ONLY).toBe(false);

    mocks.emitWebSocketStatus("connected");
    await Promise.resolve();

    expect(startPhasedSync).toHaveBeenCalledTimes(1);
  });
});

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
  const createMutableReadable = <T>(initial: T) => {
    let value = initial;
    return {
      subscribe: vi.fn((run: Subscriber<T>) => {
        run(value);
        return () => undefined;
      }),
      set(next: T) { value = next; },
    };
  };

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
      isConnected: vi.fn(() => false),
      forceReconnect: vi.fn(),
    },
    chatDB: {
      getAllMessages: vi.fn(async () => []),
      getChat: vi.fn(),
      addChat: vi.fn(),
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
    aiTypingByChatStore: createReadable({}),
    workspaceIdentity: 'account-a',
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
    checkAuth: vi.fn(async () => false),
    forcedLogoutInProgress: createReadable(false),
    isLoggingOut: createReadable(false),
    activeTeamId: createMutableReadable<string | null>(null),
    activeTeamContext: createMutableReadable<{ team: null; teamId: string | null; epoch: number }>({ team: null, teamId: null, epoch: 0 }),
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
  aiTypingByChatStore: mocks.aiTypingByChatStore,
}));
vi.mock("../workspaceQueryCache", async (importOriginal) => ({
  ...await importOriginal<typeof import('../workspaceQueryCache')>(),
  getWorkspaceCacheIdentity: () => mocks.workspaceIdentity,
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
  checkAuth: mocks.checkAuth,
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
  TeamRequestCancelledError: class TeamRequestCancelledError extends Error {},
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
  prepareRecoveryLifecycleImpl: vi.fn(),
  resetRecoveryLifecycleImpl: vi.fn(),
}));
vi.mock("../chatSyncServiceHandlersAI", () => ({}));
vi.mock("../chatSyncServiceHandlersChatUpdates", () => ({}));
vi.mock("../chatSyncServiceHandlersCoreSync", () => ({}));
vi.mock("../chatSyncServiceHandlersPhasedSync", () => ({}));
vi.mock("../chatSyncServiceHandlersAppSettings", () => ({}));
vi.mock("../chatSyncServiceHandlersConnectedAccounts", () => ({}));
vi.mock("../chatSyncServiceHandlersWebhooks", () => ({}));

import { ChatSynchronizationService, chatSyncService } from "../chatSyncService";
import { getTeam, TeamRequestCancelledError } from "../teamService";

describe("Team and Personal context cache handoff", () => {
  beforeEach(() => {
    mocks.emitWebSocketStatus("disconnected");
  });
  afterEach(() => {
    mocks.emitWebSocketStatus("disconnected");
    mocks.authStore.subscribe.mockImplementation(run => { run({ isAuthenticated: false }); return () => undefined; });
    mocks.activeTeamId.set(null);
    mocks.activeTeamContext.set({ team: null, teamId: null, epoch: 0 });
    vi.restoreAllMocks();
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
  it("requests authoritative account cache status before syncing returned Personal context", async () => {
    const service = new ChatSynchronizationService();
    await Promise.resolve();
    mocks.authStore.subscribe.mockImplementation(run => { run({ isAuthenticated: true }); return () => undefined; });
    vi.spyOn(service, "refreshChatActivity").mockResolvedValue(undefined);
    const startSync = vi.spyOn(service, "startPhasedSync").mockResolvedValue(undefined);
    (service as unknown as { webSocketConnected: boolean }).webSocketConnected = true;
    service.cachePrimed_FOR_HANDLERS_ONLY = true;
    mocks.webSocketService.sendMessage.mockClear();
    const context = { team: null, teamId: null, epoch: 2 };
    mocks.activeTeamId.set(null);
    mocks.activeTeamContext.set(context);

    await (service as unknown as { handleTeamContextChanged: (context: typeof context) => Promise<void> }).handleTeamContextChanged(context);

    expect(service.cachePrimed_FOR_HANDLERS_ONLY).toBe(false);
    expect(service.hasCompletedInitialSync_FOR_HANDLERS_ONLY).toBe(false);
    expect(mocks.webSocketService.sendMessage).toHaveBeenCalledWith("request_cache_status", {});
    expect(startSync).not.toHaveBeenCalled();
    expect((service as unknown as { isPayloadForActiveContext: (payload: { team_id: string; context_epoch: number }) => boolean })
      .isPayloadForActiveContext({ team_id: "old-team", context_epoch: 1 })).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local,teams.collaboration.realtime-team-sync
  it("starts Team sync directly and ignores late account cache responses", async () => {
    const service = new ChatSynchronizationService();
    await Promise.resolve();
    mocks.authStore.subscribe.mockImplementation(run => { run({ isAuthenticated: true }); return () => undefined; });
    vi.spyOn(service, "refreshChatActivity").mockResolvedValue(undefined);
    const startSync = vi.spyOn(service, "startPhasedSync").mockResolvedValue(undefined);
    (service as unknown as { webSocketConnected: boolean }).webSocketConnected = true;
    mocks.webSocketService.sendMessage.mockClear();
    const context = { team: null, teamId: "team-a", epoch: 1 };
    mocks.activeTeamId.set("team-a");
    mocks.activeTeamContext.set(context);

    await (service as unknown as { handleTeamContextChanged: (context: typeof context) => Promise<void> }).handleTeamContextChanged(context);

    expect(startSync).toHaveBeenCalledOnce();
    expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalledWith("request_cache_status", {});
    for (const type of ["cache_primed", "cache_status_response", "sync_status_response"]) {
      const registration = [...mocks.webSocketService.on.mock.calls].reverse().find(([name]) => name === type);
      expect(registration).toBeDefined();
      expect(() => registration![1]({})).not.toThrow();
    }
    expect(startSync).toHaveBeenCalledOnce();
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local,teams.collaboration.realtime-team-sync
  it("starts scoped sync for a restored Team on cold connection and reconnect", async () => {
    mocks.activeTeamId.set("restored-team");
    mocks.activeTeamContext.set({ team: null, teamId: "restored-team", epoch: 0 });
    const service = new ChatSynchronizationService();
    await Promise.resolve();
    const startSync = vi.spyOn(service, "startPhasedSync").mockResolvedValue(undefined);
    mocks.webSocketService.sendMessage.mockClear();

    mocks.emitWebSocketStatus("connected");
    expect(startSync).toHaveBeenCalledOnce();
    expect(service.initialSyncAttempted_FOR_HANDLERS_ONLY).toBe(true);
    expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalledWith("request_cache_status", {});

    mocks.emitWebSocketStatus("connected");
    expect(startSync).toHaveBeenCalledOnce();
    service.markInitialSyncCompleted();
    mocks.emitWebSocketStatus("disconnected");
    expect(service.initialSyncAttempted_FOR_HANDLERS_ONLY).toBe(false);
    mocks.emitWebSocketStatus("connected");
    expect(startSync).toHaveBeenCalledTimes(2);
    expect(mocks.webSocketService.sendMessage).not.toHaveBeenCalledWith("request_cache_status", {});
  });
});

describe("phased sync context cancellation", () => {
  afterEach(() => {
    mocks.activeTeamId.set(null);
    mocks.activeTeamContext.set({ team: null, teamId: null, epoch: 0 });
    vi.mocked(getTeam).mockReset();
    vi.restoreAllMocks();
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it("ignores a cancelled Team A lookup after Team B starts without ending Team B sync", async () => {
    const service = new ChatSynchronizationService();
    await Promise.resolve();
    (service as unknown as { webSocketConnected: boolean }).webSocketConnected = true;
    let rejectA!: (error: Error) => void;
    let rejectB!: (error: Error) => void;
    vi.mocked(getTeam)
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectA = reject; }))
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectB = reject; }));
    mocks.activeTeamId.set("team-a");
    mocks.activeTeamContext.set({ team: null, teamId: "team-a", epoch: 1 });
    const oldSync = service.startPhasedSync();
    mocks.activeTeamId.set("team-b");
    mocks.activeTeamContext.set({ team: null, teamId: "team-b", epoch: 2 });
    const newSync = service.startPhasedSync();
    const watchdog = setTimeout(() => undefined, 30_000);
    (service as unknown as { phasedSyncTimeout: ReturnType<typeof setTimeout> }).phasedSyncTimeout = watchdog;
    const clearTimeoutSpy = vi.spyOn(
      service as unknown as { clearPhasedSyncTimeout: () => void },
      "clearPhasedSyncTimeout",
    );
    const completion = vi.fn();
    service.addEventListener("phasedSyncComplete", completion);
    mocks.notificationStore.error.mockClear();
    try {
      rejectA(new TeamRequestCancelledError("Team request cancelled"));
      await oldSync;
      expect(mocks.notificationStore.error).not.toHaveBeenCalled();
      expect(clearTimeoutSpy).not.toHaveBeenCalled();
      expect(completion).not.toHaveBeenCalled();
      expect((service as unknown as { phasedSyncTimeout: unknown }).phasedSyncTimeout).toBe(watchdog);
    } finally {
      service.removeEventListener("phasedSyncComplete", completion);
      mocks.activeTeamContext.set({ team: null, teamId: null, epoch: 3 });
      rejectB(new TeamRequestCancelledError("Team request cancelled"));
      await newSync;
      clearTimeout(watchdog);
    }
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it("lets only the latest same-context attempt handle a lookup failure", async () => {
    const service = new ChatSynchronizationService();
    await Promise.resolve();
    (service as unknown as { webSocketConnected: boolean }).webSocketConnected = true;
    mocks.activeTeamId.set("team-a");
    mocks.activeTeamContext.set({ team: null, teamId: "team-a", epoch: 1 });
    let rejectOld!: (error: Error) => void;
    let rejectLatest!: (error: Error) => void;
    vi.mocked(getTeam)
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectOld = reject; }))
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectLatest = reject; }));
    const oldSync = service.startPhasedSync();
    const latestSync = service.startPhasedSync();
    const watchdog = setTimeout(() => undefined, 30_000);
    (service as unknown as { phasedSyncTimeout: ReturnType<typeof setTimeout> }).phasedSyncTimeout = watchdog;
    const clearTimeoutSpy = vi.spyOn(
      service as unknown as { clearPhasedSyncTimeout: () => void },
      "clearPhasedSyncTimeout",
    );
    const completion = vi.fn();
    service.addEventListener("phasedSyncComplete", completion);
    mocks.notificationStore.error.mockClear();
    try {
      rejectOld(new TeamRequestCancelledError("Obsolete Team lookup"));
      await oldSync;
      expect(mocks.notificationStore.error).not.toHaveBeenCalled();
      expect(clearTimeoutSpy).not.toHaveBeenCalled();
      expect(completion).not.toHaveBeenCalled();
      expect((service as unknown as { phasedSyncTimeout: unknown }).phasedSyncTimeout).toBe(watchdog);

      rejectLatest(new Error("Current Team lookup failed"));
      await latestSync;
      expect(mocks.notificationStore.error).toHaveBeenCalledExactlyOnceWith("Failed to start chat synchronization.");
      expect(clearTimeoutSpy).toHaveBeenCalledOnce();
      expect(completion).toHaveBeenCalledOnce();
    } finally {
      service.removeEventListener("phasedSyncComplete", completion);
      clearTimeout(watchdog);
    }
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it("reports a genuine failure in the current Team context", async () => {
    const service = new ChatSynchronizationService();
    await Promise.resolve();
    (service as unknown as { webSocketConnected: boolean }).webSocketConnected = true;
    mocks.activeTeamId.set("team-a");
    mocks.activeTeamContext.set({ team: null, teamId: "team-a", epoch: 1 });
    vi.mocked(getTeam).mockRejectedValueOnce(new Error("Team metadata unavailable"));
    mocks.notificationStore.error.mockClear();
    const completion = vi.fn();
    service.addEventListener("phasedSyncComplete", completion);
    try {
      await service.startPhasedSync();
      expect(mocks.notificationStore.error).toHaveBeenCalledWith("Failed to start chat synchronization.");
      expect(completion).toHaveBeenCalledOnce();
    } finally {
      service.removeEventListener("phasedSyncComplete", completion);
    }
  });
});

describe('Sidebar metadata hydration', () => {
  beforeEach(() => {
    mocks.workspaceIdentity = 'account-a';
    mocks.authStore.subscribe.mockImplementation(run => { run({ isAuthenticated: true }); return () => undefined; });
    mocks.chatDB.getChat.mockReset(); mocks.chatDB.addChat.mockReset();
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ chats: [
      { id: 'old-chat', encrypted_title: 'cipher-title', encrypted_chat_key: 'cipher-key', created_at: '1700000000', updated_at: '1700000100', title_v: 1 },
    ] }) })));
  });
  afterEach(() => {
    mocks.authStore.subscribe.mockImplementation(run => { run({ isAuthenticated: false }); return () => undefined; });
    vi.unstubAllGlobals();
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.projects.nested-readable,chat-navigation.activity.global-running
  it('publishes the hidden-key classification and preserves old Unix-second timestamps', async () => {
    const classified = { chat_id: 'old-chat', is_hidden_candidate: true };
    mocks.chatDB.getChat.mockResolvedValueOnce(undefined).mockResolvedValueOnce(classified);
    const listener = vi.fn(); chatSyncService.addEventListener('chatUpdated', listener);
    try {
      await chatSyncService.hydrateSidebarChats(['old-chat']);
      expect(mocks.chatDB.addChat.mock.calls[0][0]).toMatchObject({ created_at: 1700000000, updated_at: 1700000100, last_edited_overall_timestamp: 1700000100 });
      expect(listener.mock.calls[0][0].detail.chat).toBe(classified);
    } finally { chatSyncService.removeEventListener('chatUpdated', listener); }
  });
  // contract-test: supporting surface=gui.web assertions=chat-navigation.projects.nested-readable
  it('rejects a save whose account changes during the asynchronous IndexedDB write', async () => {
    mocks.chatDB.getChat.mockResolvedValue(undefined);
    mocks.chatDB.addChat.mockImplementation(async (_chat, _transaction, options) => {
      mocks.workspaceIdentity = 'account-b'; options.writeGuard();
    });
    const listener = vi.fn(); chatSyncService.addEventListener('chatUpdated', listener);
    try {
      await expect(chatSyncService.hydrateSidebarChats(['old-chat'])).rejects.toThrow('Sidebar workspace changed');
      expect(listener).not.toHaveBeenCalled();
    } finally { chatSyncService.removeEventListener('chatUpdated', listener); }
  });
});

describe('authoritative chat activity on resume', () => {
  beforeEach(() => {
    mocks.checkAuth.mockClear();
    mocks.workspaceIdentity = 'account-a';
    mocks.authStore.subscribe.mockImplementation(run => { run({ isAuthenticated: true }); return () => undefined; });
    mocks.chatDB.addChat.mockReset();
    mocks.chatDB.getChat.mockImplementation(async (chatId) => ({ chat_id: chatId, user_id: 'account-a' }));
  });
  afterEach(() => {
    mocks.authStore.subscribe.mockImplementation(run => { run({ isAuthenticated: false }); return () => undefined; });
    vi.unstubAllGlobals();
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it('checks session authority once after a rejected activity snapshot', async () => {
    const service = new ChatSynchronizationService();
    await Promise.resolve();
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 401 })));
    await service.refreshChatActivity();
    expect(mocks.checkAuth).toHaveBeenCalledExactlyOnceWith(undefined, true);
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it('does not check a replacement account for a stale activity rejection', async () => {
    const service = new ChatSynchronizationService();
    await Promise.resolve();
    vi.stubGlobal('fetch', vi.fn(async () => {
      mocks.workspaceIdentity = 'account-b';
      return { ok: false, status: 401 };
    }));
    await service.refreshChatActivity();
    expect(mocks.checkAuth).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=auth.session.lifecycle
  it('preserves session state after a temporary activity failure', async () => {
    const service = new ChatSynchronizationService();
    await Promise.resolve();
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503 })));
    await service.refreshChatActivity();
    expect(mocks.checkAuth).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it('ends only the exact locally tracked task absent from the server activity snapshot', async () => {
    const service = new ChatSynchronizationService();
    // Constructor activity subscriptions mount in a microtask. Let that
    // initialization finish before capturing a resume snapshot revision.
    await Promise.resolve();
    service.activeAITasks.set('finished-chat', { taskId: 'assistant-1', userMessageId: 'user-1' });
    service.activeAITasks.set('running-chat', { taskId: 'assistant-2', userMessageId: 'user-2' });
    const now = Date.now();
    const clock = vi.spyOn(Date, 'now').mockReturnValue(now + 4_000);
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({
      active_tasks: [{ chat_id: 'running-chat', task_id: 'assistant-2' }], chats: [],
    }) })));
    const listener = vi.fn(); service.addEventListener('aiTaskEnded', listener);
    try {
      await service.refreshChatActivity();
      expect(fetch).toHaveBeenCalled();
      expect(service.activeAITasks.has('finished-chat')).toBe(false);
      expect(listener).toHaveBeenCalledTimes(1);
      expect(listener.mock.calls[0][0].detail).toEqual({
        chatId: 'finished-chat', taskId: 'assistant-1', userMessageId: 'user-1', status: 'completed',
      });
      expect(service.activeAITasks.get('running-chat')).toEqual({ taskId: 'assistant-2', userMessageId: 'user-2' });
      expect(service.activeAITasks.has('finished-chat')).toBe(false);
    } finally { service.removeEventListener('aiTaskEnded', listener); clock.mockRestore(); }
  });

  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it('makes a replacement task cancellable before notifying listeners that the older task ended', async () => {
    const service = new ChatSynchronizationService();
    await Promise.resolve();
    service.activeAITasks.set('same-chat', { taskId: 'older-assistant', userMessageId: 'older-user' });
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({
      active_tasks: [{ chat_id: 'same-chat', task_id: 'newer-assistant' }], chats: [],
    }) })));
    const listener = vi.fn((event: Event) => {
      expect((event as CustomEvent).detail.taskId).toBe('older-assistant');
      expect(service.getActiveAITaskIdForChat('same-chat')).toBe('newer-assistant');
    });
    service.addEventListener('aiTaskEnded', listener);
    try {
      await service.refreshChatActivity();
      expect(listener).toHaveBeenCalledTimes(1);
      expect(service.getActiveAITaskIdForChat('same-chat')).toBe('newer-assistant');
    } finally { service.removeEventListener('aiTaskEnded', listener); }
  });
});

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

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,chats.completion.lease-fenced
  it("retries a zero-chat synthetic completion only after a current-connection count", async () => {
    mocks.authStore.subscribe.mockImplementation(run => {
      run({ isAuthenticated: true });
      return () => undefined;
    });
    vi.spyOn(chatSyncService, "startPhasedSync").mockResolvedValue(undefined);
    const retry = vi.spyOn(chatSyncService as unknown as {
      retryPendingMessages: (afterCurrent?: boolean) => Promise<void>;
    }, "retryPendingMessages").mockResolvedValue(undefined);
    const timeoutComplete = () => chatSyncService.dispatchEvent(new CustomEvent("phasedSyncComplete", {
      detail: { synthetic: true, reason: "timeout" },
    }));
    mocks.emitWebSocketStatus("connected");
    retry.mockClear(); // The completed-session reconnect has its own ordinary retry.
    timeoutComplete();
    expect(retry).not.toHaveBeenCalled(); // The numeric default zero is not evidence.

    chatSyncService.cacheStatusServerChatCount_FOR_HANDLERS_ONLY = Number.NaN;
    timeoutComplete();
    expect(retry).not.toHaveBeenCalled();
    chatSyncService.cacheStatusServerChatCount_FOR_HANDLERS_ONLY = 0;
    mocks.emitWebSocketStatus("connected"); // Same socket status publication keeps its receipt.
    retry.mockClear();
    timeoutComplete();
    expect(retry).toHaveBeenCalledOnce();

    mocks.emitWebSocketStatus("disconnected");
    mocks.emitWebSocketStatus("connected");
    retry.mockClear();
    timeoutComplete();
    expect(retry).not.toHaveBeenCalled(); // The prior socket's zero was revoked.
    chatSyncService.cacheStatusServerChatCount_FOR_HANDLERS_ONLY = 2;
    timeoutComplete();
    expect(retry).not.toHaveBeenCalled();
    chatSyncService.cacheStatusServerChatCount_FOR_HANDLERS_ONLY = 0;
    timeoutComplete();
    expect(retry).toHaveBeenCalledOnce();

    window.dispatchEvent(new Event("userLoggingOut"));
    retry.mockClear();
    timeoutComplete();
    expect(retry).not.toHaveBeenCalled();
    mocks.authStore.subscribe.mockImplementation(run => {
      run({ isAuthenticated: false });
      return () => undefined;
    });
    chatSyncService.cacheStatusServerChatCount_FOR_HANDLERS_ONLY = 0;
    timeoutComplete();
    expect(retry).not.toHaveBeenCalled(); // A stale status cannot authorize a logged-out actor.
    mocks.authStore.subscribe.mockImplementation(run => {
      run({ isAuthenticated: true });
      return () => undefined;
    });
    chatSyncService.dispatchEvent(new CustomEvent("phasedSyncComplete", {
      detail: { synthetic: true, reason: "error" },
    }));
    expect(retry).not.toHaveBeenCalled();
  });

  // contract-test: supporting surface=gui.web assertions=sync.startup.bounded-phases
  it("does not force a reconnect when installing clients before the socket opens or repeating the same install", () => {
    const projectFileExecutor = { stop: vi.fn() };
    const remoteCommandClient = { stop: vi.fn() };

    const dispose = chatSyncService.installProjectAgentClients(
      projectFileExecutor as unknown as Parameters<typeof chatSyncService.installProjectAgentClients>[0],
      remoteCommandClient as unknown as Parameters<typeof chatSyncService.installProjectAgentClients>[1],
    );
    expect(mocks.webSocketService.forceReconnect).not.toHaveBeenCalled();

    mocks.webSocketService.isConnected.mockReturnValue(true);
    const repeatedDispose = chatSyncService.installProjectAgentClients(
      projectFileExecutor as unknown as Parameters<typeof chatSyncService.installProjectAgentClients>[0],
      remoteCommandClient as unknown as Parameters<typeof chatSyncService.installProjectAgentClients>[1],
    );
    expect(projectFileExecutor.stop).not.toHaveBeenCalled();
    expect(remoteCommandClient.stop).not.toHaveBeenCalled();
    expect(mocks.webSocketService.forceReconnect).not.toHaveBeenCalled();

    repeatedDispose();
    dispose();
    mocks.webSocketService.isConnected.mockReturnValue(false);
  });
});

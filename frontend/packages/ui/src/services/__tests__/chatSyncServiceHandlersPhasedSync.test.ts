// frontend/packages/ui/src/services/__tests__/chatSyncServiceHandlersPhasedSync.test.ts
// Regression tests for phased sync status handling.
// These guard the cold-boot path where production users have server chats,
// but local IndexedDB is empty and the cache primed flag has expired.
// The frontend must retry after backend rewarming instead of staying empty.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import type { ChatSynchronizationService } from "../chatSyncService";

const mocks = vi.hoisted(() => ({
  chatDB: {
    getChat: vi.fn(),
    addChat: vi.fn(),
    batchSaveMetadataChats: vi.fn(),
    getMessageCountForChat: vi.fn(),
    getMetadataOnlyChatIds: vi.fn(),
  },
  userDB: {
    getUserProfile: vi.fn(),
  },
  chatListCache: {
    upsertChat: vi.fn(),
  },
  unreadMessagesStore: {
    setUnread: vi.fn(),
  },
  chatKeyManager: {
    removeKey: vi.fn(),
    withKey: vi.fn(),
    injectKey: vi.fn(),
  },
  teamService: {
    unwrapTeamChatKey: vi.fn(),
  },
  pendingChatDeletions: {
    getPendingChatDeletionsSet: vi.fn(),
  },
  notificationStore: {
    addNotificationWithOptions: vi.fn(() => "sync-recovery-notification"),
    removeNotificationsByDedupeKey: vi.fn(),
  },
  updateTotalChatCount: vi.fn(),
}));

vi.mock("../db", () => ({ chatDB: mocks.chatDB }));
vi.mock("../userDB", () => ({ userDB: mocks.userDB }));
vi.mock("../chatListCache", () => ({ chatListCache: mocks.chatListCache }));
vi.mock("../../stores/userProfile", () => ({
  updateTotalChatCount: mocks.updateTotalChatCount,
  userProfile: {
    subscribe: (run: (value: { user_id: string }) => void) => {
      run({ user_id: "user-1" });
      return () => undefined;
    },
  },
}));
vi.mock("../../stores/unreadMessagesStore", () => ({
  unreadMessagesStore: mocks.unreadMessagesStore,
}));
vi.mock("../encryption/ChatKeyManager", () => ({
  chatKeyManager: mocks.chatKeyManager,
}));
vi.mock("../pendingChatDeletions", () => mocks.pendingChatDeletions);
vi.mock("../teamService", () => mocks.teamService);
vi.mock("../../stores/notificationStore", () => ({
  notificationStore: mocks.notificationStore,
}));

import {
  ChatSynchronizationService as ChatSynchronizationServiceClass,
} from "../chatSyncService";
import {
  handleLoadMoreChatsResponseImpl,
  handlePhase2RecentChatsImpl,
  handleSyncMetadataChatsResponseImpl,
  handleSyncStatusResponseImpl,
} from "../chatSyncServiceHandlersPhasedSync";
import { phasedSyncState } from "../../stores/phasedSyncStateStore";
import { activeTeamContext } from "../../stores/teamStore";

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
  CACHE_STATUS_MAX_RETRIES: number;
  CACHE_STATUS_RETRY_INTERVAL_MS: number;
  cachePrimed: boolean;
  cachePrimed_FOR_HANDLERS_ONLY: boolean;
  cacheStatusRetryCount: number;
  cacheStatusServerChatCount: number;
  cacheStatusRetryTimer: ReturnType<typeof setTimeout> | null;
  syncRecoveryNotificationId: string | null;
  syncRecoveryNotificationShown: boolean;
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

beforeEach(() => {
  vi.clearAllMocks();
  activeTeamContext.set({ team: null, teamId: null, epoch: 0 });
  mocks.userDB.getUserProfile.mockResolvedValue({ user_id: "user-1" });
  mocks.pendingChatDeletions.getPendingChatDeletionsSet.mockReturnValue(new Set());
  mocks.chatDB.getChat.mockResolvedValue(null);
  mocks.chatDB.batchSaveMetadataChats.mockResolvedValue(0);
});

describe("handleSyncStatusResponseImpl", () => {
  // contract-test: direct surface=gui.web assertions=sync.startup.bounded-phases,chat-navigation.draft-only.addressable
  it("retries cache status when sync status reports an unprimed cache", async () => {
    const service = createService();
    phasedSyncState.markSyncCompleted();

    await handleSyncStatusResponseImpl(service as unknown as ChatSynchronizationService, {
      is_primed: false,
      chat_count: 1,
      timestamp: 1778683517,
    });

    expect(service.cachePrimed_FOR_HANDLERS_ONLY).toBe(false);
    expect(service.cacheStatusServerChatCount_FOR_HANDLERS_ONLY).toBe(1);
    expect(get(phasedSyncState).initialSyncCompleted).toBe(false);
    expect(service.scheduleCacheStatusRetry_FOR_HANDLERS_ONLY).toHaveBeenCalledTimes(1);
    expect(service.attemptInitialSync_FOR_HANDLERS_ONLY).not.toHaveBeenCalled();

    phasedSyncState.reset();
  });

  // contract-test: direct surface=gui.web assertions=sync.startup.bounded-phases
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

describe("handlePhase2RecentChatsImpl", () => {
	// contract-test: direct surface=gui.web assertions=teams.context.full-switch-local,teams.collaboration.realtime-team-sync
	it("does not inject a Team key after the active context epoch changes", async () => {
		let resolveKey: ((key: Uint8Array) => void) | undefined;
		mocks.teamService.unwrapTeamChatKey.mockImplementation(
			() => new Promise<Uint8Array>((resolve) => { resolveKey = resolve; }),
		);
		activeTeamContext.set({ team: null, teamId: "team-a", epoch: 2 });
		const service = createService();
		const pending = handlePhase2RecentChatsImpl(
			service as unknown as ChatSynchronizationService,
			{
				team_id: "team-a",
				context_epoch: 2,
				chats: [{
					chat_details: {
						id: "team-chat",
						encrypted_chat_key: "team-wrapper",
						messages_v: 1,
						title_v: 0,
					},
				}],
				chat_count: 1,
				phase: "phase2",
			},
		);

		await vi.waitFor(() => expect(resolveKey).toBeTypeOf("function"));
		activeTeamContext.set({ team: null, teamId: "team-b", epoch: 3 });
		resolveKey?.(new Uint8Array([1, 2, 3, 4]));
		await pending;

		expect(mocks.chatKeyManager.injectKey).not.toHaveBeenCalled();
		expect(mocks.chatDB.addChat).not.toHaveBeenCalled();
	});

  // contract-test: direct surface=gui.web assertions=sync.phase2.metadata-only,sync.surface.semantic-parity
  it("continues after one chat fails to persist", async () => {
    const service = createService();
    mocks.chatDB.addChat
      .mockRejectedValueOnce(new Error("IndexedDB transaction timed out"))
      .mockResolvedValueOnce(undefined);

    await handlePhase2RecentChatsImpl(
      service as unknown as ChatSynchronizationService,
      {
        chats: [
          {
            chat_details: {
              id: "failed-phase2-chat",
              encrypted_title: "failed-title",
              encrypted_chat_key: "failed-key",
              messages_v: 1,
              title_v: 1,
            },
            server_message_count: 1,
          },
          {
            chat_details: {
              id: "saved-phase2-chat",
              encrypted_title: "saved-title",
              encrypted_chat_key: "saved-key",
              messages_v: 1,
              title_v: 1,
            },
            server_message_count: 1,
          },
        ],
        chat_count: 2,
        total_chat_count: 2,
        phase: "phase2",
      },
    );

    expect(mocks.chatDB.addChat).toHaveBeenCalledTimes(2);
    expect(mocks.chatListCache.upsertChat).toHaveBeenCalledWith(
      expect.objectContaining({ chat_id: "saved-phase2-chat" }),
    );
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: "phase_2_last_20_chats_ready" }),
    );
  });

  // contract-test: direct surface=gui.web assertions=sync.phase2.metadata-only,chats.persistence.client-encrypted
  it("skips new synced metadata rows without encrypted_chat_key", async () => {
    const service = createService();

    await handlePhase2RecentChatsImpl(
      service as unknown as ChatSynchronizationService,
      {
        chats: [
          {
            chat_details: {
              id: "keyless-phase2",
              encrypted_title: "title",
              messages_v: 1,
              title_v: 1,
            },
            server_message_count: 1,
          },
        ],
        chat_count: 1,
        total_chat_count: 1,
        phase: "phase2",
      },
    );

    expect(mocks.chatDB.addChat).not.toHaveBeenCalled();
    expect(mocks.chatListCache.upsertChat).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=sync.phase2.metadata-only,chats.persistence.client-encrypted
  it("keeps synced metadata when a local encrypted_chat_key already exists", async () => {
    const service = createService();
    mocks.chatDB.getChat.mockResolvedValue({
      chat_id: "local-keyed-phase2",
      encrypted_chat_key: "local-key",
      messages_v: 0,
      title_v: 0,
      created_at: 100,
      updated_at: 100,
      last_edited_overall_timestamp: 100,
    });

    await handlePhase2RecentChatsImpl(
      service as unknown as ChatSynchronizationService,
      {
        chats: [
          {
            chat_details: {
              id: "local-keyed-phase2",
              encrypted_title: "server-title",
              messages_v: 1,
              title_v: 1,
            },
            server_message_count: 1,
          },
        ],
        chat_count: 1,
        total_chat_count: 1,
        phase: "phase2",
      },
    );

    expect(mocks.chatDB.addChat).toHaveBeenCalledWith(
      expect.objectContaining({
        chat_id: "local-keyed-phase2",
        encrypted_chat_key: "local-key",
      }),
      undefined,
      { isFromSync: true, forceIncomingEncryptedChatKey: false },
    );
  });
});

describe("handleSyncMetadataChatsResponseImpl", () => {
  // contract-test: direct surface=gui.web assertions=sync.phase2.metadata-only,chats.persistence.client-encrypted
  it("does not batch-save metadata-only chats without encrypted_chat_key", async () => {
    const service = createService();

    await handleSyncMetadataChatsResponseImpl(
      service as unknown as ChatSynchronizationService,
      {
        chats: [
          {
            chat_details: {
              id: "keyless-metadata-only",
              encrypted_title: "title",
              messages_v: 1,
              title_v: 1,
            },
          },
        ],
        total_count: 1,
      },
    );

    expect(mocks.chatDB.batchSaveMetadataChats).not.toHaveBeenCalled();
    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({ type: "metadata_chats_ready" }),
    );
  });

  // contract-test: direct surface=gui.web assertions=sync.phase2.metadata-only
  it("allows public metadata-only chats without encrypted_chat_key", async () => {
    const service = createService();
    mocks.chatDB.batchSaveMetadataChats.mockResolvedValue(1);

    await handleSyncMetadataChatsResponseImpl(
      service as unknown as ChatSynchronizationService,
      {
        chats: [
          {
            chat_details: {
              id: "demo-example",
              encrypted_title: null,
              messages_v: 1,
              title_v: 0,
            },
          },
        ],
        total_count: 1,
      },
    );

    expect(mocks.chatDB.batchSaveMetadataChats).toHaveBeenCalledWith([
      expect.objectContaining({ chat_id: "demo-example" }),
    ]);
  });

  // contract-test: direct surface=gui.web assertions=sync.phase2.metadata-only,chats.persistence.client-encrypted
  it("preserves metadata-only chats without a server key when a local key exists", async () => {
    const service = createService();
    mocks.chatDB.getChat.mockResolvedValueOnce({
      chat_id: "local-keyed-metadata-only",
      encrypted_chat_key: "local-key",
    });
    mocks.chatDB.batchSaveMetadataChats.mockResolvedValue(1);

    await handleSyncMetadataChatsResponseImpl(
      service as unknown as ChatSynchronizationService,
      {
        chats: [
          {
            chat_details: {
              id: "local-keyed-metadata-only",
              encrypted_title: "server-title",
              messages_v: 1,
              title_v: 1,
            },
          },
        ],
        total_count: 1,
      },
    );

    expect(mocks.chatDB.batchSaveMetadataChats).toHaveBeenCalledWith([
      expect.objectContaining({
        chat_id: "local-keyed-metadata-only",
        encrypted_chat_key: "local-key",
      }),
    ]);
  });

  // contract-test: direct surface=gui.web assertions=sync.phase2.metadata-only,chats.persistence.client-encrypted
  it("preserves anonymous metadata-only chat key fields", async () => {
    const service = createService();
    mocks.chatDB.batchSaveMetadataChats.mockResolvedValue(1);

    await handleSyncMetadataChatsResponseImpl(
      service as unknown as ChatSynchronizationService,
      {
        chats: [
          {
            chat_details: {
              id: "anon-metadata-only",
              encrypted_title: "anonymous-title",
              anonymous_encrypted_chat_key: "anonymous-key",
              is_anonymous: true,
              messages_v: 1,
              title_v: 1,
            },
          },
        ],
        total_count: 1,
      },
    );

    expect(mocks.chatDB.batchSaveMetadataChats).toHaveBeenCalledWith([
      expect.objectContaining({
        chat_id: "anon-metadata-only",
        anonymous_encrypted_chat_key: "anonymous-key",
        is_anonymous: true,
      }),
    ]);
  });
});

describe("handleLoadMoreChatsResponseImpl", () => {
  // contract-test: direct surface=gui.web assertions=sync.phase2.metadata-only,chats.persistence.client-encrypted
  it("keeps load-more metadata without a server key when a local key exists", async () => {
    const service = createService();
    mocks.chatDB.getChat.mockResolvedValueOnce({
      chat_id: "local-keyed-load-more",
      encrypted_chat_key: "local-key",
    });

    await handleLoadMoreChatsResponseImpl(
      service as unknown as ChatSynchronizationService,
      {
        chats: [
          {
            chat_details: {
              id: "local-keyed-load-more",
              encrypted_title: "server-title",
              messages_v: 1,
              title_v: 1,
            },
          },
        ],
        has_more: false,
        total_count: 1,
        offset: 100,
      },
    );

    expect(service.dispatchEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "load_more_chats_ready",
        detail: expect.objectContaining({
          chats: [
            expect.objectContaining({
              chat_id: "local-keyed-load-more",
              encrypted_chat_key: "local-key",
            }),
          ],
        }),
      }),
    );
  });
});

describe("ChatSynchronizationService cache status retry", () => {
  // contract-test: direct surface=gui.web assertions=sync.startup.bounded-phases
  it("does not mark sync complete when cache is cold but server reports chats", () => {
    vi.useFakeTimers();
    const service = Object.create(
      ChatSynchronizationServiceClass.prototype,
    ) as RetryServiceHarness;

    service.cachePrimed = false;
    service.CACHE_STATUS_MAX_RETRIES = 10;
    service.CACHE_STATUS_RETRY_INTERVAL_MS = 3000;
    service.cacheStatusRetryCount = 10;
    service.cacheStatusServerChatCount = 1;
    service.cacheStatusRetryTimer = null;
    service.syncRecoveryNotificationId = null;
    service.syncRecoveryNotificationShown = false;
    service.webSocketConnected = true;
    service.dispatchSyncTimeoutComplete = vi.fn();
    service.requestCacheStatus = vi.fn();

    service.scheduleCacheStatusRetry_FOR_HANDLERS_ONLY();

    expect(service.dispatchSyncTimeoutComplete).not.toHaveBeenCalled();
    expect(
      mocks.notificationStore.addNotificationWithOptions,
    ).toHaveBeenCalledWith(
      "warning",
      expect.objectContaining({
        dedupeKey: "chat-sync-recovery",
        duration: 0,
        isProcessing: true,
      }),
    );
    expect(service.cacheStatusRetryCount).toBe(1);

    vi.runOnlyPendingTimers();
    expect(service.requestCacheStatus).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  // contract-test: direct surface=gui.web assertions=sync.startup.bounded-phases
  it("does not repeat the cache recovery notification during the same recovery cycle", () => {
    vi.useFakeTimers();
    const service = Object.create(
      ChatSynchronizationServiceClass.prototype,
    ) as RetryServiceHarness;

    service.cachePrimed = false;
    service.CACHE_STATUS_MAX_RETRIES = 10;
    service.CACHE_STATUS_RETRY_INTERVAL_MS = 3000;
    service.cacheStatusRetryCount = 10;
    service.cacheStatusServerChatCount = 1;
    service.cacheStatusRetryTimer = null;
    service.syncRecoveryNotificationId = null;
    service.syncRecoveryNotificationShown = false;
    service.webSocketConnected = true;
    service.dispatchSyncTimeoutComplete = vi.fn();
    service.requestCacheStatus = vi.fn();

    service.scheduleCacheStatusRetry_FOR_HANDLERS_ONLY();
    service.cacheStatusRetryCount = 10;
    service.cacheStatusRetryTimer = null;
    service.scheduleCacheStatusRetry_FOR_HANDLERS_ONLY();

    expect(
      mocks.notificationStore.addNotificationWithOptions,
    ).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
  });

  // contract-test: direct surface=gui.web assertions=sync.startup.bounded-phases
  it("clears the cache recovery notification once the cache is primed", () => {
    const service = Object.create(
      ChatSynchronizationServiceClass.prototype,
    ) as RetryServiceHarness;

    service.cachePrimed = false;
    service.CACHE_STATUS_MAX_RETRIES = 10;
    service.CACHE_STATUS_RETRY_INTERVAL_MS = 3000;
    service.cacheStatusRetryCount = 10;
    service.cacheStatusServerChatCount = 1;
    service.cacheStatusRetryTimer = null;
    service.syncRecoveryNotificationId = null;
    service.syncRecoveryNotificationShown = false;
    service.webSocketConnected = true;
    service.dispatchSyncTimeoutComplete = vi.fn();
    service.requestCacheStatus = vi.fn();

    service.scheduleCacheStatusRetry_FOR_HANDLERS_ONLY();
    service.cachePrimed_FOR_HANDLERS_ONLY = true;

    expect(
      mocks.notificationStore.removeNotificationsByDedupeKey,
    ).toHaveBeenCalledWith("chat-sync-recovery");
  });
});

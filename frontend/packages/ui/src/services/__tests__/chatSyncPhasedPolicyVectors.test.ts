// TS side of the phased-sync parity vectors (packages/openmates-rust/src/web_sync/ts_vectors.json):
// synced-chat key admission, metadata-only chat records and the authoritative
// deletion plan of chatSyncServiceHandlersPhasedSync.ts (flag off). The Rust
// policy replays the same file in web_sync/tests.rs.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Chat } from "../../types/chat";

import type { ChatSynchronizationService } from "../chatSyncService";

// Some senders import the package barrel for translations. Loading that barrel
// here pulls UI components back into chatSyncService before it is initialized.
vi.mock("@repo/ui", () => ({
  text: {
    subscribe: (run: (value: (key: string) => string) => void) => {
      run((key) => key);
      return () => undefined;
    },
  },
}));

const mocks = vi.hoisted(() => ({
  chatDB: {
    getChat: vi.fn(),
    addChat: vi.fn(),
    batchSaveMetadataChats: vi.fn(),
    getMessageCountForChat: vi.fn(),
    getMetadataOnlyChatIds: vi.fn(),
    deleteChatIfNoPendingTurn: vi.fn(),
    deleteChat: vi.fn(),
  },
  userDB: {
    getUserProfile: vi.fn(),
  },
  chatListCache: {
    upsertChat: vi.fn(),
    removeChat: vi.fn(),
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

// config/links reads SvelteKit's `$env/dynamic/public`, which vitest cannot resolve
// (reached through voiceCallPrivacy); same stub as voiceCallPrivacy.test.ts.
vi.mock("../../config/links", () => ({ externalLinks: { legal: { privacyPolicy: "/legal/privacy" } } }));
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
  applyAuthoritativeDeletedChats,
  buildMetadataOnlyChatFromDetails,
  shouldSkipSyncedChatWithoutKey,
} from "../chatSyncServiceHandlersPhasedSync";

const VECTORS = resolve(__dirname, "../../../../../../packages/openmates-rust/src/web_sync/ts_vectors.json");
const vectors = JSON.parse(readFileSync(VECTORS, "utf8"));
const json = (value: unknown) => JSON.parse(JSON.stringify(value));

describe("phased sync parity vectors (TypeScript side)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(vectors.now * 1000);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("key admission and metadata-only chats match the committed vectors", () => {
    for (const c of vectors.admission) {
      expect(shouldSkipSyncedChatWithoutKey("Vectors", c.chatId, c.server, c.local), JSON.stringify(c)).toBe(c.skip);
    }
    for (const c of vectors.metadataChat) {
      expect(json(buildMetadataOnlyChatFromDetails(c.server, c.local as Chat | null))).toEqual(c.out);
    }
    vi.useRealTimers();
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted
  it("authoritative deletions match the committed plan", async () => {
    vi.useRealTimers();
    const service = { dispatchEvent: vi.fn() } as unknown as ChatSynchronizationService;
    for (const c of vectors.deletion) {
      const calls: { chatId: string; explicit: boolean }[] = [];
      mocks.chatDB.deleteChatIfNoPendingTurn.mockImplementation(async (chatId: string) => {
        calls.push({ chatId, explicit: false });
        return { deleted: true };
      });
      mocks.chatDB.deleteChat.mockImplementation(async (chatId: string) => { calls.push({ chatId, explicit: true }); });
      await applyAuthoritativeDeletedChats(service, c.hasDeleted ? c.deleted : undefined, c.hasExplicit ? c.explicit : undefined);
      expect(calls, JSON.stringify(c)).toEqual(c.out);
    }
  });
});

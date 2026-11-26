import { afterEach, expect, it, vi } from "vitest";
import { invalidateWorkspaceCaches } from "../workspaceCacheLifecycle";

vi.mock("$app/environment", () => ({ browser: false }));
vi.mock("../db/newChatSuggestions", () => ({}));
vi.mock("../db/pendingEmbedQueue", () => ({ putPendingEmbedOperation: vi.fn() }));
vi.mock("../db/appSettingsMemories", () => ({}));
vi.mock("../db/chatKeyManagement", () => ({}));
vi.mock("../db/messageOperations", () => ({}));
vi.mock("../db/chatCrudOperations", () => ({}));
vi.mock("../db/offlineChangesAndUpdates", () => ({}));
vi.mock("../db/quotaRecovery", () => ({ writeWithQuotaRetry: vi.fn() }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: {} }));
vi.mock("../../stores/notificationStore", () => ({ notificationStore: {} }));
vi.mock("../cryptoService", () => ({ getKeyFromStorage: async () => null }));
vi.mock("../../stores/signupState", () => ({
  forcedLogoutInProgress: {}, isLoggingOut: {},
  setForcedLogoutInProgress: vi.fn(), lastResumeTimestamp: 0, RESUME_ORPHAN_GRACE_MS: 3000,
}));
vi.mock("../../stores/teamStore", () => ({
  getActiveTeamContextSnapshot: () => ({ teamId: "team-a" }),
}));

import { chatDB } from "../db";
import type { Chat } from "../../types/chat";
import type { PersistedChatKey } from "../encryption/ChatKeyManager";

const keyReader = chatDB as unknown as {
  readPersistedChatKey(chatId: string): Promise<PersistedChatKey | null>;
};

function row(id: string, fields: Partial<Chat> = {}): Chat {
  return { chat_id: id, team_id: "team-a", ...fields } as Chat;
}

afterEach(() => vi.restoreAllMocks());

// contract-test: supporting surface=gui.web assertions=sync.startup.recent-metadata-cap
it("uses an older child's own wrapper even with no retained parent", async () => {
  const read = vi.spyOn(chatDB, "getRawChat").mockResolvedValueOnce(
    row("child", { parent_id: "parent", encrypted_chat_key: "child-wrapper", chat_visibility: "direct" }),
  );
  expect(await keyReader.readPersistedChatKey("child")).toEqual({
    encryptedKey: "child-wrapper", keyChatId: "child", teamId: "team-a", visibility: "direct",
  });
  expect(read.mock.calls).toEqual([["child"]]);
});

// contract-test: supporting surface=gui.web assertions=sync.startup.recent-metadata-cap,auth.secrets.lifecycle
it("inherits a missing wrapper only from a parent in the same current Team", async () => {
  const child = row("child", { parent_id: "parent" });
  const parent = row("parent", { encrypted_chat_key: "parent-wrapper" });
  const read = vi.spyOn(chatDB, "getRawChat")
    .mockResolvedValueOnce(child)
    .mockResolvedValueOnce(parent)
    .mockResolvedValueOnce(child)
    .mockResolvedValueOnce({ ...parent, team_id: "team-b" });
  expect(await keyReader.readPersistedChatKey("child")).toMatchObject({
    encryptedKey: "parent-wrapper", keyChatId: "parent", teamId: "team-a",
  });
  expect(await keyReader.readPersistedChatKey("child")).toBeNull();

  read.mockResolvedValueOnce(child).mockImplementationOnce(async () => {
    invalidateWorkspaceCaches();
    return parent;
  });
  expect(await keyReader.readPersistedChatKey("child")).toBeNull();
});

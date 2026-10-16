import { beforeEach, describe, expect, it, vi } from "vitest";
import { get } from "svelte/store";
import type { Chat } from "../../types/chat";

const mocks = vi.hoisted(() => ({
  cached: null as Chat[] | null,
  epoch: 0,
  teamId: null as string | null,
  getAllChats: vi.fn<() => Promise<Chat[]>>(),
}));

vi.mock("../teamStore", () => ({
  TEAM_CONTEXT_CHANGED_EVENT: "test:team-context-changed",
  getActiveTeamContextSnapshot: () => ({ teamId: mocks.teamId, epoch: mocks.epoch }),
  isActiveTeamContext: (teamId: string | null, epoch?: number) =>
    teamId === mocks.teamId && (epoch === undefined || epoch === mocks.epoch),
}));
vi.mock("../../services/db", () => ({ chatDB: { getAllChats: mocks.getAllChats } }));
vi.mock("../../services/chatListCache", () => ({ chatListCache: { getCache: () => mocks.cached } }));
vi.mock("../activeChatStore", () => ({ activeChatStore: { setActiveChat: vi.fn() } }));
vi.mock("../../services/chatSyncService", () => ({ chatSyncService: { sendSetActiveChat: vi.fn() } }));
vi.mock("../../demo_chats", () => ({
  INTRO_CHATS: [], LEGAL_CHATS: [], getAllExampleChats: () => [],
  translateDemoChat: (chat: unknown) => chat,
}));
vi.mock("../../demo_chats/convertToChat", () => ({ convertDemoChatToChat: (chat: unknown) => chat }));

import {
  chatNavigationStore, navigateNext, resetChatNavigationList, updateNavFromCache,
} from "../chatNavigationStore";

function chat(chat_id: string, team_id: string | null, timestamp: number): Chat {
  return {
    chat_id, team_id, title: chat_id, encrypted_title: null, messages_v: 1,
    title_v: 1, last_edited_overall_timestamp: timestamp, unread_count: 0,
    created_at: timestamp, updated_at: timestamp,
  } as Chat;
}

describe("chat navigation context boundary", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    resetChatNavigationList();
    mocks.teamId = null;
    mocks.cached = null;
    mocks.epoch++;
    mocks.getAllChats.mockReset();
    const dispatch = window.dispatchEvent.bind(window);
    vi.spyOn(window, "dispatchEvent").mockImplementation((event) => dispatch(event));
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
  it("only navigates chats in the active team when the sidebar is closed", async () => {
    mocks.teamId = "team-a";
    mocks.epoch++;
    mocks.getAllChats.mockResolvedValue([
      chat("personal", null, 400), chat("team-a-new", "team-a", 300),
      chat("team-b", "team-b", 250), chat("team-a-old", "team-a", 200),
    ]);
    updateNavFromCache("team-a-new");
    await vi.waitFor(() => {
      expect(get(chatNavigationStore)).toEqual({ hasPrev: false, hasNext: true });
    });
    await navigateNext();
    const event = vi.mocked(window.dispatchEvent).mock.calls.find(
      ([value]) => value.type === "chatHeaderNavigation",
    )?.[0] as CustomEvent<{ chat: Chat }> | undefined;
    expect(event?.detail.chat.chat_id).toBe("team-a-old");
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local,teams.cache.bounded-isolated
  it("discards an old context's async database result", async () => {
    let resolveOld!: (chats: Chat[]) => void;
    mocks.teamId = "team-a";
    mocks.epoch++;
    mocks.getAllChats.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }));
    updateNavFromCache("team-a-new");
    await vi.waitFor(() => expect(resolveOld).toBeTypeOf("function"));
    mocks.teamId = null;
    mocks.epoch++;
    window.dispatchEvent(new Event("test:team-context-changed"));
    resolveOld([chat("team-a-new", "team-a", 300), chat("team-a-old", "team-a", 200)]);
    await Promise.resolve();
    await Promise.resolve();
    expect(get(chatNavigationStore)).toEqual({ hasPrev: false, hasNext: false });
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
  it("falls back to IndexedDB when the memory cache only contains another workspace", async () => {
    mocks.teamId = "team-a";
    mocks.epoch++;
    mocks.cached = [chat("personal", null, 400)];
    mocks.getAllChats.mockResolvedValue([
      chat("team-a-new", "team-a", 300), chat("team-a-old", "team-a", 200),
    ]);
    updateNavFromCache("team-a-new");
    await vi.waitFor(() => {
      expect(get(chatNavigationStore)).toEqual({ hasPrev: false, hasNext: true });
    });
    expect(mocks.getAllChats).toHaveBeenCalledOnce();
  });
});

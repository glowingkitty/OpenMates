import { afterEach, describe, expect, it, vi } from "vitest";
import type { Chat } from "../../types/chat";
vi.mock("../../config/api", () => ({ getApiEndpoint: (path: string) => `https://api.example.invalid${path}` }));
import { refreshRecoveryChatVersion } from "../chatRecoveryVersionRefresh";

const chat = { chat_id: "chat-a", messages_v: 5, team_id: "team-a" } as Chat;
afterEach(() => vi.unstubAllGlobals());
describe("completion version refresh", () => {
  // contract-test: direct surface=gui.web assertions=chats.completion.lease-fenced,chats.message.identity-idempotent
  it("uses the persisted owner-scoped version even when the local optimistic version is ahead", async () => {
    const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ chat_id: "chat-a", messages_v: 3 }) }));
    vi.stubGlobal("fetch", fetcher);
    expect(await refreshRecoveryChatVersion(chat)).toEqual({ ...chat, messages_v: 3 });
    expect(fetcher).toHaveBeenCalledWith(expect.stringContaining("team_id=team-a"), expect.objectContaining({ credentials: "include", cache: "no-store" }));
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it.each([{ chat_id: "other-chat", messages_v: 3 }, { chat_id: "chat-a", messages_v: -1 }, { chat_id: "chat-a", messages_v: "3" }])("rejects mismatched or invalid persisted metadata: %j", async (data) => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => data })));
    expect(await refreshRecoveryChatVersion(chat)).toBeNull();
  });
});

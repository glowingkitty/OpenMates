import { afterEach, describe, expect, it, vi } from "vitest";
import type { Chat } from "../../types/chat";
vi.mock("../../config/api", () => ({ getApiEndpoint: (path: string) => `https://api.example.invalid${path}` }));
import { refreshRecoveryChatVersion, refreshPersistedAssistantVersion } from "../chatRecoveryVersionRefresh";

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

describe("canonical legacy assistant version", () => {
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("requests only the exact assistant anchor with authenticated bounded reads", async () => {
    const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ chat_id: chat.chat_id, messages_v: 3, messages: [{ message_id: "assistant-a", chat_id: chat.chat_id, role: "assistant", user_message_id: "user-a", encrypted_content: "ciphertext" }] }) }));
    vi.stubGlobal("fetch", fetcher);
    expect(await refreshPersistedAssistantVersion(chat, "assistant-a", "user-a")).toBe(3);
    const [url, options] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    const query = new URL(url).searchParams;
    expect(Object.fromEntries(query)).toEqual({ direction: "around", anchor_message_id: "assistant-a", limit: "1", respect_compression_boundary: "false", team_id: "team-a" });
    expect(options).toMatchObject({ credentials: "include", cache: "no-store", signal: expect.any(AbortSignal) });
  });
});

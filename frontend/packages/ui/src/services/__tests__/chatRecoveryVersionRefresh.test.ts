import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Chat } from "../../types/chat";
vi.mock("../../config/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../../config/api")>(),
  getApiEndpoint: (path: string) => `https://api.example.invalid${path}`,
}));
import { refreshRecoveryChatVersion, refreshPersistedAssistantVersion } from "../chatRecoveryVersionRefresh";

const chat = { chat_id: "chat-a", messages_v: 5, team_id: "team-a" } as Chat;
beforeEach(() => vi.stubEnv("VITE_API_URL", "https://api.example.invalid"));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
describe("completion version refresh", () => {
  // contract-test: direct surface=gui.web assertions=chats.completion.lease-fenced,chats.message.identity-idempotent
  it("uses the persisted owner-scoped version with archive capability even when the local version is ahead", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ chat_id: "chat-a", messages_v: 3 })));
    vi.stubGlobal("fetch", fetcher);
    expect(await refreshRecoveryChatVersion(chat)).toEqual({ ...chat, messages_v: 3 });
    const [url, init] = fetcher.mock.calls[0];
    expect(url).toBe("https://api.example.invalid/v1/chats/chat-a/messages/window?limit=1&respect_compression_boundary=false&team_id=team-a");
    expect(init).toEqual(expect.objectContaining({ credentials: "include", cache: "no-store", signal: expect.any(AbortSignal) }));
    expect(new Headers(init.headers).get("X-OpenMates-Client-Capabilities")).toBe("agentic-storage-v2");
    expect(chat.messages_v).toBe(5);
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it.each([
    { chat_id: "other-chat", messages_v: 3 }, { chat_id: "chat-a", messages_v: -1 },
    { chat_id: "chat-a", messages_v: "3" }, { chat_id: "chat-a", messages_v: 1.5 },
    { chat_id: "chat-a", messages_v: Number.MAX_SAFE_INTEGER + 1 },
    { chat_id: "chat-a", messages_v: null },
  ])("rejects mismatched or invalid persisted metadata: %j", async (data) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(data))));
    expect(await refreshRecoveryChatVersion(chat)).toBeNull();
    expect(chat.messages_v).toBe(5);
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it("returns no replacement version on an HTTP rejection so the caller keeps the original conflict", async () => {
    const json = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 403, json }));
    expect(await refreshRecoveryChatVersion(chat)).toBeNull();
    expect(json).not.toHaveBeenCalled();
    expect(chat.messages_v).toBe(5);
  });
  // contract-test: supporting surface=gui.web assertions=chats.completion.lease-fenced
  it.each(["network", "invalid-json"])("returns no replacement version after %s failure", async (failure) => {
    vi.stubGlobal("fetch", failure === "network"
      ? vi.fn().mockRejectedValue(new Error("fixture transport failure"))
      : vi.fn().mockResolvedValue({ ok: true, json: async () => { throw new SyntaxError("fixture invalid JSON"); } }));
    expect(await refreshRecoveryChatVersion(chat)).toBeNull();
    expect(chat.messages_v).toBe(5);
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

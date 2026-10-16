import { webcrypto } from "node:crypto";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const archiveFetch = vi.fn();
vi.mock("../../config/api", () => ({
  getApiEndpoint: (path: string) => `https://api.example.invalid${path}`,
  storageArchiveFetch: (...args: unknown[]) => archiveFetch(...args),
}));
import { encryptWithChatKey } from "../encryption/MessageEncryptor";
import { assertNoOmittedTeamTurns, loadLocalSavedHistoryForSend, loadTeamAIHistory } from "../teamAIHistory";

const key = new Uint8Array(32).fill(7);
const options = { chatId: "chat-a", teamId: "team-a", currentMessageId: "current", chatKey: key };
const reply = (body: unknown) => ({ ok: true, json: async () => body });

async function row(id: string, createdAt: number, content: string, sender: string) {
  return { message_id: id, chat_id: "chat-a", role: "user", created_at: createdAt,
    encrypted_content: await encryptWithChatKey(content, key),
    encrypted_sender_name: await encryptWithChatKey(sender, key) };
}

describe("invocation-only Team history hydration", () => {
  beforeEach(() => {
    vi.stubGlobal("crypto", webcrypto);
    vi.stubGlobal("window", { btoa, atob });
    archiveFetch.mockReset();
  });
  afterEach(() => vi.unstubAllGlobals());

  // contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked
  it("does not read or decrypt local history for an ordinary Team send", async () => {
    const readMessages = vi.fn(async () => []);
    expect(await loadLocalSavedHistoryForSend("chat-a", "team-a", readMessages)).toEqual([]);
    expect(readMessages).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked,teams.chat.sender-identity-layout
  it("reads older server pages missing from cold local cache and decrypts both speakers in order", async () => {
    const alice = await row("alice", 100, "Design the API", "Alice");
    const bob = await row("bob", 200, "I can review it", "Bob");
    archiveFetch
      .mockResolvedValueOnce(reply({ chat_id: "chat-a", messages: [bob], has_more_before: true,
        start_cursor: { created_at: 200, message_id: "bob" }, server_message_count: 2 }))
      .mockResolvedValueOnce(reply({ chat_id: "chat-a", messages: [alice], has_more_before: false,
        start_cursor: { created_at: 100, message_id: "alice" }, server_message_count: 2 }));
    const history = await loadTeamAIHistory({ ...options, assertScope: () => undefined });
    expect(history.map(({ content, sender_name }) => [content, sender_name])).toEqual([
      ["Design the API", "Alice"], ["I can review it", "Bob"],
    ]);
    expect(archiveFetch).toHaveBeenCalledTimes(2);
    for (const [url, init] of archiveFetch.mock.calls) {
      expect(url).toContain("team_id=team-a");
      expect(url).toContain("respect_compression_boundary=false");
      expect(init).toEqual(expect.objectContaining({ credentials: "include", cache: "no-store" }));
    }
    expect(archiveFetch.mock.calls[1][0]).toContain("before_message_id=bob");
  });

  // contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
  it("fails closed when a page is missing, unauthorized, or missing sender attribution", async () => {
    archiveFetch.mockResolvedValueOnce(reply({ chat_id: "chat-a", messages: [], has_more_before: true,
      start_cursor: null, server_message_count: 1 }));
    await expect(loadTeamAIHistory({ ...options, assertScope: () => undefined }))
      .rejects.toThrow("made no progress");
    archiveFetch.mockResolvedValueOnce({ ok: false, status: 403 });
    await expect(loadTeamAIHistory({ ...options, assertScope: () => undefined }))
      .rejects.toThrow("403");
    archiveFetch.mockResolvedValueOnce(reply({ chat_id: "chat-a", messages: [{
      message_id: "alice", chat_id: "chat-a", role: "user", created_at: 100,
      encrypted_content: await encryptWithChatKey("private", key),
    }], has_more_before: false, start_cursor: null, server_message_count: 1 }));
    await expect(loadTeamAIHistory({ ...options, assertScope: () => undefined }))
      .rejects.toThrow("attribution is missing");
  });

  // contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
  it("rejects truncated counts and a repeated pagination cursor", async () => {
    const bob = await row("bob", 200, "later", "Bob");
    archiveFetch.mockResolvedValueOnce(reply({ chat_id: "chat-a", messages: [bob],
      has_more_before: false, start_cursor: null, server_message_count: 2 }));
    await expect(loadTeamAIHistory({ ...options, assertScope: () => undefined }))
      .rejects.toThrow("incomplete");
    archiveFetch
      .mockResolvedValueOnce(reply({ chat_id: "chat-a", messages: [bob], has_more_before: true,
        start_cursor: { created_at: 200, message_id: "bob" }, server_message_count: 2 }))
      .mockResolvedValueOnce(reply({ chat_id: "chat-a", messages: [bob], has_more_before: true,
        start_cursor: { created_at: 200, message_id: "bob" }, server_message_count: 2 }));
    await expect(loadTeamAIHistory({ ...options, assertScope: () => undefined }))
      .rejects.toThrow("cursor did not advance");
  });

  // contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked
  it("continues past the exact-read cursor when a byte-bounded page has no selected rows", async () => {
    const oversized = await row("large", 200, "Large encrypted text", "Bob");
    const older = await row("older", 100, "Earlier context", "Alice");
    archiveFetch
      .mockResolvedValueOnce(reply({ chat_id: "chat-a", messages: [], has_more_before: true,
        start_cursor: null, oversized_message_cursor: { created_at: 200, message_id: "large" },
        server_message_count: 2 }))
      .mockResolvedValueOnce(reply({ message: oversized }))
      .mockResolvedValueOnce(reply({ chat_id: "chat-a", messages: [older], has_more_before: false,
        start_cursor: { created_at: 100, message_id: "older" }, server_message_count: 2 }));
    const history = await loadTeamAIHistory({ ...options, assertScope: () => undefined });
    expect(history.map((item) => item.message_id)).toEqual(["older", "large"]);
    expect(archiveFetch.mock.calls[1][0]).toContain("team_id=team-a");
    expect(archiveFetch.mock.calls[2][0]).toContain("before_message_id=large");
  });

  // contract-test: direct surface=gui.web assertions=teams.chat.encrypted-until-invoked
  it("accepts initial 404 only with explicit fresh-local-chat provenance", async () => {
    archiveFetch.mockResolvedValueOnce({ ok: false, status: 404 });
    expect(await loadTeamAIHistory({ ...options, allowMissingInitialChat: true,
      assertScope: () => undefined })).toEqual([]);
    archiveFetch.mockResolvedValueOnce({ ok: false, status: 404 });
    await expect(loadTeamAIHistory({ ...options, assertScope: () => undefined }))
      .rejects.toThrow("404");
  });

  // contract-test: supporting surface=gui.web assertions=teams.chat.encrypted-until-invoked
  it("rejects an unsent earlier human turn that the authorized server pages do not contain", () => {
    const pending = { message_id: "prior", status: "waiting_for_internet" } as never;
    expect(() => assertNoOmittedTeamTurns([pending], [], "current"))
      .toThrow("unsent or unconfirmed");
    expect(() => assertNoOmittedTeamTurns([pending], [{ message_id: "prior" } as never], "current"))
      .not.toThrow();
  });

  // contract-test: supporting surface=gui.web assertions=teams.context.full-switch-local
  it("discards a Team page if context changes while the network request is pending", async () => {
    let resolve!: (value: ReturnType<typeof reply>) => void;
    archiveFetch.mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    let active = true;
    const loading = loadTeamAIHistory({ ...options, assertScope: () => {
      if (!active) throw new Error("scope changed");
    } });
    active = false;
    resolve(reply({ chat_id: "chat-a", messages: [], has_more_before: false,
      start_cursor: null, server_message_count: 0 }));
    await expect(loading).rejects.toThrow("scope changed");
  });
});

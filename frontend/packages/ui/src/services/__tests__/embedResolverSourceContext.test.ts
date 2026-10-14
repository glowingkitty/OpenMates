import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import { writable } from "svelte/store";

const state = vi.hoisted(() => ({
  activeChat: "unrelated-active-chat", chats: new Map<string, Record<string, unknown>>(),
  loaded: new Map<string, Record<string, unknown>>(),
  provenance: new Map<string, Record<string, unknown>>(),
  raw: new Map<string, Record<string, unknown>>(), localKeys: new Map<string, Record<string, unknown>[]>(),
  fetch: vi.fn(), send: vi.fn(), keys: vi.fn(), put: vi.fn(), dispatch: vi.fn(),
}));
vi.mock("../../stores/authState", () => ({ authStore: writable({ isAuthenticated: true, isInitialized: true }) }));
vi.mock("../../stores/userProfile", () => ({ userProfile: writable({ user_id: "owner-1", account_id: "account-1" }) }));
vi.mock("../../stores/teamStore", () => ({ activeTeamId: writable(null as string | null) }));
vi.mock("../../stores/activeChatStore", () => ({ activeChatStore: { get: () => state.activeChat } }));
vi.mock("../db", () => ({ chatDB: { getChat: vi.fn(async (id: string) => state.chats.get(id) ?? null) } }));
vi.mock("../embedStore", () => ({ embedStore: {
  get: vi.fn(async (id: string) => state.loaded.get(id) ?? null),
  getRawEntry: vi.fn(async (id: string) => state.raw.get(id) ?? null),
  getEmbedKeyEntries: vi.fn(async (hash: string) => state.localKeys.get(hash) ?? []),
  storeEmbedKeys: state.keys, putEncrypted: state.put,
} }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: { getProvenance: (id: string) => state.provenance.get(id) ?? null } }));
vi.mock("../chatSyncService", () => ({ chatSyncService: { dispatchEvent: state.dispatch } }));
vi.mock("../websocketService", () => ({ webSocketService: { sendMessage: state.send } }));
vi.mock("../../config/api", () => ({ getApiEndpoint: (path: string) => path, storageArchiveFetch: state.fetch }));
vi.mock("../../demo_chats/exampleChatStore", () => ({
  isExampleChat: (id: string) => id.startsWith("example-"),
  getExampleChatEmbed: () => null,
}));

import { authStore } from "../../stores/authState";
import { userProfile } from "../../stores/userProfile";
import { activeTeamId } from "../../stores/teamStore";
import { requestEmbedFromServerOnce, resolveEmbed, isEmbedKnownError, markEmbedAsError, clearEmbedError } from "../embedResolver";

let nextId = 0;
const embedId = () => `source-context-${++nextId}`;
const ready = (id: string) => new Response(JSON.stringify({
  embed: { embed_id: id, status: "finished", encrypted_type: "cipher-type", encrypted_content: "cipher-content" },
  embed_keys: [],
}), { status: 200 });

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(crypto.subtle.digest).mockImplementation(webcrypto.subtle.digest.bind(webcrypto.subtle));
  state.activeChat = "unrelated-active-chat";
  state.chats.clear(); state.loaded.clear(); state.raw.clear(); state.localKeys.clear(); state.provenance.clear();
  state.fetch.mockReset().mockResolvedValue(new Response("{}", { status: 404 }));
  state.send.mockReset().mockResolvedValue(undefined);
  state.keys.mockReset().mockImplementation(async (_keys: unknown, guard: () => void) => guard());
  state.put.mockReset().mockImplementation(async (ref: string, data: Record<string, unknown>, _type: unknown,
    _content: unknown, _metadata: unknown, options: { writeGuard: () => void }) => {
    options.writeGuard(); state.loaded.set(ref, { ...data, type: "app_skill_use", content: "decoded" });
  });
  state.dispatch.mockReset();
  authStore.set({ isAuthenticated: true, isInitialized: true });
  userProfile.set({ user_id: "owner-1", account_id: "account-1" } as never);
  activeTeamId.set(null);
  vi.spyOn(console, "warn").mockImplementation(() => undefined);
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe("embed reads use caller source context", () => {
  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,storage.background.complete-sealed-recovery
  it("loads a valid second source after a first-source404 without inheriting its cooldown", async () => {
    const id = embedId();
    state.fetch.mockImplementation(async (path: string) => path.includes("/source-b/") ? ready(id) : new Response("{}", { status: 404 }));
    await requestEmbedFromServerOnce(id, "source-a", { chatId: "source-a" });
    await requestEmbedFromServerOnce(id, "source-b", { chatId: "source-b" });
    expect(state.fetch.mock.calls.map(([path]) => path)).toEqual([
      `/v1/embeds/chats/source-a/embeds/${id}`, `/v1/embeds/chats/source-b/embeds/${id}`,
    ]);
    expect(state.send).toHaveBeenCalledExactlyOnceWith("request_embed", { embed_id: id, chat_id: "source-a", team_id: null });
    expect(await resolveEmbed(id, { chatId: "source-b" })).toMatchObject({ embed_id: id, status: "finished" });
    expect(state.put).toHaveBeenCalledTimes(1);
  });

  // contract-test: supporting surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("uses the source Team and its parent fallback without borrowing the active chat", async () => {
    const id = embedId();
    state.chats.set("source-child", { team_id: "source-team", parent_id: "source-parent" });
    state.chats.set("source-parent", { team_id: "source-team" });
    activeTeamId.set("unrelated-selected-team");
    state.fetch.mockImplementation(async (path: string) => path.includes("/source-parent/") ? ready(id) : new Response("{}", { status: 404 }));
    await requestEmbedFromServerOnce(id, "parent-fallback", { chatId: "source-child" });
    expect(state.fetch.mock.calls.map(([path]) => path)).toEqual([
      `/v1/embeds/chats/source-child/embeds/${id}?team_id=source-team`,
      `/v1/embeds/chats/source-parent/embeds/${id}?team_id=source-team`,
    ]);
    expect(state.send).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=chats.completion.recovery-takeover,chats.persistence.client-encrypted
  it("bounds repeated404s to the existing cooldown and allows later ready content", async () => {
    const id = embedId();
    await requestEmbedFromServerOnce(id, "first", { chatId: "source" });
    expect(await requestEmbedFromServerOnce(id, "repeat", { chatId: "source" })).toBe(false);
    expect(state.fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(10_001);
    state.fetch.mockResolvedValue(ready(id));
    await requestEmbedFromServerOnce(id, "ready", { chatId: "source" });
    expect(state.fetch).toHaveBeenCalledTimes(2);
    expect(await resolveEmbed(id, { chatId: "source" })).toMatchObject({ status: "finished" });
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it.each(["account", "Team"])("isolates cooldown when the %s changes", async (kind) => {
    const id = embedId();
    await requestEmbedFromServerOnce(id, "old-context", { chatId: "source" });
    if (kind === "account") userProfile.set({ user_id: "owner-2", account_id: "account-2" } as never);
    else { activeTeamId.set("team-2"); state.chats.set("source", { team_id: "team-2" }); }
    state.fetch.mockResolvedValue(ready(id));
    await requestEmbedFromServerOnce(id, "new-context", { chatId: "source" });
    expect(state.fetch).toHaveBeenCalledTimes(2);
    expect(state.put).toHaveBeenCalledTimes(1);
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,storage.background.complete-sealed-recovery
  it("deduplicates concurrent previews in one source context", async () => {
    const id = embedId(); let release!: (response: Response) => void;
    state.fetch.mockImplementation(() => new Promise(resolve => { release = resolve; }));
    const first = requestEmbedFromServerOnce(id, "first-preview", { chatId: "source" });
    const duplicate = requestEmbedFromServerOnce(id, "second-preview", { chatId: "source" });
    await vi.waitFor(() => expect(state.fetch).toHaveBeenCalledTimes(1));
    expect(await duplicate).toBe(false);
    release(ready(id));
    expect(await first).toBe(true);
    expect(state.put).toHaveBeenCalledTimes(1);
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("keeps a live request deduplicated when related readiness arrives simultaneously", async () => {
    const id = embedId(); let release!: (response: Response) => void;
    state.loaded.set(`embed:${id}`, { _decryptionFailed: true });
    state.fetch.mockImplementation(() => new Promise(resolve => { release = resolve; }));
    await resolveEmbed(id, { chatId: "source" });
    await vi.waitFor(() => expect(state.fetch).toHaveBeenCalledTimes(1));
    state.provenance.set("source", { timestamp: 2, keyFingerprint: "new-ready-key" });
    await Promise.all([resolveEmbed(id, { chatId: "source" }), resolveEmbed(id, { chatId: "source" })]);
    expect(await requestEmbedFromServerOnce(id, "third-preview", { chatId: "source" })).toBe(false);
    expect(state.fetch).toHaveBeenCalledTimes(1);
    release(ready(id));
    await vi.waitFor(() => expect(state.put).toHaveBeenCalledTimes(1));
    expect(await resolveEmbed(id, { chatId: "source" })).toMatchObject({ status: "finished" });
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,storage.background.complete-sealed-recovery
  it.each(["completion", "failure"])("does not let an older %s clobber a newer live request after terminal reset", async outcome => {
    const id = embedId(); const releases: Array<(response: Response) => void> = [];
    state.fetch.mockImplementation(() => new Promise(resolve => { releases.push(resolve); }));
    if (outcome === "failure") state.send.mockRejectedValueOnce(new Error("not connected"));
    const older = requestEmbedFromServerOnce(id, "older-preview", { chatId: "source" });
    await vi.waitFor(() => expect(state.fetch).toHaveBeenCalledTimes(1));
    markEmbedAsError(id, "cancelled"); clearEmbedError(id);
    const newer = requestEmbedFromServerOnce(id, "newer-preview", { chatId: "source" });
    await vi.waitFor(() => expect(state.fetch).toHaveBeenCalledTimes(2));
    await vi.advanceTimersByTimeAsync(10_001);
    releases[0](new Response("{}", { status: 404 }));
    expect(await older).toBe(outcome === "completion");
    expect(await requestEmbedFromServerOnce(id, "third-preview", { chatId: "source" })).toBe(false);
    expect(state.fetch).toHaveBeenCalledTimes(2);
    releases[1](ready(id)); expect(await newer).toBe(true);
    expect(state.put).toHaveBeenCalledTimes(1);
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("keeps the owning source on the WebSocket fallback after navigation during a404 read", async () => {
    const id = embedId(); let release!: (response: Response) => void;
    state.fetch.mockImplementation(() => new Promise(resolve => { release = resolve; }));
    const pending = requestEmbedFromServerOnce(id, "navigation", { chatId: "source" });
    await vi.waitFor(() => expect(state.fetch).toHaveBeenCalledTimes(1));
    state.activeChat = "new-active-chat";
    release(new Response("{}", { status: 404 }));
    expect(await pending).toBe(true);
    expect(state.send).toHaveBeenCalledExactlyOnceWith("request_embed", { embed_id: id, chat_id: "source", team_id: null });
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it.each([403, 503])("does not hydrate an unavailable HTTP%s response", async (status) => {
    const id = embedId();
    state.fetch.mockResolvedValue(new Response("{}", { status }));
    await requestEmbedFromServerOnce(id, "unavailable", { chatId: "source" });
    expect(state.keys).not.toHaveBeenCalled(); expect(state.put).not.toHaveBeenCalled();
    expect(state.send).toHaveBeenCalledExactlyOnceWith("request_embed", { embed_id: id, chat_id: "source", team_id: null });
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("rejects a different embed identity returned by the ciphertext read", async () => {
    const id = embedId(); state.fetch.mockResolvedValue(ready("different-embed"));
    await requestEmbedFromServerOnce(id, "different-identity", { chatId: "source" });
    expect(state.keys).not.toHaveBeenCalled(); expect(state.put).not.toHaveBeenCalled();
    expect(state.send).toHaveBeenCalledExactlyOnceWith("request_embed", { embed_id: id, chat_id: "source", team_id: null });
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("discards a delayed response when its owner changes before local writes", async () => {
    const id = embedId(); let release!: (response: Response) => void;
    state.fetch.mockImplementation(() => new Promise(resolve => { release = resolve; }));
    const pending = requestEmbedFromServerOnce(id, "old-owner", { chatId: "source" });
    await vi.waitFor(() => expect(state.fetch).toHaveBeenCalledTimes(1));
    userProfile.set({ user_id: "owner-2", account_id: "account-2" } as never);
    release(ready(id));
    expect(await pending).toBe(false);
    expect(state.keys).not.toHaveBeenCalled(); expect(state.put).not.toHaveBeenCalled(); expect(state.send).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("keeps failed decryption transient and retries immediately after local key arrival", async () => {
    const id = embedId(); state.loaded.set(`embed:${id}`, { _decryptionFailed: true });
    await resolveEmbed(id, { chatId: "source" });
    await vi.waitFor(() => expect(state.fetch).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(10_001);
    await resolveEmbed(id, { chatId: "source" });
    expect(isEmbedKnownError(id)).toBe(false);
    await vi.waitFor(() => expect(state.fetch).toHaveBeenCalledTimes(2));
    const { computeSHA256 } = await import("../../message_parsing/utils");
    state.localKeys.set(await computeSHA256(id), [{ encrypted_embed_key: "new-wrapped-key", key_type: "chat" }]);
    state.loaded.set(`embed:${id}`, { embed_id: id, status: "finished", content: "decoded" });
    expect(await resolveEmbed(id, { chatId: "source" })).toMatchObject({ status: "finished" });
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it("retries immediately when its chat key becomes ready but not for an unrelated chat key", async () => {
    const id = embedId(); state.loaded.set(`embed:${id}`, { _decryptionFailed: true });
    await resolveEmbed(id, { chatId: "source" });
    await vi.waitFor(() => expect(state.fetch).toHaveBeenCalledTimes(1));
    state.provenance.set("unrelated", { timestamp: 1, keyFingerprint: "unrelated" });
    await resolveEmbed(id, { chatId: "source" }); expect(state.fetch).toHaveBeenCalledTimes(1);
    state.provenance.set("source", { timestamp: 2, keyFingerprint: "ready" });
    state.fetch.mockResolvedValue(ready(id));
    await resolveEmbed(id, { chatId: "source" });
    await vi.waitFor(() => expect(state.put).toHaveBeenCalledTimes(1));
    expect(state.fetch).toHaveBeenCalledTimes(2);
    expect(await resolveEmbed(id, { chatId: "source" })).toMatchObject({ status: "finished" });
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,chats.sync.key-gated-recovery
  it.each(["source", "account", "Team"])("does not carry failed decryption into a new %s context", async kind => {
    const id = embedId(); state.loaded.set(`embed:${id}`, { _decryptionFailed: true });
    await resolveEmbed(id, { chatId: "source" });
    await vi.waitFor(() => expect(state.fetch).toHaveBeenCalledTimes(1));
    if (kind === "account") userProfile.set({ user_id: "next-owner", account_id: "next-account" } as never);
    if (kind === "Team") activeTeamId.set("next-team");
    state.loaded.set(`embed:${id}`, { embed_id: id, status: "finished", content: "decoded" });
    expect(await resolveEmbed(id, { chatId: kind === "source" ? "next-source" : "source" })).toMatchObject({ status: "finished" });
    expect(isEmbedKnownError(id)).toBe(false);
  });

  // contract-test: supporting surface=gui.web assertions=chats.sync.key-gated-recovery
  it("suppresses unchanged failed decrypt work within cooldown but preserves producer terminal errors", async () => {
    const id = embedId(); state.loaded.set(`embed:${id}`, { _decryptionFailed: true });
    const { embedStore } = await import("../embedStore");
    vi.mocked(embedStore.get).mockClear();
    await resolveEmbed(id, { chatId: "source" });
    await resolveEmbed(id, { chatId: "source" });
    expect(embedStore.get).toHaveBeenCalledTimes(1);
    markEmbedAsError(id, "cancelled");
    state.loaded.set(`embed:${id}`, { embed_id: id, status: "finished" });
    expect(await resolveEmbed(id, { chatId: "other-source" })).toBeNull();
    expect(isEmbedKnownError(id)).toBe(true);
    clearEmbedError(id);
  });

  // contract-test: supporting surface=gui.web assertions=public-example-chats.transcript.safe-rendering,chats.persistence.client-encrypted
  it("never fetches missing public example fixtures or editor-only references", async () => {
    expect(await resolveEmbed(embedId(), { chatId: "example-source" })).toBeNull();
    expect(await requestEmbedFromServerOnce(embedId(), "example", { chatId: "example-source" })).toBe(false);
    expect(await requestEmbedFromServerOnce("preview:code:local", "editor", { chatId: "source" })).toBe(false);
    expect(state.fetch).not.toHaveBeenCalled(); expect(state.send).not.toHaveBeenCalled();
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PendingAppsResult } from "../appsWorkspaceResultOutbox";

const state = vi.hoisted(() => ({ authenticated: true, userId: "owner" as string | null, teamId: null as string | null }));
const pendingDisk = vi.hoisted(() => new Map<string, PendingAppsResult>());
vi.mock("../appsWorkspaceResultOutbox", () => ({
  makePendingAppsResultId: (user: string, team: string | null, root: string) => JSON.stringify([user, team, root]),
  stagePendingAppsResult: vi.fn(async (record: PendingAppsResult) => { pendingDisk.set(record.id, structuredClone(record)); }),
  getPendingAppsResult: vi.fn(async (user: string, team: string | null, root: string) => pendingDisk.get(JSON.stringify([user, team, root]))),
  listPendingAppsResults: vi.fn(async (user: string, team: string | null) => [...pendingDisk.values()].filter(row => row.userId === user && row.teamId === team)),
  deletePendingAppsResult: vi.fn(async (record: PendingAppsResult) => { if (pendingDisk.get(record.id)?.revision === record.revision) pendingDisk.delete(record.id); }),
}));
const mocks = vi.hoisted(() => ({
  syncTarget: new EventTarget(),
  sendLoadMoreChats: vi.fn(async (_offset: number) => {}),
  sendMessage: vi.fn(async (_type: string, _payload: unknown) => {}),
  addChat: vi.fn(async (..._args: unknown[]) => {}),
  getChat: vi.fn(async () => null as Record<string, unknown> | null),
  putEncrypted: vi.fn(async () => {}),
  getEmbedKey: vi.fn(async () => new Uint8Array(32).fill(7)),
  getEmbedKeyEntries: vi.fn(async () => [] as Array<Record<string, unknown>>),
  get: vi.fn(async () => undefined as Record<string, unknown> | undefined),
  setEmbedKeyInCache: vi.fn(),
  clearEmbedError: vi.fn(),
  storeEmbedKeys: vi.fn(async () => {}),
  wrapMaster: vi.fn(async () => "master-wrapper"),
  wrapTeam: vi.fn(async () => "team-wrapper"),
  getChatsPage: vi.fn(async () => ({ items: [] as Array<{ chat_id: string; team_id: string | null }>, nextAfter: null as string | null })),
  getEmbedsByHashedChatIdPage: vi.fn(async () => ({ items: [] as Array<Record<string, unknown>>, nextAfter: null as string | null })),
}));

function crypt(value: string): string {
  const bytes = new TextEncoder().encode(value);
  return `encrypted:${btoa(Array.from(bytes, (byte) => String.fromCharCode(byte ^ 73)).join(""))}`;
}
function decrypt(value: string): string {
  const bytes = Uint8Array.from(atob(value.slice("encrypted:".length)), (char) => char.charCodeAt(0) ^ 73);
  return new TextDecoder().decode(bytes);
}

vi.mock("../../config/api", () => ({ getApiEndpoint: (path: string) => `https://api.test${path}` }));
vi.mock("../../data/embedRegistry.generated", () => ({ EMBED_CHILD_TYPE_MAP: { "events:search": "event" } }));
vi.mock("../embedStore", () => ({ embedStore: mocks }));
vi.mock("../embedResolver", () => ({ clearEmbedError: mocks.clearEmbedError }));
vi.mock("../db", () => ({ chatDB: { getChatsPage: mocks.getChatsPage, addChat: mocks.addChat, getChat: mocks.getChat } }));
vi.mock("../../stores/teamStore", () => ({
  activeTeamId: { subscribe: (run: (value: unknown) => void) => { run(state.teamId); return () => {}; } },
  activeTeamContext: { subscribe: (run: (value: unknown) => void) => { run({ teamId: state.teamId, epoch: 1 }); return () => {}; } },
}));
vi.mock("../chatSyncService", () => ({ chatSyncService: Object.assign(mocks.syncTarget, { sendLoadMoreChats: mocks.sendLoadMoreChats }) }));
vi.mock("../websocketService", () => ({ webSocketService: { sendMessage: mocks.sendMessage } }));
vi.mock("../cryptoService", () => ({
  encryptWithEmbedKey: vi.fn(async (value: string) => crypt(value)),
  decryptWithEmbedKey: vi.fn(async (value: string) => decrypt(value)),
  generateEmbedKey: vi.fn(() => new Uint8Array(32).fill(7)),
  wrapEmbedKeyWithMasterKey: mocks.wrapMaster,
  wrapEmbedKeyWithChatKey: mocks.wrapTeam,
  unwrapEmbedKeyWithMasterKey: vi.fn(async () => new Uint8Array(32).fill(7)),
  unwrapEmbedKeyWithChatKey: vi.fn(async () => new Uint8Array(32).fill(7)),
  decryptChatKeyWithMasterKey: vi.fn(async () => new Uint8Array(32).fill(3)),
}));
vi.mock("../teamService", () => ({ getTeamKey: vi.fn(async () => new Uint8Array(32).fill(3)) }));
vi.mock("../anonymousChatKeyWrapping", () => ({
  wrapAnonymousChatKey: vi.fn(async () => "guest-wrapper"),
  unwrapAnonymousChatKey: vi.fn(async () => new Uint8Array(32).fill(7)),
}));
vi.mock("../appsWorkspaceService", () => ({ pollAppsSkillTask: vi.fn() }));
vi.mock("../../stores/userProfile", () => ({ userProfile: { subscribe: (run: (value: unknown) => void) => { run({ user_id: state.userId }); return () => {}; } } }));
vi.mock("../../stores/authStore", () => ({ authStore: { subscribe: (run: (value: unknown) => void) => { run({ isAuthenticated: state.authenticated }); return () => {}; } } }));
vi.mock("../../message_parsing/utils", () => ({ computeSHA256: vi.fn(async () => "hash") }));

const disk = new Map<string, unknown>();
function installGuestIndexedDb() {
  const store = {
    indexNames: { contains: () => false }, createIndex: vi.fn(),
    getAll: () => {
      const request: { result: unknown[]; onsuccess?: () => void; onerror?: () => void } = { result: Array.from(disk.values()) };
      queueMicrotask(() => request.onsuccess?.());
      return request;
    },
    put: (record: { root_embed_id: string }) => { disk.set(record.root_embed_id, record); },
    delete: (id: string) => { disk.delete(id); },
  };
  const db = {
    createObjectStore: () => store,
    transaction: () => {
      const tx: { objectStoreNames: { contains: () => boolean }; objectStore: () => typeof store; oncomplete?: () => void; onerror?: () => void; onabort?: () => void } = {
        objectStoreNames: { contains: () => true }, objectStore: () => store,
      };
      queueMicrotask(() => queueMicrotask(() => tx.oncomplete?.()));
      return tx;
    },
    close: vi.fn(),
  };
  vi.stubGlobal("indexedDB", { open: () => {
    const request: { result: typeof db; transaction: ReturnType<typeof db.transaction>; onupgradeneeded?: () => void; onsuccess?: () => void; onerror?: () => void } = { result: db, transaction: db.transaction() };
    queueMicrotask(() => { request.onupgradeneeded?.(); request.onsuccess?.(); });
    return request;
  } });
}

function successfulUploads(linked: string[] = []) {
  const bodies: unknown[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      bodies.push(JSON.parse(String(init.body)));
      return new Response(JSON.stringify({ root_embed_id: "root", linked_embed_ids: linked }), { status: 200 });
    }
    return new Response("{}", { status: 404 });
  }));
  return bodies;
}

describe("Apps result persistence", () => {
  afterEach(() => vi.useRealTimers());
  beforeEach(() => {
    vi.resetModules();
    vi.clearAllMocks();
    mocks.get.mockResolvedValue(undefined);
    mocks.putEncrypted.mockImplementation(async () => {});
    mocks.getChatsPage.mockResolvedValue({ items: [], nextAfter: null });
    mocks.getEmbedsByHashedChatIdPage.mockResolvedValue({ items: [], nextAfter: null });
    mocks.addChat.mockImplementation(async () => {});
    mocks.sendLoadMoreChats.mockImplementation(async () => {});
    mocks.sendMessage.mockImplementation(async () => {});
    localStorage.clear();
    disk.clear();
    pendingDisk.clear();
    state.authenticated = true;
    state.userId = "owner";
    state.teamId = null;
    installGuestIndexedDb();
    vi.stubGlobal("crypto", { subtle: { digest: async (_name: string, data: Uint8Array) => {
      const bytes = new Uint8Array(32);
      bytes.set(data.slice(0, 16));
      bytes[15] = data[data.length - 1] ?? 0;
      return bytes.buffer;
    } }, randomUUID: () => "00000000-0000-4000-8000-000000000000" });
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph,apps.execution.direct-shared-contract
  it("makes sync results locally available before a single finished upload is acknowledged", async () => {
    const rootId = "94000000-0000-4000-8000-000000000001";
    let acknowledge!: (response: Response) => void;
    const fetchMock = vi.fn(() => new Promise<Response>(resolve => { acknowledge = resolve; }));
    vi.stubGlobal("fetch", fetchMock);
    const service = await import("../appsWorkspaceResultsService");
    await service.retainAppsResult({ appId: "events", skillId: "search", input: { query: "Jazz" },
      response: { status: "processing" }, requestId: rootId, newRequest: true, persistence: "background" });
    expect(fetchMock).not.toHaveBeenCalled();
    await expect(service.retainAppsResult({ appId: "events", skillId: "search", input: { query: "Jazz" },
      response: { results: [{ title: "Jazz night" }] }, requestId: rootId, persistence: "background" })).resolves.toBe(rootId);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(mocks.putEncrypted).toHaveBeenCalledTimes(3); // draft, completed parent and child
    const queued = [...pendingDisk.values()][0];
    expect(queued.graph.embeds).toHaveLength(2);
    expect(queued.graph.embeds[0].status).toBe("finished");
    expect(JSON.stringify(queued)).not.toContain("Jazz night");
    const retry = service.retryAppsResultSave(rootId);
    acknowledge(new Response(JSON.stringify({ root_embed_id: rootId, linked_embed_ids: [] }), { status: 200 }));
    await retry;
    expect(pendingDisk.size).toBe(0);
    const { get } = await import("svelte/store");
    expect(get(service.appsResultSaveStates)[service.appsResultSaveKey("owner", null, rootId)]).toBe("saved");
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph
  it("keeps successful local results after upload failure and retries the identical ciphertext", async () => {
    const rootId = "94000000-0000-4000-8000-000000000002";
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response("unavailable", { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ root_embed_id: rootId, linked_embed_ids: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const service = await import("../appsWorkspaceResultsService");
    await service.retainAppsResult({ appId: "events", skillId: "search", input: {},
      response: { results: [{ title: "Visible despite failed save" }] }, requestId: rootId, newRequest: true, persistence: "background" });
    const { get } = await import("svelte/store");
    await vi.waitFor(() => expect(get(service.appsResultSaveStates)[service.appsResultSaveKey("owner", null, rootId)]).toBe("error"));
    expect(mocks.putEncrypted).toHaveBeenCalledTimes(2);
    expect(pendingDisk.size).toBe(1);
    const firstBody = fetchMock.mock.calls[0][1].body;
    await service.retryAppsResultSave(rootId);
    expect(fetchMock.mock.calls[1][1].body).toBe(firstBody);
    expect(pendingDisk.size).toBe(0);
    expect(get(service.appsResultSaveStates)[service.appsResultSaveKey("owner", null, rootId)]).toBe("saved");
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph
  it("serializes accepted processing and finished revisions without deleting a newer graph", async () => {
    const rootId = "94000000-0000-4000-8000-000000000003";
    let revision = 0;
    vi.stubGlobal("crypto", { ...crypto, randomUUID: () => `revision-${++revision}` });
    const acknowledgements: Array<(response: Response) => void> = [];
    const fetchMock = vi.fn(() => new Promise<Response>(resolve => { acknowledgements.push(resolve); }));
    vi.stubGlobal("fetch", fetchMock);
    const service = await import("../appsWorkspaceResultsService");
    await service.retainAppsResult({ appId: "events", skillId: "search", input: {},
      response: { status: "processing", task_id: "accepted-task" }, requestId: rootId, newRequest: true, persistence: "background" });
    await service.retainAppsResult({ appId: "events", skillId: "search", input: {},
      response: { results: [{ title: "Completed" }] }, requestId: rootId, persistence: "background" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect([...pendingDisk.values()][0].graph.embeds[0].status).toBe("finished");
    acknowledgements[0](new Response(JSON.stringify({ root_embed_id: rootId, linked_embed_ids: [] }), { status: 200 }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect([...pendingDisk.values()][0].graph.embeds[0].status).toBe("finished");
    const finished = service.retryAppsResultSave(rootId);
    acknowledgements[1](new Response(JSON.stringify({ root_embed_id: rootId, linked_embed_ids: [] }), { status: 200 }));
    await finished;
    expect(pendingDisk.size).toBe(0);
    const bodies = fetchMock.mock.calls.map((call: unknown[]) => JSON.parse((call[1] as RequestInit).body as string));
    expect(bodies.map(body => body.embeds[0].status)).toEqual(["processing", "finished"]);
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph,apps.library.embeds-account-paginated
  it("recovers only the active account's pending graph after reload without a server lookup", async () => {
    const rootId = "94000000-0000-4000-8000-000000000004";
    vi.stubGlobal("fetch", vi.fn(async () => new Response("offline", { status: 503 })));
    const initial = await import("../appsWorkspaceResultsService");
    await initial.retainAppsResult({ appId: "events", skillId: "search", input: {},
      response: { results: [{ title: "Survives reload" }] }, requestId: rootId, newRequest: true, persistence: "background" });
    const { get } = await import("svelte/store");
    await vi.waitFor(() => expect(get(initial.appsResultSaveStates)[initial.appsResultSaveKey("owner", null, rootId)]).toBe("error"));
    vi.resetModules();
    mocks.putEncrypted.mockClear();
    const recovered = await import("../appsWorkspaceResultsService");
    state.userId = "other-user";
    expect(await recovered.recoverPendingAppsResults(null, "events", "search")).toBeNull();
    expect(mocks.putEncrypted).not.toHaveBeenCalled();
    state.userId = "owner";
    expect(await recovered.recoverPendingAppsResults(null, "events", "search")).toBe(rootId);
    expect(mocks.putEncrypted).toHaveBeenCalledTimes(2);
    expect(await recovered.listPendingAppsResultItems("events")).toHaveLength(1);
    const requests = vi.mocked(fetch).mock.calls;
    expect(requests.every((call) => call[1]?.method === "POST")).toBe(true);
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph,apps.execution.direct-shared-contract
  it("turns a cold unaccepted processing draft into an encrypted interrupted result", async () => {
    const rootId = "94000000-0000-4000-8000-000000000005";
    const initial = await import("../appsWorkspaceResultsService");
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ root_embed_id: rootId, linked_embed_ids: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await initial.retainAppsResult({ appId: "events", skillId: "search", input: { query: "Private draft" },
      response: { status: "processing" }, requestId: rootId, newRequest: true, persistence: "background" });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(pendingDisk.get(JSON.stringify(["owner", null, rootId]))?.graph.embeds[0].status).toBe("processing");

    vi.resetModules();
    const recovered = await import("../appsWorkspaceResultsService");
    expect(await recovered.recoverPendingAppsResults(null, "events", "search")).toBeNull();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const body = JSON.parse(String(fetchMock.mock.calls[0][1]?.body)) as { embeds: Array<{ status: string; encrypted_content: string }> };
    expect(body.embeds[0].status).toBe("error");
    expect(JSON.parse(decrypt(body.embeds[0].encrypted_content))).toMatchObject({
      status: "error", error: "request_interrupted", input: { query: "Private draft" },
    });
    expect(String(fetchMock.mock.calls[0][1]?.body)).not.toContain("Private draft");
    const { pollAppsSkillTask } = await import("../appsWorkspaceService");
    expect(pollAppsSkillTask).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph,apps.execution.direct-shared-contract
  it("resumes a cold accepted task only after its processing graph is acknowledged", async () => {
    const rootId = "94000000-0000-4000-8000-000000000006";
    const id = JSON.stringify(["owner", null, rootId]);
    const root = { embed_id: rootId, encrypted_type: crypt("app_skill_use"),
      encrypted_content: crypt(JSON.stringify({ app_id: "events", skill_id: "search", input: { query: "Private search" },
        task_ids: ["accepted-task"], status: "processing", embed_ids: [] })), status: "processing" as const, embed_ids: [] };
    pendingDisk.set(id, { id, userId: "owner", teamId: null, rootEmbedId: rootId, revision: "accepted-1",
      graph: { app_id: "events", skill_id: "search", root_embed_id: rootId, embeds: [root],
        encrypted_embed_key: "master-wrapper", created_at: 123 }, updatedAt: 123 });
    let acknowledge!: (response: Response) => void;
    const requests: Array<{ url: string; init?: RequestInit }> = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      requests.push({ url, init });
      if (init?.method === "POST" && requests.filter(item => item.init?.method === "POST").length === 1) {
        return new Promise<Response>(resolve => { acknowledge = resolve; });
      }
      if (url.endsWith(`/v1/apps/workspace/results/${rootId}`)) return Promise.resolve(new Response(JSON.stringify({
        root: { ...root, app_id: "events", skill_id: "search", created_at: 123 }, children: [],
        key: { encrypted_embed_key: "master-wrapper", hashed_user_id: "owner-hash", created_at: 123 },
      }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify({ root_embed_id: rootId, linked_embed_ids: [] }), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    mocks.get.mockResolvedValue({ status: "processing", content: decrypt(root.encrypted_content) });
    const { pollAppsSkillTask } = await import("../appsWorkspaceService");
    vi.mocked(pollAppsSkillTask).mockResolvedValue({ results: [{ title: "Recovered event" }] });
    const service = await import("../appsWorkspaceResultsService");
    expect(await service.recoverPendingAppsResults(null, "events", "search")).toBeNull();
    expect(requests).toHaveLength(1);
    expect(pollAppsSkillTask).not.toHaveBeenCalled();
    acknowledge(new Response(JSON.stringify({ root_embed_id: rootId, linked_embed_ids: [] }), { status: 200 }));
    await vi.waitFor(() => expect(requests.filter(item => item.init?.method === "POST")).toHaveLength(2));
    expect(pollAppsSkillTask).toHaveBeenCalledExactlyOnceWith("accepted-task", { expectedUserId: "owner" });
    expect(requests.every(item => !item.url.includes("/v1/apps/events/skills/search"))).toBe(true);
    const finished = JSON.parse(String(requests.filter(item => item.init?.method === "POST")[1].init?.body)) as {
      embeds: Array<{ status: string; encrypted_content: string }>;
    };
    expect(finished.embeds[0].status).toBe("finished");
    expect(finished.embeds).toHaveLength(2);
    expect(JSON.parse(decrypt(finished.embeds[1].encrypted_content))).toMatchObject({ title: "Recovered event" });
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph
  it("keeps a provider-ID graph pending after failed save and preserves an existing linked asset on retry", async () => {
    const rootId = "94000000-0000-4000-8000-000000000007";
    const assetId = "94000000-0000-4000-8000-000000000008";
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response("unavailable", { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ root_embed_id: rootId, linked_embed_ids: [assetId] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const service = await import("../appsWorkspaceResultsService");
    await expect(service.retainAppsResult({ appId: "events", skillId: "search", input: { query: "Private" },
      response: { results: [{ embed_id: assetId, title: "Original provider asset" }] },
      requestId: rootId, newRequest: true, persistence: "background" })).rejects.toBeInstanceOf(service.AppsResultSavePendingError);
    const queued = pendingDisk.get(JSON.stringify(["owner", null, rootId]));
    expect(queued?.graph.embeds[0].status).toBe("finished");
    expect(queued?.graph.embeds.map(row => row.embed_id)).toEqual([rootId, assetId]);
    expect(JSON.stringify(queued)).not.toContain("Original provider asset");
    expect(mocks.putEncrypted.mock.calls.map(call => call[0])).toEqual([`embed:${rootId}`]);
    await service.retryAppsResultSave(rootId);
    expect(fetchMock.mock.calls[1][1].body).toBe(fetchMock.mock.calls[0][1].body);
    expect(mocks.putEncrypted.mock.calls.map(call => call[0])).toEqual([`embed:${rootId}`]);
    expect(mocks.setEmbedKeyInCache).not.toHaveBeenCalledWith(assetId, expect.anything());
    expect(pendingDisk.has(JSON.stringify(["owner", null, rootId]))).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph
  it("retains every nested direct result as encrypted parent and children", async () => {
    const bodies = successfulUploads();
    const { retainAppsResult } = await import("../appsWorkspaceResultsService");
    const results = Array.from({ length: 25 }, (_, index) => ({ title: `Private event ${index}`, id: index }));
    await retainAppsResult({ appId: "events", skillId: "search", input: { requests: [{ query: "Private jazz" }] },
      response: { success: true, data: { provider: "events", results: [{ id: "q1", results }] } },
      requestId: "10000000-0000-4000-8000-000000000000" });
    const body = bodies[0] as { embeds: Array<{ encrypted_content: string; embed_id: string }>; root_embed_id: string };
    expect(body.embeds).toHaveLength(26);
    expect(body.embeds[0].embed_id).toBe(body.root_embed_id);
    expect(JSON.stringify(body)).not.toContain("Private jazz");
    expect(JSON.stringify(body)).not.toContain("Private event 0");
    expect(JSON.parse(decrypt(body.embeds[0].encrypted_content))).toMatchObject({ app_id: "events", skill_id: "search", query: "Private jazz", input: { requests: [{ query: "Private jazz" }] }, result_count: 25, provider: "events" });
  });

  // contract-test: direct surface=gui.web assertions=apps.anonymous.local-results-and-promotion
  it("keeps encrypted guest graph after failed promotion and retries the same IDs", async () => {
    state.authenticated = false;
    const { retainAppsResult, promoteGuestAppsResults } = await import("../appsWorkspaceResultsService");
    const id = "20000000-0000-4000-8000-000000000000";
    await retainAppsResult({ appId: "events", skillId: "search", input: { query: "Private walk" }, response: { results: [{ title: "Private venue" }] }, guest: true, requestId: id });
    expect(disk.size).toBe(1);
    expect(JSON.stringify(Array.from(disk.values()))).not.toContain("Private venue");
    state.authenticated = true;
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    await expect(promoteGuestAppsResults()).rejects.toThrow("offline");
    expect(disk.has(id)).toBe(true);
    const bodies = successfulUploads();
    expect(await promoteGuestAppsResults()).toBe(1);
    expect(await promoteGuestAppsResults()).toBe(0);
    expect(disk.size).toBe(0);
    expect((bodies[0] as { root_embed_id: string }).root_embed_id).toBe(id);
  });

  // contract-test: direct surface=gui.web assertions=apps.anonymous.local-results-and-promotion,apps.library.embeds-account-paginated
  it("keeps guest source when account changes during a successful upload", async () => {
    state.authenticated = false;
    const { retainAppsResult, promoteGuestAppsResults } = await import("../appsWorkspaceResultsService");
    const id = "70000000-0000-4000-8000-000000000000";
    await retainAppsResult({ appId: "events", skillId: "search", input: {}, response: { results: [{ title: "Private result" }] }, guest: true, requestId: id });
    state.authenticated = true;
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body)).expected_user_id).toBe("owner");
      state.userId = "other-user";
      return new Response(JSON.stringify({ root_embed_id: id, linked_embed_ids: [] }), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    await expect(promoteGuestAppsResults()).rejects.toThrow("account changed");
    expect(disk.has(id)).toBe(true);
    state.userId = "owner";
    successfulUploads();
    expect(await promoteGuestAppsResults()).toBe(1);
    expect(disk.has(id)).toBe(false);
  });

  // contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated,apps.results.web-retained-graph
  it("pins the submitted Team wrapper and refuses account switches", async () => {
    const bodies = successfulUploads();
    const { retainAppsResult } = await import("../appsWorkspaceResultsService");
    const requestId = "30000000-0000-4000-8000-000000000000";
    await retainAppsResult({ appId: "events", skillId: "search", input: {}, response: { status: "processing", task_id: "task" }, teamId: "team-a", requestId });
    await retainAppsResult({ appId: "events", skillId: "search", input: {}, response: { data: { results: [] } }, teamId: "team-a", requestId });
    expect(mocks.wrapTeam).toHaveBeenCalledTimes(1);
    expect((bodies[0] as { encrypted_embed_key: string }).encrypted_embed_key).toBe((bodies[1] as { encrypted_embed_key: string }).encrypted_embed_key);
    await expect(retainAppsResult({ appId: "events", skillId: "search", input: {}, response: {}, requestId })).rejects.toThrow("account changed");
    state.userId = "other-user";
    await expect(retainAppsResult({ appId: "events", skillId: "search", input: {}, response: {}, teamId: "team-a", requestId })).rejects.toThrow("account changed");
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph
  it("keeps every accepted task ID encrypted across processing updates", async () => {
    const bodies = successfulUploads();
    const { retainAppsResult } = await import("../appsWorkspaceResultsService");
    const requestId = "31000000-0000-4000-8000-000000000000";
    await retainAppsResult({ appId: "events", skillId: "search", input: { private: "query" },
      response: { status: "processing", task_id: "task-a" }, requestId });
    mocks.get.mockResolvedValueOnce({ status: "processing", content: JSON.stringify({ task_id: "task-a" }) });
    await retainAppsResult({ appId: "events", skillId: "search", input: { private: "query" },
      response: { status: "processing", task_id: "task-b" }, requestId });
    const second = bodies[1] as { embeds: Array<{ encrypted_content: string }> };
    expect(JSON.parse(decrypt(second.embeds[0].encrypted_content)).task_ids).toEqual(["task-a", "task-b"]);
    expect(JSON.stringify(second)).not.toContain("query");
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph
  it("reuses a generated asset ID without replacing its existing encrypted row or key", async () => {
    const assetId = "40000000-0000-4000-8000-000000000000";
    const bodies = successfulUploads([assetId]);
    const { retainAppsResult } = await import("../appsWorkspaceResultsService");
    await retainAppsResult({ appId: "images", skillId: "generate", input: { prompt: "Private image" },
      response: { data: { results: [{ embed_id: assetId, type: "image", files: [{ variant: "original" }] }] } },
      teamId: "team-a", requestId: "50000000-0000-4000-8000-000000000000" });
    const body = bodies[0] as { embeds: Array<{ embed_id: string }> };
    expect(body.embeds.map((row) => row.embed_id)).toContain(assetId);
    expect(mocks.putEncrypted).toHaveBeenCalledTimes(1); // only the new root is written locally
    expect(mocks.setEmbedKeyInCache).not.toHaveBeenCalledWith(assetId, expect.anything());
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph,apps.library.embeds-account-paginated
  it("refreshes expired Team media URLs in local ciphertext using the existing child key", async () => {
    const assetId = "60000000-0000-4000-8000-000000000000";
    mocks.get.mockResolvedValue({
      status: "finished", type: "image", parent_embed_id: "root", createdAt: 1,
      content: JSON.stringify({ app_id: "images", skill_id: "generate", files: { original: { download_url: "https://api.test/expired", download_expires_at: 1 } } }),
    });
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ download_url: "https://api.test/fresh", download_expires_at: 9999999999 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const { refreshAppsGeneratedAssetUrls } = await import("../appsWorkspaceResultsService");
    await refreshAppsGeneratedAssetUrls([assetId], "team-a");
    expect(fetchMock).toHaveBeenCalledWith(
      `https://api.test/v1/generated-assets/${assetId}/files/original/download-url?team_id=team-a`,
      expect.objectContaining({ credentials: "include" }),
    );
    const stored = (mocks.putEncrypted.mock.calls as unknown as Array<[string, { encrypted_content: string }]>)[0][1];
    const content = JSON.parse(decrypt(stored.encrypted_content)) as { previewImageUrl: string; files: { original: { download_url: string } } };
    expect(content.previewImageUrl).toBe("https://api.test/fresh");
    expect(content.files.original.download_url).toBe("https://api.test/fresh");
    expect(mocks.getEmbedKey).toHaveBeenCalledWith(assetId);
    expect(mocks.wrapTeam).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
  it("indexes historical local chat roots in bounded account-scoped batches", async () => {
    const chatId = "80000000-0000-4000-8000-000000000000";
    const rootId = "81000000-0000-4000-8000-000000000000";
    mocks.getChatsPage.mockResolvedValueOnce({ items: [{ chat_id: chatId, team_id: null }], nextAfter: null });
    mocks.getEmbedsByHashedChatIdPage.mockResolvedValueOnce({ items: [{
      contentRef: `embed:${rootId}`, embed_id: rootId, app_id: "audio", skill_id: "generate",
      hashed_chat_id: "hash", encrypted_content: crypt("private audio result"), status: "finished",
    }], nextAfter: null });
    const posted: Array<{ expected_user_id: string; team_id: string | null; items: Array<Record<string, string>> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      posted.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify({ indexed: 1, received: 1 }), { status: 200 });
    }));
    const { indexHistoricalAppsResults } = await import("../appsWorkspaceResultsService");
    await indexHistoricalAppsResults("audio");
    expect(mocks.getChatsPage).toHaveBeenCalledWith(null, 50);
    expect(mocks.getEmbedsByHashedChatIdPage).toHaveBeenCalledWith("hash", null, 50);
    expect(posted).toEqual([{ expected_user_id: "owner", team_id: null, items: [
      { embed_id: rootId, chat_id: chatId, app_id: "audio", skill_id: "generate" },
    ] }]);
    expect(JSON.stringify(posted)).not.toContain("private audio result");
  });

  // contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
  it("indexes a legacy root synced after the first empty library scan without reloading", async () => {
    const chatId = "88000000-0000-4000-8000-000000000000";
    const rootId = "89000000-0000-4000-8000-000000000000";
    const posted: Array<{ expected_user_id: string; items: Array<{ embed_id: string }> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      posted.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify({ indexed: 1, received: 1 }), { status: 200 });
    }));
    const { indexHistoricalAppsResults, notifyAppsHistoricalEmbedsSynced } = await import("../appsWorkspaceResultsService");
    await indexHistoricalAppsResults("audio");
    expect(posted).toHaveLength(0);

    // The encrypted bulk sync has now committed a chat and its root embed.
    mocks.getChatsPage.mockResolvedValue({ items: [{ chat_id: chatId, team_id: null }], nextAfter: null });
    mocks.getEmbedsByHashedChatIdPage.mockResolvedValue({ items: [{
      embed_id: rootId, app_id: "audio", skill_id: "generate", hashed_chat_id: "hash",
      encrypted_content: crypt("private legacy result"), status: "finished",
    }], nextAfter: null });
    vi.useFakeTimers();
    notifyAppsHistoricalEmbedsSynced("owner");
    await vi.advanceTimersByTimeAsync(350);
    expect(posted).toEqual([{ expected_user_id: "owner", team_id: null, items: [{ embed_id: rootId, chat_id: chatId, app_id: "audio", skill_id: "generate" }] }]);
    expect(JSON.stringify(posted)).not.toContain("private legacy result");
  });

  // contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
  it("discovers an uncached older chat through bounded ciphertext pages and resumes by cursor", async () => {
    const chatId = "90000000-0000-4000-8000-000000000000";
    const rootId = "91000000-0000-4000-8000-000000000000";
    const posted: Array<{ expected_user_id: string; items: Array<{ embed_id: string }> }> = [];
    const chat = { chat_id: chatId, team_id: null, encrypted_chat_key: "chat-wrapper" };
    mocks.sendLoadMoreChats.mockImplementation(async (offset) => {
      queueMicrotask(() => mocks.syncTarget.dispatchEvent(new CustomEvent("load_more_chats_ready", {
        detail: { chats: [chat], has_more: false, offset, team_id: null },
      })));
    });
    mocks.sendMessage.mockImplementation(async (_type, payload) => {
      const request = payload as { request_id: string; chat_ids: string[]; embed_offset: number; apps_legacy_embeds_only: boolean };
      expect(request.chat_ids).toEqual([chatId]);
      expect(request.embed_offset).toBe(0);
      expect(request.apps_legacy_embeds_only).toBe(true);
      queueMicrotask(() => mocks.syncTarget.dispatchEvent(new CustomEvent("apps_legacy_embed_page_ready", {
        detail: { request_id: request.request_id, chat_id: chatId, team_id: null, embed_offset: 0,
          next_embed_offset: null, embeds: [{ embed_id: rootId, hashed_chat_id: "hash", encrypted_content: crypt('{"app_id":"audio","skill_id":"generate","private":"result"}'), status: "finished" }],
          embed_keys: [{ hashed_embed_id: "hash", hashed_chat_id: "hash", key_type: "chat", encrypted_embed_key: "wrapper", hashed_user_id: "hash", created_at: 1 }] },
      })));
    });
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      posted.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify({ indexed: 1, received: 1 }), { status: 200 });
    }));
    const { startAppsHistoricalDiscovery } = await import("../appsWorkspaceResultsService");
    const stop = startAppsHistoricalDiscovery("audio");
    await vi.waitFor(() => expect(posted).toHaveLength(1));
    expect(posted[0].items[0].embed_id).toBe(rootId);
    expect(JSON.stringify(posted)).not.toContain("private");
    expect(mocks.addChat).toHaveBeenCalledWith(chat, undefined, expect.objectContaining({ isFromSync: true, writeGuard: expect.any(Function) }));
    expect(mocks.storeEmbedKeys).toHaveBeenCalledWith(expect.any(Array), expect.any(Function));
    expect(localStorage.getItem("apps-legacy-discovery:owner:personal")).toBe("done");
    stop();
    const again = startAppsHistoricalDiscovery("audio");
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mocks.sendLoadMoreChats).toHaveBeenCalledTimes(1);
    again();
  });

  // contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
  it("resumes at the last completed older-chat page after library exit", async () => {
    let secondPageRequests = 0;
    mocks.sendLoadMoreChats.mockImplementation(async (offset) => {
      if (offset === 100) {
        queueMicrotask(() => mocks.syncTarget.dispatchEvent(new CustomEvent("load_more_chats_ready", {
          detail: { chats: [], has_more: true, offset, team_id: null },
        })));
      } else {
        secondPageRequests++;
        if (secondPageRequests === 2) queueMicrotask(() => mocks.syncTarget.dispatchEvent(new CustomEvent("load_more_chats_ready", {
          detail: { chats: [], has_more: false, offset, team_id: null },
        })));
      }
    });
    const { startAppsHistoricalDiscovery } = await import("../appsWorkspaceResultsService");
    const stop = startAppsHistoricalDiscovery("audio");
    await vi.waitFor(() => expect(localStorage.getItem("apps-legacy-discovery:owner:personal")).toBe("120"));
    await vi.waitFor(() => expect(secondPageRequests).toBe(1));
    stop();
    const resumed = startAppsHistoricalDiscovery("audio");
    await vi.waitFor(() => expect(localStorage.getItem("apps-legacy-discovery:owner:personal")).toBe("done"));
    expect(mocks.sendLoadMoreChats.mock.calls.map((call) => call[0])).toEqual([100, 120, 120]);
    resumed();
  });

  // contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
  it("stops older-chat projection when the account changes before the guarded metadata put", async () => {
    const chatId = "92000000-0000-4000-8000-000000000000";
    const rootId = "93000000-0000-4000-8000-000000000000";
    let releasePut: (() => void) | undefined;
    mocks.addChat.mockImplementation(async (...args: unknown[]) => {
      await new Promise<void>((resolve) => { releasePut = resolve; });
      state.userId = "account-b";
      (args[2] as { writeGuard: () => void }).writeGuard();
    });
    mocks.sendLoadMoreChats.mockImplementation(async (offset) => {
      queueMicrotask(() => mocks.syncTarget.dispatchEvent(new CustomEvent("load_more_chats_ready", {
        detail: { chats: [{ chat_id: chatId, team_id: null, encrypted_chat_key: "chat-wrapper" }], has_more: false, offset, team_id: null },
      })));
    });
    mocks.sendMessage.mockImplementation(async (_type, payload) => {
      const request = payload as { request_id: string };
      queueMicrotask(() => mocks.syncTarget.dispatchEvent(new CustomEvent("apps_legacy_embed_page_ready", {
        detail: { request_id: request.request_id, chat_id: chatId, team_id: null, embed_offset: 0,
          next_embed_offset: null, embeds: [{ embed_id: rootId, hashed_chat_id: "hash", encrypted_content: crypt('{"app_id":"audio","skill_id":"generate"}'), status: "finished" }],
          embed_keys: [{ hashed_embed_id: "hash", hashed_chat_id: "hash", key_type: "chat", encrypted_embed_key: "wrapper", hashed_user_id: "hash", created_at: 1 }] },
      })));
    });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { startAppsHistoricalDiscovery } = await import("../appsWorkspaceResultsService");
    const stop = startAppsHistoricalDiscovery("audio");
    await vi.waitFor(() => expect(releasePut).toBeTypeOf("function"));
    releasePut?.();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mocks.storeEmbedKeys).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(localStorage.getItem("apps-legacy-discovery:owner:personal")).toBeNull();
    stop();
  });

  // contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
  it("continues indexing another chat after a stale local chat cannot be read", async () => {
    const staleChat = "82000000-0000-4000-8000-000000000000";
    const validChat = "83000000-0000-4000-8000-000000000000";
    const rootId = "84000000-0000-4000-8000-000000000000";
    mocks.getChatsPage.mockResolvedValueOnce({ items: [
      { chat_id: staleChat, team_id: null }, { chat_id: validChat, team_id: null },
    ], nextAfter: null });
    mocks.getEmbedsByHashedChatIdPage.mockRejectedValueOnce(new Error("stale local index"));
    mocks.getEmbedsByHashedChatIdPage.mockResolvedValueOnce({ items: [{
      contentRef: `embed:${rootId}`, embed_id: rootId, app_id: "audio", skill_id: "generate",
      hashed_chat_id: "hash", encrypted_content: crypt("private"), status: "finished",
    }], nextAfter: null });
    const bodies = successfulUploads();
    const { indexHistoricalAppsResults } = await import("../appsWorkspaceResultsService");
    await indexHistoricalAppsResults("audio");
    expect(bodies).toHaveLength(1);
    expect((bodies[0] as { items: Array<{ chat_id: string }> }).items[0].chat_id).toBe(validChat);
  });

  // contract-test: direct surface=gui.web assertions=apps.library.embeds-account-paginated
  it("reopens a legacy chat root with its original chat-key wrapper", async () => {
    const rootId = "85000000-0000-4000-8000-000000000000";
    const childId = "86000000-0000-4000-8000-000000000000";
    const root = { embed_id: rootId, app_id: "audio", skill_id: "generate", hashed_chat_id: "chat-hash",
      encrypted_type: crypt("app_skill_use"), encrypted_content: crypt('{"app_id":"audio"}'),
      status: "finished", embed_ids: [childId], created_at: 1, updated_at: 1 };
    const child = { embed_id: childId, encrypted_type: crypt("audio"),
      encrypted_content: crypt('{"app_id":"audio"}'), status: "finished", parent_embed_id: rootId };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ root, children: [child], linked: [], key: null }), { status: 200 })));
    const { getAppsResult } = await import("../appsWorkspaceResultsService");
    await getAppsResult(rootId);
    expect(mocks.getEmbedKey).toHaveBeenCalledWith(rootId, "chat-hash");
    expect(mocks.putEncrypted).toHaveBeenCalledTimes(2);
    expect(mocks.storeEmbedKeys).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph,apps.library.embeds-account-paginated
  it("clears a preview's stale decryption failure after restoring all 25 result keys", async () => {
    const rootId = "88000000-0000-4000-8000-000000000000";
    const children = Array.from({ length: 25 }, (_, index) => ({
      embed_id: `89000000-0000-4000-8000-${String(index).padStart(12, "0")}`,
      encrypted_type: crypt("website"),
      encrypted_content: crypt(JSON.stringify({ title: `Page ${index + 1}`, url: `https://example.test/${index + 1}` })),
      status: "finished",
      parent_embed_id: rootId,
    }));
    const root = { embed_id: rootId, app_id: "web", skill_id: "search",
      encrypted_type: crypt("app_skill_use"), encrypted_content: crypt(JSON.stringify({ app_id: "web", skill_id: "search", embed_ids: children.map((child) => child.embed_id) })),
      status: "finished", embed_ids: children.map((child) => child.embed_id), created_at: 1, updated_at: 1 };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ root, children, linked: [], key: {
      hashed_embed_id: "hash", hashed_user_id: "owner-hash", encrypted_embed_key: "master-wrapper", key_type: "master", created_at: 1,
    } }), { status: 200 })));

    const { getAppsResult } = await import("../appsWorkspaceResultsService");
    await getAppsResult(rootId);

    expect(mocks.putEncrypted).toHaveBeenCalledTimes(26);
    expect(mocks.clearEmbedError.mock.calls.map(([id]) => id)).toEqual([rootId, ...children.map((child) => child.embed_id)]);
    for (let index = 0; index < 26; index++) {
      expect(mocks.clearEmbedError.mock.invocationCallOrder[index]).toBeGreaterThan(mocks.setEmbedKeyInCache.mock.invocationCallOrder[index]);
    }
  });

  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph,apps.library.embeds-account-paginated
  it("pins authenticated hydration to the submitting account through the local write guard", async () => {
    const bodies = successfulUploads();
    mocks.putEncrypted.mockImplementation(async (...args: unknown[]) => {
      state.userId = "account-b";
      const options = args[5] as { writeGuard: () => void };
      options.writeGuard();
    });
    const { retainAppsResult } = await import("../appsWorkspaceResultsService");
    await expect(retainAppsResult({ appId: "events", skillId: "search", input: {},
      response: { data: { results: [] } }, requestId: "87000000-0000-4000-8000-000000000000" }))
      .rejects.toThrow("account changed");
    expect(bodies).toHaveLength(1); // Server accepted A; B received no local row.
    expect(mocks.putEncrypted).toHaveBeenCalledTimes(1);
  });
  // contract-test: direct surface=gui.web assertions=apps.results.web-retained-graph
  it("keeps the request query in the encrypted parent for the regular search preview", async () => {
    const bodies = successfulUploads();
    const { retainAppsResult } = await import("../appsWorkspaceResultsService");
    await retainAppsResult({ appId: "events", skillId: "search", input: { query: "Saved parent query" }, response: { results: [{ title: "Result" }] }, requestId: "92000000-0000-4000-8000-000000000001" });
    const root = (bodies[0] as { embeds: Array<{ encrypted_content: string }> }).embeds[0];
    expect(JSON.parse(decrypt(root.encrypted_content)).query).toBe("Saved parent query");
    expect(JSON.stringify(bodies)).not.toContain("Saved parent query");
  });

  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph
  it("does not hide a hydrated media graph if generated URL refresh fails", async () => {
    const id = "93000000-0000-4000-8000-000000000001";
    const root = { embed_id: id, app_id: "images", skill_id: "generate", encrypted_type: crypt("app_skill_use"), encrypted_content: crypt('{"app_id":"images"}'), status: "finished", embed_ids: [], created_at: 1, updated_at: 1 };
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ root, children: [], linked: [], key: { hashed_embed_id: "hash", hashed_user_id: "owner-hash", encrypted_embed_key: "master-wrapper", key_type: "master", created_at: 1 } }), { status: 200 })));
    mocks.get.mockRejectedValueOnce(new Error("Transient cache failure"));
    const { getAppsResult } = await import("../appsWorkspaceResultsService");
    await expect(getAppsResult(id)).resolves.toBeUndefined();
    expect(mocks.putEncrypted).toHaveBeenCalledTimes(1);
  });

});

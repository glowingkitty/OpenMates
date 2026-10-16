import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../config/api", () => ({ storageArchiveFetch: (input: RequestInfo | URL, init?: RequestInit) => globalThis.fetch(input, init), getApiEndpoint: (path: string) => path }));
vi.mock("../../message_parsing/utils", () => ({ computeSHA256: async (value: string) => `hash-${value}` }));
vi.mock("../userPlanService", () => ({ validateUserFlows: () => [] }));
vi.mock("../cryptoService", () => ({
  decryptWithEmbedKey: async (value: string) => value,
  unwrapEmbedKeyWithChatKey: async () => new Uint8Array([2]),
}));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: {
  getKeySync: () => new Uint8Array([1]), getKey: async () => new Uint8Array([1]),
} }));

import { loadSharedChatDetailsPage } from "../sharedChatDetailsService";

const plan = (id: string, updated_at: number) => ({
  plan_id: id, status: "active", primary_chat_id: "share", updated_at,
  created_at: updated_at, encrypted_title: `title-${id}`, encrypted_goal: `goal-${id}`,
});
const wrapper = (id: string) => ({ id: `key-${id}`, key_type: "chat",
  hashed_plan_id: `hash-${id}`, encrypted_plan_key: `wrapped-${id}` });

afterEach(() => vi.unstubAllGlobals());

describe("shared Plan and Task cursor pages", () => {
  // contract-test: direct surface=gui.web assertions=storage.cold.discoverable-bounded
  it("fetches one requested Plan page and loads older rows only on explicit continuation", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({
        items: [plan("p2", 200), plan("p3", 300)], key_wrappers: [wrapper("p2"), wrapper("p3")],
        key_wrapper_window: { has_more_after: false, end_cursor: "key-p3" },
        has_more_before: true, start_cursor: { timestamp: 200, id: "p2" }, oversized_id: null, payload_bytes: 200,
      }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({
        items: [plan("p1", 100)], key_wrappers: [wrapper("p1")],
        key_wrapper_window: { has_more_after: false, end_cursor: "key-p1" },
        has_more_before: false, start_cursor: { timestamp: 100, id: "p1" }, oversized_id: null, payload_bytes: 100,
      }) });
    vi.stubGlobal("fetch", fetcher);
    const first = await loadSharedChatDetailsPage("share", "plans");
    expect(first.plans.map((item) => item.plan_id)).toEqual(["p2", "p3"]);
    expect(first.window).toEqual({ hasMoreBefore: true, startCursor: { timestamp: 200, id: "p2" } });
    expect(fetcher).toHaveBeenCalledTimes(1);
    const next = await loadSharedChatDetailsPage("share", "plans", first.window.startCursor);
    expect(next.plans.map((item) => item.plan_id)).toEqual(["p1"]);
    expect(next.window.hasMoreBefore).toBe(false);
    expect(fetcher.mock.calls[1][0]).toContain("before_timestamp=200&before_id=p2");
  });

  // contract-test: direct surface=gui.web assertions=storage.cold.discoverable-bounded
  it("reads an oversized selected Plan exactly and continues past its cursor", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({
        items: [], key_wrappers: [], has_more_before: true, start_cursor: null,
        oversized_id: "p1", payload_bytes: 0,
      }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({
        item: plan("p1", 100), key_wrappers: [wrapper("p1")],
        key_wrapper_window: { has_more_after: false, end_cursor: "key-p1" },
      }) });
    vi.stubGlobal("fetch", fetcher);
    const page = await loadSharedChatDetailsPage("share", "plans");
    expect(page.plans[0].plan_id).toBe("p1");
    expect(page.window.startCursor).toEqual({ timestamp: 100, id: "p1" });
    expect(fetcher.mock.calls[1][0]).toBe("/v1/share/chat/share/auxiliary/plans/p1");
  });
});

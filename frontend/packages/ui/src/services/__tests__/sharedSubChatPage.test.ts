import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../config/api", () => ({ getApiEndpoint: (path: string) => path }));
vi.mock("../../message_parsing/utils", () => ({ computeSHA256: vi.fn() }));
vi.mock("../userPlanService", () => ({ validateUserFlows: vi.fn() }));
vi.mock("../cryptoService", () => ({ decryptWithEmbedKey: vi.fn(), unwrapEmbedKeyWithChatKey: vi.fn() }));
vi.mock("../encryption/ChatKeyManager", () => ({ chatKeyManager: { getKey: vi.fn() } }));

import { loadSharedSubChatPage } from "../sharedChatDetailsService";

const row = (id: string, created_at: number) => ({
  id, created_at, parent_id: "shared-root", is_sub_chat: true, encrypted_title: `cipher-${id}`,
});

afterEach(() => vi.unstubAllGlobals());

describe("shared subchat cursor pages", () => {
  // contract-test: direct surface=gui.web assertions=storage.cold.discoverable-bounded
  it("reads only the requested page and advances the oldest-row cursor", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({
        items: [row("child-2", 200), row("child-3", 300)], has_more_before: true,
        start_cursor: { timestamp: 200, id: "child-2" }, oversized_id: null, payload_bytes: 200,
      }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({
        items: [row("child-1", 100)], has_more_before: false,
        start_cursor: { timestamp: 100, id: "child-1" }, oversized_id: null, payload_bytes: 100,
      }) });
    vi.stubGlobal("fetch", fetcher);
    const newest = await loadSharedSubChatPage("shared-root");
    expect(newest.items.map((item) => item.id)).toEqual(["child-2", "child-3"]);
    expect(newest).toMatchObject({ hasMoreBefore: true, nextCursor: { timestamp: 200, id: "child-2" } });
    expect(fetcher).toHaveBeenCalledTimes(1);
    const older = await loadSharedSubChatPage("shared-root", newest.nextCursor);
    expect(older.items.map((item) => item.id)).toEqual(["child-1"]);
    expect(older.hasMoreBefore).toBe(false);
    expect(fetcher.mock.calls[1][0]).toContain("before_timestamp=200&before_id=child-2");
  });

  // contract-test: direct surface=gui.web assertions=storage.cold.discoverable-bounded
  it("loads one oversized child by exact ID and keeps the next older cursor", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({
        items: [], has_more_before: true, start_cursor: null,
        oversized_id: "child-large", payload_bytes: 0,
      }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ item: row("child-large", 100) }) });
    vi.stubGlobal("fetch", fetcher);
    const page = await loadSharedSubChatPage("shared-root");
    expect(page.items.map((item) => item.id)).toEqual(["child-large"]);
    expect(page.nextCursor).toEqual({ timestamp: 100, id: "child-large" });
    expect(fetcher.mock.calls[1][0]).toBe("/v1/share/chat/shared-root/auxiliary/sub_chats/child-large");
  });

  // contract-test: direct surface=gui.web assertions=storage.cold.discoverable-bounded
  it("rejects repeated cursors and a child from another shared root", async () => {
    const fetcher = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({
        items: [row("child-2", 200)], has_more_before: true,
        start_cursor: { timestamp: 200, id: "child-2" }, oversized_id: null, payload_bytes: 100,
      }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({
        items: [{ ...row("child-1", 100), parent_id: "other-root" }], has_more_before: false,
        start_cursor: { timestamp: 100, id: "child-1" }, oversized_id: null, payload_bytes: 100,
      }) });
    vi.stubGlobal("fetch", fetcher);
    await expect(loadSharedSubChatPage("shared-root", { timestamp: 200, id: "child-2" }))
      .rejects.toThrow(/cursor did not advance/);
    await expect(loadSharedSubChatPage("shared-root")).rejects.toThrow(/invalid bounded metadata/);
  });
});

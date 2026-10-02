import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  deletePendingAppsResult,
  getPendingAppsResult,
  listPendingAppsResults,
  makePendingAppsResultId,
  stagePendingAppsResult,
  type PendingAppsResult,
} from "../appsWorkspaceResultOutbox";

function installIndexedDb(holdCompletions = false) {
  const disk = new Map<string, PendingAppsResult & { teamScope: string }>();
  const closes = vi.fn();
  const transactions: Array<{ oncomplete?: () => void; onabort?: () => void; error: Error | null }> = [];
  const heldCompletions: Array<() => void> = [];
  const objectStore = {
    indexNames: { contains: () => false },
    createIndex: vi.fn(),
  };
  const db = {
    objectStoreNames: { contains: () => false },
    createObjectStore: () => objectStore,
    close: closes,
    transaction: () => {
      let pending = 0;
      let finishing = false;
      const tx: {
        oncomplete?: () => void;
        onerror?: () => void;
        onabort?: () => void;
        error: Error | null;
        abort: () => void;
        objectStore: () => unknown;
      } = {
        error: null,
        abort: vi.fn(),
        objectStore: () => store,
      };
      transactions.push(tx);
      function request<T>(read: () => T): { result?: T; onsuccess?: () => void } {
        pending++;
        const result: { result?: T; onsuccess?: () => void } = {};
        queueMicrotask(() => {
          result.result = read();
          result.onsuccess?.();
          pending--;
          if (!pending && !finishing) {
            finishing = true;
            queueMicrotask(() => {
              finishing = false;
              if (!pending) {
                if (holdCompletions) heldCompletions.push(() => tx.oncomplete?.());
                else tx.oncomplete?.();
              }
            });
          }
        });
        return result;
      }
      const store = {
        put: (row: PendingAppsResult & { teamScope: string }) => request(() => { disk.set(row.id, structuredClone(row)); }),
        get: (id: string) => request(() => structuredClone(disk.get(id))),
        delete: (id: string) => request(() => { disk.delete(id); }),
        index: () => ({ getAll: (range: { value: [string, string] }) => request(() =>
          Array.from(disk.values()).filter((row) => row.userId === range.value[0] && row.teamScope === range.value[1]).map((row) => structuredClone(row)),
        ) }),
      };
      return tx;
    },
  };
  vi.stubGlobal("IDBKeyRange", { only: (value: [string, string]) => ({ value }) });
  vi.stubGlobal("indexedDB", { open: vi.fn(() => {
    const opened: { result: typeof db; transaction: { objectStore: () => typeof objectStore }; onupgradeneeded?: () => void; onsuccess?: () => void } = {
      result: db,
      transaction: { objectStore: () => objectStore },
    };
    queueMicrotask(() => { opened.onupgradeneeded?.(); opened.onsuccess?.(); });
    return opened;
  }) });
  return { disk, closes, transactions, heldCompletions };
}

function pending(userId: string, teamId: string | null, revision: string): PendingAppsResult {
  return {
    id: makePendingAppsResultId(userId, teamId, "root"),
    userId, teamId, rootEmbedId: "root", revision, updatedAt: 123,
    graph: {
      app_id: "web", skill_id: "search", root_embed_id: "root",
      ...(teamId ? { team_id: teamId } : {}),
      embeds: [{ embed_id: "root", encrypted_type: "cipher-type", encrypted_content: "cipher-content", status: "finished" }],
      encrypted_embed_key: "wrapped-key", created_at: 123,
    },
  };
}

describe("Apps result outbox", () => {
  beforeEach(() => vi.unstubAllGlobals());

  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph,apps.library.embeds-account-paginated
  it("persists only ciphertext and scopes reads to the account and team", async () => {
    const { disk, closes } = installIndexedDb();
    const alice = pending("alice", null, "1");
    alice.deferredChildIds = ["child-id"];
    const aliceTeam = pending("alice", "team-1", "1");
    const bob = pending("bob", null, "1");
    (alice.graph.embeds[0] as unknown as Record<string, unknown>).plaintext = "secret content";
    (alice.graph as unknown as Record<string, unknown>).input = "secret input";
    await Promise.all([stagePendingAppsResult(alice), stagePendingAppsResult(aliceTeam), stagePendingAppsResult(bob)]);
    expect(disk.size).toBe(3);
    expect(JSON.stringify(disk.get(alice.id))).not.toContain("secret");
    expect((await getPendingAppsResult("alice", null, "root"))?.deferredChildIds).toEqual(["child-id"]);
    expect((await listPendingAppsResults("alice", null)).map((row) => row.id)).toEqual([alice.id]);
    expect((await listPendingAppsResults("alice", "team-1")).map((row) => row.id)).toEqual([aliceTeam.id]);
    expect(await getPendingAppsResult("bob", null, "root")).toMatchObject({ userId: "bob" });
    expect(await getPendingAppsResult("alice", "team-2", "root")).toBeUndefined();
    expect(closes).toHaveBeenCalledTimes(8);
  });

  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph
  it("keeps a newer revision when an older upload is acknowledged", async () => {
    const { disk } = installIndexedDb();
    const old = pending("alice", null, "processing-1");
    const newer = pending("alice", null, "finished-2");
    await stagePendingAppsResult(old);
    await stagePendingAppsResult(newer);
    await deletePendingAppsResult(old);
    expect(disk.get(old.id)?.revision).toBe("finished-2");
    await deletePendingAppsResult(newer);
    expect(await getPendingAppsResult("alice", null, "root")).toBeUndefined();
  });

  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph,apps.library.embeds-account-paginated
  it("rejects a record whose key or graph has another scope", async () => {
    const { disk } = installIndexedDb();
    const row = pending("alice", "team-1", "1");
    row.id = makePendingAppsResultId("bob", "team-1", "root");
    await expect(stagePendingAppsResult(row)).rejects.toThrow("scope");
    expect(disk.size).toBe(0);
  });

  // contract-test: supporting surface=gui.web assertions=apps.results.web-retained-graph
  it("reports a durable write only after commit and rejects an abort", async () => {
    const { closes, transactions, heldCompletions } = installIndexedDb(true);
    let settled = false;
    const write = stagePendingAppsResult(pending("alice", null, "1")).then(() => { settled = true; });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(heldCompletions).toHaveLength(1);
    expect(settled).toBe(false);
    heldCompletions.shift()?.();
    await write;
    expect(settled).toBe(true);
    expect(closes).toHaveBeenCalledTimes(1);

    const aborted = stagePendingAppsResult(pending("alice", null, "2"));
    await new Promise((resolve) => setTimeout(resolve, 0));
    const tx = transactions[transactions.length - 1]!;
    tx.error = new Error("disk unavailable");
    tx.onabort?.();
    await expect(aborted).rejects.toThrow("disk unavailable");
    expect(closes).toHaveBeenCalledTimes(2);
  });
});

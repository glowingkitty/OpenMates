import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  rows: [] as Array<Record<string, unknown>>,
  read: vi.fn(),
  sent: vi.fn(),
}));

vi.mock("../db", () => ({ chatDB: {
  getChat: vi.fn(async () => ({ chat_id: "chat-1", team_id: null })),
} }));
vi.mock("../embedDiffStore", () => ({
  getEmbedDiffs: vi.fn(async () => [...state.rows]),
  storeEmbedDiff: vi.fn(async (row: Record<string, unknown>) => {
    const index = state.rows.findIndex((item) => item.version_number === row.version_number);
    if (index >= 0) state.rows[index] = row;
    else state.rows.push(row);
  }),
}));
vi.mock("../encryption/MetadataEncryptor", () => ({
  encryptWithEmbedKey: vi.fn(async (plain: string) => `cipher:${plain}`),
  decryptWithEmbedKey: vi.fn(async (cipher: string) => cipher.startsWith("cipher:") ? cipher.slice(7) : null),
}));
vi.mock("../chatSyncServiceSenders", () => ({ sendStoreEmbedDiffImpl: state.sent }));
vi.mock("../../config/api", () => ({
  getApiEndpoint: (path: string) => `https://api.test${path}`,
  storageArchiveFetch: state.read,
}));

import { persistClientEncryptedEmbedDiffRows } from "../streamedEmbedRevisionHistory";

const history = { embed_id: "embed-1", chat_id: "chat-1", version_history_rows: [
  { embed_id: "embed-1", version_number: 2, patch: "patch-v2", created_at: 10 },
  { embed_id: "embed-1", version_number: 3, patch: "patch-v3", created_at: 11 },
] } as unknown as Parameters<typeof persistClientEncryptedEmbedDiffRows>[1];
const service = { webSocketConnected_FOR_SENDERS_ONLY: true } as Parameters<typeof persistClientEncryptedEmbedDiffRows>[0];
const key = new Uint8Array([1, 2]);

describe("streamed next-revision history", () => {
  beforeEach(() => { state.rows.length = 0; state.read.mockReset(); state.sent.mockReset(); });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted
  it("creates ordinary v1 history only when the canonical snapshot is missing", async () => {
    state.read.mockResolvedValue({ ok: false, status: 409, json: async () => ({ detail: "snapshot_required" }) });
    await persistClientEncryptedEmbedDiffRows(service, {
      ...history, version_history_rows: [{ embed_id: "embed-1", version_number: 1,
        snapshot: "initial", created_at: 1 }],
    }, key, "owner-hash");
    expect(state.sent).toHaveBeenCalledTimes(1);
    expect(state.read).toHaveBeenCalledTimes(1);
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,storage.versions.bounded-reconstruction
  it("adopts an equivalent canonical v1 after a competing encrypted write", async () => {
    state.read.mockResolvedValueOnce({ ok: false, status: 409, json: async () => ({ detail: "snapshot_required" }) });
    state.sent.mockRejectedValueOnce(Object.assign(new Error("competing version"), { code: "embed_diff_conflict" }));
    state.read.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({
      embed_id: "embed-1", version_number: 1, rows: [{ version_number: 1,
        encrypted_snapshot: "cipher:initial", encrypted_patch: null, created_at: 1 }],
    }) });
    await persistClientEncryptedEmbedDiffRows(service, { ...history, version_history_rows: [
      { embed_id: "embed-1", version_number: 1, snapshot: "initial", created_at: 1 },
    ] }, key, "owner-hash");
    expect(state.sent).toHaveBeenCalledTimes(1);
    expect(state.rows[0].encrypted_snapshot).toBe("cipher:initial");
  });

  // contract-test: direct surface=gui.web assertions=chats.persistence.client-encrypted,storage.versions.bounded-reconstruction
  it("rejects a different canonical v1 instead of overwriting immutable history", async () => {
    state.read.mockResolvedValue({ ok: true, status: 200, json: async () => ({
      embed_id: "embed-1", version_number: 1, rows: [{ version_number: 1,
        encrypted_snapshot: "cipher:different", encrypted_patch: null }],
    }) });
    await expect(persistClientEncryptedEmbedDiffRows(service, { ...history, version_history_rows: [
      { embed_id: "embed-1", version_number: 1, snapshot: "initial", created_at: 1 },
    ] }, key, "owner-hash")).rejects.toThrow("Canonical revision history differs");
    expect(state.sent).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("retains v3 history locally without a premature immutable server write", async () => {
    await persistClientEncryptedEmbedDiffRows(service, history, key, "owner-hash", true, false);
    expect(state.rows.map((row) => row.version_number)).toEqual([2, 3]);
    expect(state.sent).not.toHaveBeenCalled();
    expect(state.read).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery,chats.persistence.client-encrypted
  it("reuses scoped canonical v3 history only after matching plaintext", async () => {
    state.read.mockResolvedValue({ ok: true, status: 200, json: async () => ({
      embed_id: "embed-1", version_number: 3, rows: [
        { version_number: 2, encrypted_patch: "cipher:patch-v2" },
        { version_number: 3, encrypted_patch: "cipher:patch-v3" },
      ],
    }) });
    await persistClientEncryptedEmbedDiffRows(service, history, key, "owner-hash", true, true);
    expect(state.read).toHaveBeenCalledWith(expect.stringContaining("/versions/3?"), { credentials: "include" });
    expect(state.rows).toHaveLength(2);
    expect(state.sent).not.toHaveBeenCalled();
  });

  // contract-test: direct surface=gui.web assertions=storage.background.complete-sealed-recovery
  it("keeps local v3 history pending when canonical rows are absent or differ", async () => {
    state.read.mockResolvedValueOnce({ ok: false, status: 404 });
    await persistClientEncryptedEmbedDiffRows(service, history, key, "owner-hash", true, true);
    expect(state.rows).toHaveLength(2);
    state.read.mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({
      embed_id: "embed-1", version_number: 3, rows: [
        { version_number: 2, encrypted_patch: "cipher:patch-v2" },
        { version_number: 3, encrypted_patch: "cipher:different" },
      ],
    }) });
    await expect(persistClientEncryptedEmbedDiffRows(service, history, key, "owner-hash", true, true))
      .rejects.toThrow("Canonical revision history differs");
    expect(state.rows).toHaveLength(2);
    expect(state.sent).not.toHaveBeenCalled();
  });
});

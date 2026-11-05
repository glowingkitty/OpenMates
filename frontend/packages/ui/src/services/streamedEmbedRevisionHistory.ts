/** Preserve ordinary streamed version rows while sealed recovery owns canonical writes. */
import type { ChatSynchronizationService } from "./chatSyncService";
import type { SendEmbedDataPayload } from "../types/chat";
import { chatDB } from "./db";
import { encryptWithEmbedKey, decryptWithEmbedKey } from "./encryption/MetadataEncryptor";
import { normalizeToUnixSeconds } from "./timestampUtils";

export async function persistClientEncryptedEmbedDiffRows(
  serviceInstance: ChatSynchronizationService,
  embedData: SendEmbedDataPayload["payload"],
  embedKey: Uint8Array,
  hashedUserId: string,
  sealedRootRevision: boolean = false,
  durableHead: boolean = true,
): Promise<void> {
  const rows = embedData.version_history_rows;
  if (!Array.isArray(rows) || rows.length === 0) return;

  const { storeEmbedDiff, getEmbedDiffs } = await import("./embedDiffStore");
  const localRows = sealedRootRevision ? await getEmbedDiffs(embedData.embed_id) : [];
  const existingByVersion = new Map(localRows.map((row) => [row.version_number, row]));
  const samePlaintext = async (ciphertext: string | null | undefined, expected: string | null): Promise<boolean> => {
    if (expected === null) return ciphertext == null;
    if (typeof ciphertext !== "string") return false;
    const plaintext = await decryptWithEmbedKey(ciphertext, embedKey);
    return plaintext !== null && plaintext === expected;
  };
  const adoptCanonicalRow = async (version: number, snapshot: string | null, patch: string | null): Promise<boolean> => {
    const chat = await chatDB.getChat(embedData.chat_id);
    const query = new URLSearchParams({ capability: "bounded-v1", chat_id: embedData.chat_id });
    if (chat?.team_id) query.set("team_id", chat.team_id);
    const { getApiEndpoint, storageArchiveFetch } = await import("../config/api");
    const response = await storageArchiveFetch(getApiEndpoint(
      `/v1/embeds/${encodeURIComponent(embedData.embed_id)}/versions/${version}?${query}`,
    ), { credentials: "include" });
    if (response.status === 404) return false;
    if (response.status === 409) {
      const error = await response.json();
      if (version === 1 && error?.detail === "snapshot_required") return false;
    }
    if (!response.ok) throw new Error(`Canonical revision history read failed (${response.status}).`);
    const page = await response.json();
    if (page.embed_id !== embedData.embed_id || page.version_number !== version || !Array.isArray(page.rows)) {
      throw new Error("Canonical revision history identity changed.");
    }
    const matching = page.rows.filter((row: { version_number?: number }) => row.version_number === version);
    if (matching.length !== 1 || !await samePlaintext(matching[0].encrypted_snapshot, snapshot)
      || !await samePlaintext(matching[0].encrypted_patch, patch)) {
      throw new Error("Canonical revision history differs from streamed output.");
    }
    await storeEmbedDiff({
      id: `${embedData.embed_id}_v${version}`, embed_id: embedData.embed_id, version_number: version,
      encrypted_snapshot: matching[0].encrypted_snapshot ?? undefined,
      encrypted_patch: matching[0].encrypted_patch ?? undefined,
      created_at: normalizeToUnixSeconds(matching[0].created_at, Math.floor(Date.now() / 1000)),
    });
    return true;
  };
  const seenVersions = new Set<number>();
  let sendStoreEmbedDiffFunction: typeof import("./chatSyncServiceSenders").sendStoreEmbedDiffImpl | undefined;
  if (!sealedRootRevision) {
    const sendersModule = await import("./chatSyncServiceSenders");
    sendStoreEmbedDiffFunction = sendersModule.sendStoreEmbedDiffImpl ||
      (sendersModule as { default?: { sendStoreEmbedDiffImpl?: typeof sendersModule.sendStoreEmbedDiffImpl } })
        .default?.sendStoreEmbedDiffImpl;
    if (typeof sendStoreEmbedDiffFunction !== "function") {
      throw new Error("sendStoreEmbedDiffImpl function not found");
    }
  }

  for (const row of rows) {
    if (sealedRootRevision) {
      if (row.embed_id !== embedData.embed_id || !Number.isSafeInteger(row.version_number)
        || row.version_number < 1 || row.version_number > Number(embedData.version_number)
        || seenVersions.has(row.version_number)) {
        throw new Error("Streamed revision history identity or order changed.");
      }
      seenVersions.add(row.version_number);
    }
    if (!row.embed_id || typeof row.version_number !== "number") continue;
    const expectedSnapshot = typeof row.snapshot === "string" ? row.snapshot : null;
    const expectedPatch = typeof row.patch === "string" ? row.patch : null;
    if (sealedRootRevision) {
      const existing = existingByVersion.get(row.version_number);
      if (existing && (!await samePlaintext(existing.encrypted_snapshot, expectedSnapshot)
        || !await samePlaintext(existing.encrypted_patch, expectedPatch))) {
        throw new Error("Local revision history differs from streamed recovery history.");
      }
      const encryptedSnapshot = existing?.encrypted_snapshot
        ?? (expectedSnapshot ? await encryptWithEmbedKey(expectedSnapshot, embedKey) : undefined);
      const encryptedPatch = existing?.encrypted_patch
        ?? (expectedPatch ? await encryptWithEmbedKey(expectedPatch, embedKey) : undefined);
      if (!encryptedSnapshot && !encryptedPatch) continue;
      await storeEmbedDiff({
        id: `${row.embed_id}_v${row.version_number}`,
        embed_id: row.embed_id, version_number: row.version_number,
        encrypted_snapshot: encryptedSnapshot ?? undefined,
        encrypted_patch: encryptedPatch ?? undefined,
        created_at: normalizeToUnixSeconds(row.created_at, Math.floor(Date.now() / 1000)),
      });
      // Typed sealed recovery owns the immutable server version row and ACK.
      continue;
    }
    if (await adoptCanonicalRow(row.version_number, expectedSnapshot, expectedPatch)) continue;
    const encryptedSnapshot =
      typeof row.snapshot === "string"
        ? await encryptWithEmbedKey(row.snapshot, embedKey)
        : undefined;
    const encryptedPatch =
      typeof row.patch === "string"
        ? await encryptWithEmbedKey(row.patch, embedKey)
        : undefined;
    if (!encryptedSnapshot && !encryptedPatch) continue;

    const createdAt = normalizeToUnixSeconds(
      row.created_at,
      Math.floor(Date.now() / 1000),
    );
    const encryptedRow = {
      id: `${row.embed_id}_v${row.version_number}`,
      embed_id: row.embed_id,
      version_number: row.version_number,
      encrypted_snapshot: encryptedSnapshot,
      encrypted_patch: encryptedPatch,
      created_at: createdAt,
    };

    await storeEmbedDiff(encryptedRow);
    try {
      await sendStoreEmbedDiffFunction!(serviceInstance, {
        embed_id: row.embed_id, version_number: row.version_number,
        encrypted_snapshot: encryptedSnapshot ?? null, encrypted_patch: encryptedPatch ?? null,
        hashed_user_id: hashedUserId, created_at: createdAt,
      });
    } catch (error) {
      if (!(error instanceof Error) || (error as Error & { code?: string }).code !== "embed_diff_conflict"
        || !await adoptCanonicalRow(row.version_number, expectedSnapshot, expectedPatch)) throw error;
    }
  }
  if (sealedRootRevision && durableHead) {
    const expectedRows = rows.filter((row) => row.embed_id === embedData.embed_id
      && Number.isInteger(row.version_number) && row.version_number > 0);
    if (expectedRows.length === 0) return;
    const maxVersion = Math.max(...expectedRows.map((row) => row.version_number));
    const chat = await chatDB.getChat(embedData.chat_id);
    const query = new URLSearchParams({ capability: "bounded-v1", chat_id: embedData.chat_id });
    if (chat?.team_id) query.set("team_id", chat.team_id);
    const { getApiEndpoint, storageArchiveFetch } = await import("../config/api");
    const response = await storageArchiveFetch(getApiEndpoint(
      `/v1/embeds/${encodeURIComponent(embedData.embed_id)}/versions/${maxVersion}?${query}`,
    ), { credentials: "include" });
    if (response.status === 404 || response.status === 409) return; // Sealed diff recovery remains pending.
    if (!response.ok) throw new Error(`Canonical revision history read failed (${response.status}).`);
    const page = await response.json() as {
      embed_id?: string; version_number?: number;
      rows?: Array<{ version_number: number; encrypted_snapshot?: string | null; encrypted_patch?: string | null }>;
    };
    if (page.embed_id !== embedData.embed_id || page.version_number !== maxVersion
      || !Array.isArray(page.rows)) throw new Error("Canonical revision history identity changed.");
    const canonicalRows = new Map(page.rows.map((row) => [row.version_number, row]));
    if (canonicalRows.size !== page.rows.length) throw new Error("Canonical revision history is ambiguous.");
    for (const row of expectedRows) {
      const canonical = canonicalRows.get(row.version_number);
      if (!canonical || !await samePlaintext(canonical.encrypted_snapshot,
        typeof row.snapshot === "string" ? row.snapshot : null)
        || !await samePlaintext(canonical.encrypted_patch,
          typeof row.patch === "string" ? row.patch : null)) {
        throw new Error("Canonical revision history differs from streamed recovery history.");
      }
      await storeEmbedDiff({
        id: `${row.embed_id}_v${row.version_number}`, embed_id: row.embed_id,
        version_number: row.version_number,
        encrypted_snapshot: canonical.encrypted_snapshot ?? undefined,
        encrypted_patch: canonical.encrypted_patch ?? undefined,
        created_at: normalizeToUnixSeconds(row.created_at, Math.floor(Date.now() / 1000)),
      });
    }
  }
}

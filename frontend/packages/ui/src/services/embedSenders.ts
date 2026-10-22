import type { ChatSynchronizationService } from "./chatSyncService";
import { webSocketService } from "./websocketService";
import type { Chat, StoreEmbedDiffPayload, StoreEmbedPayload } from "../types/chat";
import type { EmbedType } from "../message_parsing/types";
import { chatDB, type PendingEmbedOperation } from "./db";
import { computeSHA256 } from "../message_parsing/utils";
import { getApiEndpoint, storageArchiveFetch } from "../config/api";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import {
  decryptWithEmbedKey, unwrapEmbedKeyWithChatKey, unwrapEmbedKeyWithMasterKey,
} from "./encryption/MetadataEncryptor";
import {
  assertCanonicalEmbedWriteLease, withCanonicalEmbedWrite,
  type CanonicalEmbedWriteLease,
} from "./canonicalEmbedWriteCoordinator";

const EMBED_RECEIPT_TIMEOUT_MS = 30_000;
const MAX_ACTIVE_EMBED_RECEIPTS = 32;
const activePendingEmbedOperations = new Map<string, Promise<void>>();
const persistenceChatIds = new Map<string, string>();
const MAX_PERSISTENCE_CHAT_IDS = 128;
let pendingEmbedFlush: Promise<void> | null = null;
let lastPendingEmbedOperationTime = 0;
let capacityDeferred = false;
let capacityDrainScheduled = false;

class CanonicalEmbedWriteRejected extends Error {
  constructor(readonly code: string) {
    super(`Canonical embed write was rejected (${code}).`);
  }
}

class CanonicalEmbedRecoveryPending extends Error {
  constructor() {
    super("Sealed revision recovery must publish the canonical head before queued reconciliation.");
  }
}

function scheduleCapacityDrain(): void {
  if (!capacityDeferred || capacityDrainScheduled) return;
  capacityDeferred = false;
  capacityDrainScheduled = true;
  globalThis.setTimeout(() => {
    capacityDrainScheduled = false;
    void flushPendingEmbedOperations();
  }, 0);
}

async function sendWithReceipt(
  type: "store_embed" | "store_embed_keys",
  confirmedType: "store_embed_confirmed" | "store_embed_keys_confirmed",
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const requestId = crypto.randomUUID();
  let stop = () => {};
  const confirmation = new Promise<Record<string, unknown>>((resolve, reject) => {
    const timer = globalThis.setTimeout(() => {
      stop();
      reject(new Error(`Canonical ${type} confirmation timed out.`));
    }, EMBED_RECEIPT_TIMEOUT_MS);
    const onConfirmed = (raw: unknown) => {
      const receipt = raw as Record<string, unknown>;
      if (receipt.request_id !== requestId) return;
      stop();
      resolve(receipt);
    };
    const onClose = () => {
      stop();
      reject(new Error(`Connection closed before canonical ${type} confirmation.`));
    };
    const onError = (raw: unknown) => {
      const error = raw as Record<string, unknown>;
      if (error.request_id !== requestId || typeof error.code !== "string") return;
      stop();
      reject(new CanonicalEmbedWriteRejected(error.code));
    };
    stop = () => {
      globalThis.clearTimeout(timer);
      webSocketService.off(confirmedType, onConfirmed);
      webSocketService.off("error", onError);
      webSocketService.removeEventListener("close", onClose);
    };
    webSocketService.on(confirmedType, onConfirmed);
    webSocketService.on("error", onError);
    webSocketService.addEventListener("close", onClose);
  });
  void confirmation.catch(() => {});
  try {
    await webSocketService.sendMessage(type, { ...payload, request_id: requestId });
    return await confirmation;
  } finally {
    stop();
  }
}

/** Prove that a queued re-encrypted write is the already sealed head. */
async function readEquivalentCanonicalHead(head: StoreEmbedPayload, historical = false): Promise<{
  embed: Record<string, unknown>; type: string; content: string;
  queuedContent: string; key: Uint8Array; keySubject: string; verifiedKeyTypes: Set<string>;
}> {
  if (!head.chat_id || !head.hashed_chat_id || !head.hashed_user_id) {
    throw new Error("Canonical embed chat and owner scope are unavailable.");
  }
  const chat = await chatDB.getRawChat(head.chat_id);
  if (!chat || await computeSHA256(chat.chat_id) !== head.hashed_chat_id
    || (head.team_id ?? null) !== (chat.team_id ?? null)) {
    throw new Error("Canonical embed chat scope changed.");
  }
  const query = chat.team_id ? `?team_id=${encodeURIComponent(chat.team_id)}` : "";
  const response = await storageArchiveFetch(getApiEndpoint(
    `/v1/embeds/chats/${encodeURIComponent(head.chat_id)}/embeds/${encodeURIComponent(head.embed_id)}${query}`,
  ), { credentials: "include" });
  if (!response.ok) throw new Error(`Canonical embed head read failed (${response.status}).`);
  const page = await response.json() as {
    embed?: Record<string, unknown>; embed_keys?: Array<Record<string, unknown>>;
    embed_keys_has_more_after?: boolean; oversized_embed_key_id?: string | null;
  };
  const embed = page.embed;
  const same = (value: unknown, expected: unknown) => value === expected;
  if (!embed || !same(embed.embed_id, head.embed_id)
    || !same(embed.hashed_chat_id, head.hashed_chat_id)
    || !same(embed.hashed_user_id, head.hashed_user_id)
    || !same(embed.hashed_message_id, head.hashed_message_id)
    || !same(embed.parent_embed_id ?? null, head.parent_embed_id ?? null)
    || (historical
      ? Number(embed.version_number ?? 1) <= Number(head.version_number ?? 1)
      : !same(Number(embed.version_number ?? 1), head.version_number ?? 1))
    || (!historical && !same(embed.status, head.status))
    || (head.app_id !== undefined && !same(embed.app_id, head.app_id))
    || (head.skill_id !== undefined && !same(embed.skill_id, head.skill_id))
    || (!historical && head.hashed_task_id !== undefined && !same(embed.hashed_task_id, head.hashed_task_id))
    || (!historical && head.embed_ids !== undefined
      && JSON.stringify(embed.embed_ids ?? []) !== JSON.stringify(head.embed_ids ?? []))
    || (!historical && head.is_private !== undefined && !same(embed.is_private, head.is_private))
    || (!historical && head.is_shared !== undefined && !same(embed.is_shared, head.is_shared))
    || typeof embed.encrypted_content !== "string" || typeof embed.encrypted_type !== "string") {
    throw new Error("Canonical embed identity or version differs; use a versioned edit.");
  }
  if (page.embed_keys_has_more_after || page.oversized_embed_key_id
    || !Array.isArray(page.embed_keys) || page.embed_keys.length > 128) {
    throw new Error("Canonical embed key wrappers are incomplete.");
  }
  const { embedStore } = await import("./embedStore");
  const key = await embedStore.getEmbedKey(head.embed_id, head.hashed_chat_id);
  if (!key) throw new Error("Canonical embed key is unavailable.");
  const keySubject = head.parent_embed_id || head.embed_id;
  const hashedSubject = await computeSHA256(keySubject);
  const verifiedKeyTypes = new Set<string>();
  for (const wrapper of page.embed_keys) {
    // Other authorized key scopes are not evidence that this owner's queued
    // master/chat wrapper already exists. Validate every row we would reuse.
    if (wrapper.hashed_embed_id !== hashedSubject
      || wrapper.hashed_user_id !== head.hashed_user_id
      || (wrapper.key_type !== "master" && wrapper.key_type !== "chat")) continue;
    if (typeof wrapper.encrypted_embed_key !== "string"
      || (wrapper.key_type === "master" ? wrapper.hashed_chat_id != null
        : wrapper.hashed_chat_id !== head.hashed_chat_id)
      || ["hashed_project_id", "hashed_plan_id", "hashed_team_id", "team_key_epoch"]
        .some((field) => wrapper[field] != null)) {
      throw new Error("Canonical embed key wrapper identity was invalid.");
    }
    let unwrapped: Uint8Array | null = null;
    if (wrapper.key_type === "master") {
      unwrapped = await unwrapEmbedKeyWithMasterKey(wrapper.encrypted_embed_key, keySubject);
    } else {
      const chatKey = await chatKeyManager.getKey(head.chat_id);
      if (chatKey) unwrapped = await unwrapEmbedKeyWithChatKey(wrapper.encrypted_embed_key, chatKey, {
        embedId: keySubject, chatId: head.chat_id,
      });
    }
    if (!unwrapped || unwrapped.length !== key.length
      || unwrapped.some((byte, index) => byte !== key[index])) {
      throw new Error("Canonical embed key wrapper did not match the local key.");
    }
    // Historical wrappers may use different nonces for the same key. Verify
    // every row before deduplicating types; never rotate canonical ciphertext.
    verifiedKeyTypes.add(wrapper.key_type);
  }
  if (verifiedKeyTypes.size === 0) throw new Error("Canonical embed key wrapper did not match the local key.");
  const [queuedContent, canonicalContent, queuedType, canonicalType] = await Promise.all([
    decryptWithEmbedKey(head.encrypted_content, key),
    decryptWithEmbedKey(embed.encrypted_content, key),
    decryptWithEmbedKey(head.encrypted_type, key),
    decryptWithEmbedKey(embed.encrypted_type, key),
  ]);
  if (queuedContent === null || queuedType === null
    || canonicalContent === null || (!historical && queuedContent !== canonicalContent)
    || queuedType !== canonicalType) {
    throw new Error("Canonical embed content or type differs; use a versioned edit.");
  }
  const queuedPreview = head.encrypted_text_preview;
  const canonicalPreview = embed.encrypted_text_preview;
  if (!historical && (queuedPreview != null || canonicalPreview != null)) {
    if (typeof queuedPreview !== "string" || typeof canonicalPreview !== "string") {
      throw new Error("Canonical embed preview differs; use a versioned edit.");
    }
    const [queuedText, canonicalText] = await Promise.all([
      decryptWithEmbedKey(queuedPreview, key),
      decryptWithEmbedKey(canonicalPreview, key),
    ]);
    if (queuedText === null || canonicalText === null || queuedText !== canonicalText) {
      throw new Error("Canonical embed preview differs; use a versioned edit.");
    }
  }
  return { embed, type: canonicalType, content: canonicalContent,
    queuedContent, key, keySubject, verifiedKeyTypes };
}

/** Reconcile an old queued root only against its authenticated historical source. */
async function readEquivalentHistoricalHead(
  head: StoreEmbedPayload,
): Promise<Awaited<ReturnType<typeof readEquivalentCanonicalHead>>> {
  const canonical = await readEquivalentCanonicalHead(head, true);
  const chat = await chatDB.getRawChat(head.chat_id!);
  if (!chat || (chat.team_id ?? null) !== (head.team_id ?? null)) {
    throw new Error("Historical embed chat scope changed.");
  }
  const query = new URLSearchParams({ capability: "bounded-v1", chat_id: head.chat_id! });
  if (chat.team_id) query.set("team_id", chat.team_id);
  const response = await storageArchiveFetch(getApiEndpoint(
    `/v1/embeds/${encodeURIComponent(head.embed_id)}/versions/${head.version_number ?? 1}?${query}`,
  ), { credentials: "include" });
  if (!response.ok) throw new Error(`Historical embed version read failed (${response.status}).`);
  const page = await response.json() as {
    embed_id?: string; version_number?: number;
    rows?: Array<{ version_number: number; encrypted_snapshot?: string | null; encrypted_patch?: string | null }>;
  };
  if (page.embed_id !== head.embed_id || page.version_number !== (head.version_number ?? 1)
    || !Array.isArray(page.rows)
    || page.rows[page.rows.length - 1]?.version_number !== (head.version_number ?? 1)) {
    throw new Error("Historical embed version identity changed.");
  }
  const [{ reconstructEncryptedVersionRows }, { historySourceFromSealedEmbed }] = await Promise.all([
    import("./embedDiffStore"), import("./recoveryEmbedSource"),
  ]);
  const source = await historySourceFromSealedEmbed(canonical.queuedContent, canonical.type);
  const reconstructionRows = page.rows.map((row) => ({ ...row,
    created_at: 0, has_snapshot: !!row.encrypted_snapshot, has_patch: !!row.encrypted_patch,
  }));
  if (await reconstructEncryptedVersionRows(reconstructionRows, canonical.key) !== source) {
    throw new Error("Historical embed source differs from the queued revision.");
  }
  return canonical;
}

/** A queued wrapper must not rotate an already canonical head to a different key. */
async function verifyQueuedWrappersForCanonicalHead(
  head: StoreEmbedPayload, keys: Array<Record<string, unknown>>,
  canonical: Awaited<ReturnType<typeof readEquivalentCanonicalHead>>,
): Promise<void> {
  const hashedSubject = await computeSHA256(canonical.keySubject);
  for (const wrapper of keys) {
    if (wrapper.hashed_embed_id !== hashedSubject
      || wrapper.hashed_user_id !== head.hashed_user_id
      || typeof wrapper.encrypted_embed_key !== "string") {
      throw new Error("Queued embed wrapper identity differs from the canonical head.");
    }
    let unwrapped: Uint8Array | null = null;
    if (wrapper.key_type === "master" && wrapper.hashed_chat_id == null) {
      unwrapped = await unwrapEmbedKeyWithMasterKey(wrapper.encrypted_embed_key, canonical.keySubject);
    } else if (wrapper.key_type === "chat" && wrapper.hashed_chat_id === head.hashed_chat_id) {
      const chatKey = await chatKeyManager.getKey(head.chat_id!);
      if (chatKey) unwrapped = await unwrapEmbedKeyWithChatKey(wrapper.encrypted_embed_key, chatKey, {
        embedId: canonical.keySubject, chatId: head.chat_id,
      });
    }
    if (!unwrapped || unwrapped.length !== canonical.key.length
      || unwrapped.some((byte, index) => byte !== canonical.key[index])) {
      throw new Error("Queued embed wrapper would rotate the canonical head key.");
    }
  }
}

/** Restore authorization context omitted by legacy preview updates and queued writes. */
async function resolveEmbedPersistenceContext(payload: StoreEmbedPayload): Promise<StoreEmbedPayload> {
  if (!payload.hashed_chat_id || (payload.app_id && payload.skill_id && payload.chat_id)) {
    return payload;
  }
  const { embedStore } = await import("./embedStore");
  const contentRef = `embed:${payload.embed_id}`;
  const entry = await embedStore.getRawEntry(contentRef);
  let appId = payload.app_id ?? entry?.app_id;
  let skillId = payload.skill_id ?? entry?.skill_id;
  if (!appId || !skillId) {
    // Older sync paths omitted the local catalog projection. Recover it from
    // already encrypted local content without changing the outgoing ciphertext.
    const catalog = await embedStore.getCatalogContext(contentRef);
    appId ??= catalog?.app_id;
    skillId ??= catalog?.skill_id;
    if (!catalog && entry?.has_encrypted_content && (!appId || !skillId)) {
      throw new Error("Embed catalog context is not ready; operation remains queued for retry.");
    }
  }
  // Older non-catalog embeds retain their original persistence protocol.
  if (!appId && !skillId) return payload;
  if (!appId || !skillId) {
    throw new Error("Embed catalog context is not ready; operation remains queued for retry.");
  }
  const withChatContext = (chat: Pick<Chat, "chat_id" | "team_id">): StoreEmbedPayload => ({
    ...payload,
    app_id: appId,
    skill_id: skillId,
    chat_id: payload.chat_id ?? chat.chat_id,
    team_id: payload.team_id !== undefined ? payload.team_id : chat.team_id ?? null,
  });
  const cachedChatId = persistenceChatIds.get(payload.hashed_chat_id);
  if (cachedChatId) {
    // Cache only identity; re-read current Team context for every write.
    const chat = await chatDB.getRawChat(cachedChatId);
    if (chat) return withChatContext(chat);
    persistenceChatIds.delete(payload.hashed_chat_id);
  }
  let afterChatId: string | null = null;
  do {
    // Routing fields are available without decrypting titles or unwrapping keys.
    const page = await chatDB.getChatsPage(afterChatId);
    for (const chat of page.items) {
      if (await computeSHA256(chat.chat_id) !== payload.hashed_chat_id) continue;
      if (persistenceChatIds.size >= MAX_PERSISTENCE_CHAT_IDS) {
        const oldest = persistenceChatIds.keys().next().value;
        if (oldest) persistenceChatIds.delete(oldest);
      }
      persistenceChatIds.set(payload.hashed_chat_id, chat.chat_id);
      return withChatContext(chat);
    }
    afterChatId = page.nextAfter;
  } while (afterChatId !== null);
  throw new Error("Embed chat context is not ready; operation remains queued for retry.");
}

async function persistCanonicalEmbedOperation(operation: PendingEmbedOperation): Promise<void> {
  const head = await resolveEmbedPersistenceContext(operation.store_embed_payload);
  const requestedVersion = Number(head.version_number ?? 1);
  if (!Number.isSafeInteger(requestedVersion) || requestedVersion < 1) {
    throw new Error("Queued embed revision is invalid.");
  }
  let canonical: Awaited<ReturnType<typeof readEquivalentCanonicalHead>> | null = null;
  // Compare every readable revision before writing, including v1 and children.
  // Fresh encryption of an already acknowledged revision is correctly rejected
  // by storage. A child awaiting its parent must remain queued, not reciphered.
  {
    if (!head.chat_id || !head.hashed_chat_id || !head.hashed_user_id) {
      throw new Error("Canonical embed chat and owner scope are unavailable.");
    }
    const chat = await chatDB.getRawChat(head.chat_id);
    if (!chat || await computeSHA256(chat.chat_id) !== head.hashed_chat_id
      || (chat.team_id ?? null) !== (head.team_id ?? null)) {
      throw new Error("Canonical embed chat scope changed.");
    }
    const query = chat.team_id ? `?team_id=${encodeURIComponent(chat.team_id)}` : "";
    const availability = await fetch(getApiEndpoint(
      `/v1/embeds/chats/${encodeURIComponent(head.chat_id)}/references/availability${query}`,
    ), {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        embed_ids: head.parent_embed_id ? [head.embed_id, head.parent_embed_id] : [head.embed_id],
        required_recovery_versions: { [head.embed_id]: requestedVersion },
      }),
    });
    if (!availability.ok) {
      throw new Error(`Canonical embed availability failed (${availability.status}).`);
    }
    const result = await availability.json() as {
      results?: Array<{ embed_id?: string; state?: string;
        recovery_ack?: { state?: string; version?: number; canonical_digest?: string } }>;
    };
    if (!Array.isArray(result.results) || result.results.length !== (head.parent_embed_id ? 2 : 1)
      || result.results[0].embed_id !== head.embed_id
      || (head.parent_embed_id && result.results[1].embed_id !== head.parent_embed_id)) {
      throw new Error("Canonical embed availability identity changed.");
    }
    const ack = result.results[0].recovery_ack;
    if (ack && (ack.state !== "ACKNOWLEDGED" || ack.version !== requestedVersion
      || typeof ack.canonical_digest !== "string" || !/^[0-9a-f]{64}$/.test(ack.canonical_digest))) {
      throw new Error("Canonical embed acknowledgement identity changed.");
    }
    const parentReady = !head.parent_embed_id || result.results[1].state === "ready";
    if (result.results[0].state === "missing") {
      if (requestedVersion > 1) throw new CanonicalEmbedRecoveryPending();
    } else if (requestedVersion === 1 && parentReady && result.results[0].state === "unusable") {
      // A processing child may finish once its scoped parent is readable.
    } else {
      if (result.results[0].state !== "ready") {
        throw new Error("Canonical embed is unavailable; queued revision remains pending.");
      }
      const response = await storageArchiveFetch(getApiEndpoint(
        `/v1/embeds/chats/${encodeURIComponent(head.chat_id)}/embeds/${encodeURIComponent(head.embed_id)}${query}`,
      ), { credentials: "include" });
      if (!response.ok) throw new Error(`Canonical embed head read failed (${response.status}).`);
      const page = await response.json() as { embed?: Record<string, unknown> };
      const prior = page.embed;
      if (!prior || prior.embed_id !== head.embed_id
        || prior.hashed_chat_id !== head.hashed_chat_id
        || prior.hashed_user_id !== head.hashed_user_id
        || (prior.parent_embed_id ?? null) !== (head.parent_embed_id ?? null)) {
        throw new Error("Canonical embed identity differs; queued revision remains pending.");
      }
      const currentVersion = Number(prior.version_number ?? 1);
      if (currentVersion === requestedVersion - 1) throw new CanonicalEmbedRecoveryPending();
      if (currentVersion > requestedVersion) {
        canonical = await readEquivalentHistoricalHead(head);
      } else if (currentVersion !== requestedVersion) {
        throw new Error("Canonical embed revision differs; queued revision remains pending.");
      } else if (requestedVersion > 1 || head.parent_embed_id || ack) {
        canonical = await readEquivalentCanonicalHead(head);
      }
      // An unacknowledged v1 root can still accept a legacy preview update.
      // Check its version first so an old queue cannot regress a newer head.
    }
  }
  if (!canonical) try {
    const headReceipt = await sendWithReceipt("store_embed", "store_embed_confirmed", head as unknown as Record<string, unknown>);
    const expectedDigest = await computeSHA256(head.encrypted_content);
    if (headReceipt.embed_id !== head.embed_id || headReceipt.canonical_digest !== expectedDigest) {
      throw new Error(`Canonical embed ${head.embed_id} receipt did not match its ciphertext.`);
    }
  } catch (error) {
    if (!(error instanceof CanonicalEmbedWriteRejected) || error.code !== "embed_write_denied") throw error;
    canonical = await readEquivalentCanonicalHead(head);
  }
  const keys = operation.store_embed_keys_payload?.keys ?? [];
  if (canonical && keys.length > 0) await verifyQueuedWrappersForCanonicalHead(head, keys, canonical);
  const existingKeyTypes = canonical?.verifiedKeyTypes;
  const missingKeys = existingKeyTypes
    ? keys.filter((wrapper) => !existingKeyTypes.has(wrapper.key_type)) : keys;
  if (missingKeys.length > 0 && !(canonical && (requestedVersion > 1
    || Number(canonical.embed.version_number ?? 1) > requestedVersion))) {
    const keyReceipt = await sendWithReceipt("store_embed_keys", "store_embed_keys_confirmed", { keys: missingKeys });
    if (keyReceipt.failed_count !== 0 || keyReceipt.created_count !== missingKeys.length) {
      throw new Error(`Canonical embed ${head.embed_id} key wrappers were incomplete.`);
    }
  }
  if (canonical) {
    const { embedStore } = await import("./embedStore");
    await embedStore.putEncrypted(`embed:${head.embed_id}`, {
      embed_id: head.embed_id,
      encrypted_content: canonical.embed.encrypted_content,
      encrypted_type: canonical.embed.encrypted_type,
      encrypted_text_preview: canonical.embed.encrypted_text_preview,
      status: canonical.embed.status,
      hashed_chat_id: canonical.embed.hashed_chat_id,
      hashed_message_id: canonical.embed.hashed_message_id,
      hashed_user_id: canonical.embed.hashed_user_id,
      embed_ids: canonical.embed.embed_ids,
      parent_embed_id: canonical.embed.parent_embed_id,
      version_number: canonical.embed.version_number,
      is_private: canonical.embed.is_private,
      is_shared: canonical.embed.is_shared,
      createdAt: canonical.embed.created_at,
      updatedAt: canonical.embed.updated_at,
    }, canonical.type as EmbedType, canonical.content, {
      app_id: head.app_id, skill_id: head.skill_id,
    });
  }
}

async function persistQueuedEmbedOperation(
  operation: PendingEmbedOperation, lease?: CanonicalEmbedWriteLease,
): Promise<void> {
  const active = activePendingEmbedOperations.get(operation.operation_id);
  if (active) {
    try {
      await active;
      return;
    } catch {
      // The reconnect flush retries an operation whose previous socket closed.
    }
  }
  if (activePendingEmbedOperations.size >= MAX_ACTIVE_EMBED_RECEIPTS) {
    capacityDeferred = true;
    throw new Error("Canonical embed receipt capacity is full; operation remains queued for retry.");
  }
  const persist = async () => {
    const queued = (await chatDB.getPendingEmbedOperations())
      .filter((candidate) => candidate.embed_id === operation.embed_id)
      .sort((a, b) => a.created_at - b.created_at || a.operation_id.localeCompare(b.operation_id));
    const position = queued.findIndex((candidate) => candidate.operation_id === operation.operation_id);
    if (position < 0) return; // An earlier flush already committed this operation.
    for (const earlier of queued.slice(0, position)) {
      await persistCanonicalEmbedOperation(earlier);
      await chatDB.removePendingEmbedOperation(earlier.operation_id);
    }
    await persistCanonicalEmbedOperation(operation);
    await chatDB.removePendingEmbedOperation(operation.operation_id);
  };
  if (lease) assertCanonicalEmbedWriteLease(lease, operation.embed_id);
  const run = lease ? persist() : withCanonicalEmbedWrite(operation.embed_id, persist);
  activePendingEmbedOperations.set(operation.operation_id, run);
  try {
    await run;
  } finally {
    if (activePendingEmbedOperations.get(operation.operation_id) === run) {
      activePendingEmbedOperations.delete(operation.operation_id);
    }
    if (activePendingEmbedOperations.size < MAX_ACTIVE_EMBED_RECEIPTS) scheduleCapacityDrain();
  }
}

/**
 * Send encrypted embed to server for Directus storage.
 * If the WebSocket is not connected, queues the operation in IndexedDB
 * for retry on reconnect.
 */
export async function sendStoreEmbedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: StoreEmbedPayload,
  embedKeysPayload?: { keys: Array<Record<string, unknown>> },
  lease?: CanonicalEmbedWriteLease,
): Promise<boolean> {
  if (lease) assertCanonicalEmbedWriteLease(lease, payload.embed_id);
  const createdAt = Math.max(Date.now(), lastPendingEmbedOperationTime + 0.001);
  lastPendingEmbedOperationTime = createdAt;
  const operation: PendingEmbedOperation = {
    operation_id: crypto.randomUUID(), embed_id: payload.embed_id,
    store_embed_payload: payload, store_embed_keys_payload: embedKeysPayload,
    created_at: createdAt,
  };
  await chatDB.addPendingEmbedOperation(operation);
  if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
    console.warn(
      `[EmbedSenders] WebSocket not connected - queuing embed ${payload.embed_id} for offline sync`,
    );
    return false;
  }

  try {
    await persistQueuedEmbedOperation(operation, lease);
    return true;
  } catch (error) {
    if (error instanceof CanonicalEmbedRecoveryPending) return false;
    console.error(
      `[EmbedSenders] Canonical embed ${payload.embed_id} is pending retry:`,
      error,
    );
    return false;
  }
}

/**
 * Send embed key wrappers to server.
 * If offline, the keys are already queued as part of the embed operation.
 */
export async function sendStoreEmbedKeysImpl(
  serviceInstance: ChatSynchronizationService,
  payload: { keys: Array<Record<string, unknown>> },
): Promise<void> {
  if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
    throw new Error("Cannot store standalone embed keys while disconnected.");
  }
  const receipt = await sendWithReceipt("store_embed_keys", "store_embed_keys_confirmed", payload);
  if (receipt.failed_count !== 0 || receipt.created_count !== payload.keys.length) {
    throw new Error("Canonical embed key wrappers were incomplete.");
  }
}

/**
 * Send an encrypted embed version row to server.
 * This is only called after the receiving client encrypts snapshot/patch data
 * with the parent embed key.
 */
export async function sendStoreEmbedDiffImpl(
  serviceInstance: ChatSynchronizationService,
  payload: StoreEmbedDiffPayload,
): Promise<void> {
  if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
    console.warn(
      `[EmbedSenders] WebSocket not connected - encrypted diff row for ${payload.embed_id} v${payload.version_number} was not sent`,
    );
    return;
  }

  try {
    console.debug(
      `[EmbedSenders] Sending encrypted embed diff ${payload.embed_id} v${payload.version_number} to server`,
    );
    await webSocketService.sendMessage("store_embed_diff", payload);
  } catch (error) {
    console.error(
      `[EmbedSenders] Error sending store_embed_diff for ${payload.embed_id} v${payload.version_number}:`,
      error,
    );
  }
}

/**
 * Flush all pending embed operations from IndexedDB.
 * Called on WebSocket reconnect.
 */
export async function flushPendingEmbedOperations(): Promise<void> {
  if (pendingEmbedFlush) return pendingEmbedFlush;
  pendingEmbedFlush = (async () => {
    const operations = await chatDB.getPendingEmbedOperations();
    if (operations.length === 0) return;

    console.info(
      `[EmbedSenders] Flushing ${operations.length} pending embed operation(s)`,
    );

    for (const op of operations.sort((a, b) => a.created_at - b.created_at)) {
      try {
        await persistQueuedEmbedOperation(op);
        console.debug(
          `[EmbedSenders] Flushed embed operation ${op.embed_id}`,
        );
      } catch (error) {
        if (error instanceof CanonicalEmbedRecoveryPending) continue;
        console.error(
          `[EmbedSenders] Failed to flush embed operation ${op.embed_id}:`,
          error,
        );
        // Leave in queue for next reconnect attempt
      }
    }
  })().catch((error) => {
    console.error(
      "[EmbedSenders] Error flushing pending embed operations:",
      error,
    );
  }).finally(() => { pendingEmbedFlush = null; });
  return pendingEmbedFlush;
}

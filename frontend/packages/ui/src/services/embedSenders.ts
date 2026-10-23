import type { ChatSynchronizationService } from "./chatSyncService";
import { webSocketService } from "./websocketService";
import type { Chat, StoreEmbedDiffPayload, StoreEmbedPayload } from "../types/chat";
import type { EmbedType } from "../message_parsing/types";
import { chatDB, type PendingEmbedOperation } from "./db";
import { notificationStore } from "../stores/notificationStore";
import { get } from "svelte/store";
import { text } from "../i18n/translations";
import { computeSHA256 } from "../message_parsing/utils";
import { getApiEndpoint, storageArchiveFetch } from "../config/api";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { getKeyFromStorage } from "./cryptoService";
import {
  decryptWithEmbedKey, unwrapEmbedKeyWithChatKey, unwrapEmbedKeyWithMasterKey,
} from "./encryption/MetadataEncryptor";
import {
  assertCanonicalEmbedWriteLease, withCanonicalEmbedWrite,
  type CanonicalEmbedWriteLease,
} from "./canonicalEmbedWriteCoordinator";

const EMBED_RECEIPT_TIMEOUT_MS = 30_000;
const MAX_ACTIVE_EMBED_RECEIPTS = 32;
const activePendingEmbedOperations = new Map<string, Promise<EmbedPersistenceResult>>();
const persistenceChatIds = new Map<string, string>();
const MAX_PERSISTENCE_CHAT_IDS = 128;
const RECONCILABLE_WRITE_REJECTIONS = new Set([
  "canonical_precondition_mismatch", "acknowledged_embed_revision_immutable",
]);
let pendingEmbedFlush: Promise<void> | null = null;
let lastPendingEmbedOperationTime = 0;
let capacityDeferred = false;
let capacityDrainScheduled = false;

export type EmbedPersistenceResult =
  | { status: "persisted" | "adopted"; operation_id: string }
  | { status: "waiting"; operation_id: string; failure_code?: string }
  | { status: "conflict" | "denied"; operation_id: string; failure_code: string };

interface CanonicalRevision {
  version: number;
  ciphertext_sha256: string;
  write_state: "mutable" | "immutable";
}

class CanonicalEmbedConflict extends Error {
  constructor(readonly code: string) { super(code); }
}

function requireAuthorizedRead(response: { ok: boolean; status: number }): void {
  if (response.status === 403) throw new CanonicalEmbedWriteRejected("embed_write_denied");
  if (!response.ok) throw new Error(`Canonical embed read unavailable (${response.status}).`);
}

class CanonicalEmbedWriteRejected extends Error {
  constructor(readonly code: string, readonly reason?: string) {
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
  let releaseErrorOwnership = () => {};
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
      reject(new CanonicalEmbedWriteRejected(error.code,
        typeof error.reason === "string" && /^[A-Za-z0-9._:-]{1,128}$/.test(error.reason) ? error.reason : undefined));
    };
    stop = () => {
      releaseErrorOwnership();
      globalThis.clearTimeout(timer);
      webSocketService.off(confirmedType, onConfirmed);
      webSocketService.removeEventListener("close", onClose);
    };
    webSocketService.on(confirmedType, onConfirmed);
    releaseErrorOwnership = webSocketService.ownEmbedProtocolRequest(requestId, onError);
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
async function readEquivalentCanonicalHead(head: StoreEmbedPayload, historical = false, revision?: CanonicalRevision): Promise<{
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
  requireAuthorizedRead(response);
  const page = await response.json() as {
    embed?: Record<string, unknown>; embed_keys?: Array<Record<string, unknown>>;
    embed_keys_has_more_after?: boolean; oversized_embed_key_id?: string | null;
  };
  const embed = page.embed;
  const canonicalVersion = embed?.version_number ?? 1;
  if (typeof canonicalVersion !== "number" || !Number.isSafeInteger(canonicalVersion) || canonicalVersion < 1) {
    throw new CanonicalEmbedConflict("embed_version_conflict");
  }
  if (revision && embed && (canonicalVersion !== revision.version
    || typeof embed.encrypted_content !== "string"
    || await computeSHA256(embed.encrypted_content) !== revision.ciphertext_sha256)) {
    throw new CanonicalEmbedRecoveryPending();
  }
  const same = (value: unknown, expected: unknown) => value === expected;
  if (!embed || !same(embed.embed_id, head.embed_id)
    || !same(embed.hashed_chat_id, head.hashed_chat_id)
    || !same(embed.hashed_user_id, head.hashed_user_id)
    || !same(embed.hashed_message_id, head.hashed_message_id)
    || !same(embed.parent_embed_id ?? null, head.parent_embed_id ?? null)
    || (historical
      ? canonicalVersion <= (head.version_number ?? 1)
      : !same(canonicalVersion, head.version_number ?? 1))
    || (!historical && !same(embed.status, head.status))
    || (head.app_id !== undefined && !same(embed.app_id, head.app_id))
    || (head.skill_id !== undefined && !same(embed.skill_id, head.skill_id))
    // Older recovered heads omitted optional task indexing. Missing metadata is
    // compatible only after all scope/key/content checks below; a different
    // non-null task identity still conflicts.
    || (!historical && head.hashed_task_id !== undefined && embed.hashed_task_id != null
      && !same(embed.hashed_task_id, head.hashed_task_id))
    || (!historical && head.embed_ids !== undefined
      && JSON.stringify(embed.embed_ids ?? []) !== JSON.stringify(head.embed_ids ?? []))
    || (!historical && head.is_private !== undefined && !same(embed.is_private, head.is_private))
    || (!historical && head.is_shared !== undefined && !same(embed.is_shared, head.is_shared))
    || typeof embed.encrypted_content !== "string" || typeof embed.encrypted_type !== "string") {
    throw new CanonicalEmbedConflict("embed_identity_or_version_conflict");
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
      throw new CanonicalEmbedConflict("embed_wrapper_conflict");
    }
    let unwrapped: Uint8Array | null = null;
    if (wrapper.key_type === "master") {
      if (!await getKeyFromStorage()) throw new CanonicalEmbedRecoveryPending();
      unwrapped = await unwrapEmbedKeyWithMasterKey(wrapper.encrypted_embed_key, keySubject);
    } else {
      const chatKey = await chatKeyManager.getKey(head.chat_id);
      if (!chatKey) throw new CanonicalEmbedRecoveryPending();
      unwrapped = await unwrapEmbedKeyWithChatKey(wrapper.encrypted_embed_key, chatKey, {
        embedId: keySubject, chatId: head.chat_id,
      });
    }
    if (!unwrapped || unwrapped.length !== key.length
      || unwrapped.some((byte, index) => byte !== key[index])) {
      throw new CanonicalEmbedConflict("embed_wrapper_conflict");
    }
    // Historical wrappers may use different nonces for the same key. Verify
    // every row before deduplicating types; never rotate canonical ciphertext.
    verifiedKeyTypes.add(wrapper.key_type);
  }
  if (verifiedKeyTypes.size === 0) throw new CanonicalEmbedRecoveryPending();
  const [queuedContent, canonicalContent, queuedType, canonicalType] = await Promise.all([
    decryptWithEmbedKey(head.encrypted_content, key),
    decryptWithEmbedKey(embed.encrypted_content, key),
    decryptWithEmbedKey(head.encrypted_type, key),
    decryptWithEmbedKey(embed.encrypted_type, key),
  ]);
  if (queuedContent === null || queuedType === null
    || canonicalContent === null || (!historical && queuedContent !== canonicalContent)
    || queuedType !== canonicalType) {
    throw new CanonicalEmbedConflict("embed_content_or_type_conflict");
  }
  const queuedPreview = head.encrypted_text_preview;
  const canonicalPreview = embed.encrypted_text_preview;
  if (!historical && (queuedPreview != null || canonicalPreview != null)) {
    if (typeof queuedPreview !== "string" || typeof canonicalPreview !== "string") {
      throw new CanonicalEmbedConflict("embed_preview_conflict");
    }
    const [queuedText, canonicalText] = await Promise.all([
      decryptWithEmbedKey(queuedPreview, key),
      decryptWithEmbedKey(canonicalPreview, key),
    ]);
    if (queuedText === null || canonicalText === null || queuedText !== canonicalText) {
      throw new CanonicalEmbedConflict("embed_preview_conflict");
    }
  }
  return { embed, type: canonicalType, content: canonicalContent,
    queuedContent, key, keySubject, verifiedKeyTypes };
}

/** Reconcile an old queued root only against its authenticated historical source. */
async function readEquivalentHistoricalHead(
  head: StoreEmbedPayload, revision: CanonicalRevision,
): Promise<Awaited<ReturnType<typeof readEquivalentCanonicalHead>>> {
  const canonical = await readEquivalentCanonicalHead(head, true, revision);
  const chat = await chatDB.getRawChat(head.chat_id!);
  if (!chat || (chat.team_id ?? null) !== (head.team_id ?? null)) {
    throw new CanonicalEmbedConflict("embed_identity_conflict");
  }
  const query = new URLSearchParams({ capability: "bounded-v1", chat_id: head.chat_id! });
  if (chat.team_id) query.set("team_id", chat.team_id);
  const response = await storageArchiveFetch(getApiEndpoint(
    `/v1/embeds/${encodeURIComponent(head.embed_id)}/versions/${head.version_number ?? 1}?${query}`,
  ), { credentials: "include" });
  requireAuthorizedRead(response);
  const page = await response.json() as {
    embed_id?: string; version_number?: number;
    rows?: Array<{ version_number: number; encrypted_snapshot?: string | null; encrypted_patch?: string | null }>;
  };
  if (page.embed_id !== head.embed_id || page.version_number !== (head.version_number ?? 1)
    || !Array.isArray(page.rows)
    || page.rows[page.rows.length - 1]?.version_number !== (head.version_number ?? 1)) {
    throw new CanonicalEmbedConflict("embed_version_conflict");
  }
  const [{ reconstructEncryptedVersionRows }, { historySourceFromSealedEmbed }] = await Promise.all([
    import("./embedDiffStore"), import("./recoveryEmbedSource"),
  ]);
  const source = await historySourceFromSealedEmbed(canonical.queuedContent, canonical.type);
  const reconstructionRows = page.rows.map((row) => ({ ...row,
    created_at: 0, has_snapshot: !!row.encrypted_snapshot, has_patch: !!row.encrypted_patch,
  }));
  if (await reconstructEncryptedVersionRows(reconstructionRows, canonical.key) !== source) {
    throw new CanonicalEmbedConflict("embed_content_conflict");
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
      throw new CanonicalEmbedConflict("embed_wrapper_conflict");
    }
    let unwrapped: Uint8Array | null = null;
    if (wrapper.key_type === "master" && wrapper.hashed_chat_id == null) {
      if (!await getKeyFromStorage()) throw new CanonicalEmbedRecoveryPending();
      unwrapped = await unwrapEmbedKeyWithMasterKey(wrapper.encrypted_embed_key, canonical.keySubject);
    } else if (wrapper.key_type === "chat" && wrapper.hashed_chat_id === head.hashed_chat_id) {
      const chatKey = await chatKeyManager.getKey(head.chat_id!);
      if (!chatKey) throw new CanonicalEmbedRecoveryPending();
      unwrapped = await unwrapEmbedKeyWithChatKey(wrapper.encrypted_embed_key, chatKey, {
        embedId: canonical.keySubject, chatId: head.chat_id,
      });
    }
    if (!unwrapped || unwrapped.length !== canonical.key.length
      || unwrapped.some((byte, index) => byte !== canonical.key[index])) {
      throw new CanonicalEmbedConflict("embed_wrapper_conflict");
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

async function persistCanonicalEmbedOperation(
  operation: PendingEmbedOperation, readOnly = false,
): Promise<"persisted" | "adopted"> {
  // Once another consumer wins a CAS, every retry/reload must remain read-only
  // until equivalence is proved. Never turn temporary read unavailability into
  // permission to overwrite the winner with a fresh precondition.
  readOnly ||= RECONCILABLE_WRITE_REJECTIONS.has(operation.failure_code ?? "");
  const head = await resolveEmbedPersistenceContext(operation.store_embed_payload);
  const requestedVersion = head.version_number ?? 1;
  if (!Number.isSafeInteger(requestedVersion) || requestedVersion < 1) {
    throw new CanonicalEmbedConflict("embed_version_conflict");
  }
  if (!head.chat_id || !head.hashed_chat_id || !head.hashed_user_id) {
    throw new Error("Canonical embed chat and owner scope are unavailable.");
  }
  const chat = await chatDB.getRawChat(head.chat_id);
  if (!chat) throw new Error("Canonical embed chat is not hydrated.");
  if (await computeSHA256(chat.chat_id) !== head.hashed_chat_id
    || (chat.team_id ?? null) !== (head.team_id ?? null)) {
    throw new CanonicalEmbedConflict("embed_identity_conflict");
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
  requireAuthorizedRead(availability);
  const result = await availability.json() as {
    results?: Array<{ embed_id?: string; state?: string; canonical_revision?: CanonicalRevision }>;
  };
  if (!Array.isArray(result.results) || result.results.length !== (head.parent_embed_id ? 2 : 1)
    || result.results[0].embed_id !== head.embed_id
    || (head.parent_embed_id && result.results[1].embed_id !== head.parent_embed_id)) {
    throw new Error("Canonical embed availability identity is unknown.");
  }
  if (head.parent_embed_id && result.results[1].state !== "ready") {
    throw new CanonicalEmbedRecoveryPending();
  }
  const availabilityHead = result.results[0];
  const revision = availabilityHead.canonical_revision;
  let canonical: Awaited<ReturnType<typeof readEquivalentCanonicalHead>> | null = null;
  let precondition: { version: number | null; ciphertext_sha256: string | null } | undefined;
  let allowWrapperWrites = !readOnly;
  if (availabilityHead.state === "missing") {
    if (readOnly || requestedVersion > 1) throw new CanonicalEmbedRecoveryPending();
    precondition = { version: null, ciphertext_sha256: null };
  } else {
    // Missing/invalid proof is UNKNOWN. A missing recovery ACK never grants permission.
    if (!revision || !Number.isSafeInteger(revision.version) || revision.version < 1
      || typeof revision.ciphertext_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(revision.ciphertext_sha256)
      || (revision.write_state !== "mutable" && revision.write_state !== "immutable")) {
      if (availabilityHead.state !== "ready") throw new CanonicalEmbedRecoveryPending();
      // Read-only equivalence can prove durable canonical bytes even when
      // availability cannot grant a write capability (notably child embeds).
      canonical = await readEquivalentCanonicalHead(head);
      allowWrapperWrites = false;
    } else {
      if (revision.version === requestedVersion - 1) throw new CanonicalEmbedRecoveryPending();
      if (revision.version > requestedVersion) {
        canonical = await readEquivalentHistoricalHead(head, revision);
      } else if (revision.version !== requestedVersion) {
        throw new CanonicalEmbedConflict("embed_version_conflict");
      } else if (readOnly || revision.write_state === "immutable") {
        canonical = await readEquivalentCanonicalHead(head, false, revision);
      }
      precondition = { version: revision.version, ciphertext_sha256: revision.ciphertext_sha256 };
    }
  }
  if (!canonical) {
    if (!precondition) throw new CanonicalEmbedRecoveryPending();
    let headReceipt: Record<string, unknown>;
    try {
      headReceipt = await sendWithReceipt("store_embed", "store_embed_confirmed", {
        ...head, version_number: requestedVersion, canonical_precondition: precondition,
        operation_id: operation.operation_id,
      });
    } catch (error) {
      if (error instanceof CanonicalEmbedWriteRejected
        && error.code === "embed_revision_conflict" && RECONCILABLE_WRITE_REJECTIONS.has(error.reason ?? "")) {
        // Another browser/recovery consumer may have saved the same result with
        // another AES nonce. Refresh authority and prove equivalence without
        // retrying a write or replacing the original queued ciphertext.
        const reconciliation = { ...operation, failure_code: error.reason };
        await chatDB.addPendingEmbedOperation(reconciliation);
        return persistCanonicalEmbedOperation(reconciliation, true);
      }
      throw error;
    }
    const expectedDigest = await computeSHA256(head.encrypted_content);
    if (headReceipt.embed_id !== head.embed_id || headReceipt.canonical_digest !== expectedDigest) {
      throw new Error("Canonical embed receipt did not match its ciphertext.");
    }
  }
  const keys = operation.store_embed_keys_payload?.keys ?? [];
  if (canonical && keys.length > 0) await verifyQueuedWrappersForCanonicalHead(head, keys, canonical);
  const existingKeyTypes = canonical?.verifiedKeyTypes;
  const missingKeys = existingKeyTypes
    ? keys.filter((wrapper) => typeof wrapper.key_type !== "string" || !existingKeyTypes.has(wrapper.key_type)) : keys;
  if (missingKeys.length > 0 && !allowWrapperWrites) throw new CanonicalEmbedRecoveryPending();
  if (missingKeys.length > 0 && !(canonical && (requestedVersion > 1
    || Number(canonical.embed.version_number ?? 1) > requestedVersion))) {
    const keyReceipt = await sendWithReceipt("store_embed_keys", "store_embed_keys_confirmed", { keys: missingKeys,
      operation_id: operation.operation_id });
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
  return canonical ? "adopted" : "persisted";
}

function terminalResult(operation: PendingEmbedOperation): EmbedPersistenceResult | null {
  return operation.state === "conflict" || operation.state === "denied"
    ? { status: operation.state, operation_id: operation.operation_id, failure_code: operation.failure_code ?? (operation.state === "denied" ? "embed_write_denied" : "embed_revision_conflict") }
    : null;
}

/** Recheck only failures caused by the old CAS/task-metadata comparisons. */
function canReconcileRetainedConflict(operation: PendingEmbedOperation): boolean {
  return operation.state === "conflict" && (RECONCILABLE_WRITE_REJECTIONS.has(operation.failure_code ?? "")
    || operation.failure_code === "embed_identity_or_version_conflict");
}

async function settleOperation(operation: PendingEmbedOperation): Promise<EmbedPersistenceResult> {
  const terminal = terminalResult(operation);
  if (terminal && !canReconcileRetainedConflict(operation)) return terminal;
  try {
    const status = await persistCanonicalEmbedOperation(operation, terminal !== null);
    await chatDB.removePendingEmbedOperation(operation.operation_id);
    if (terminal && !(await chatDB.getPendingEmbedOperations()).some((other) =>
      other.embed_id === operation.embed_id && terminalResult(other))) {
      notificationStore.removeNotificationsByDedupeKey(`embed-write-conflict:${operation.embed_id}`);
    }
    return { status, operation_id: operation.operation_id };
  } catch (error) {
    // Retained conflicts are read-only recovery probes. Keep their evidence and
    // original classification until equivalence is fully proved.
    if (terminal) return terminal;
    const denied = error instanceof CanonicalEmbedWriteRejected && error.code === "embed_write_denied";
    const conflict = error instanceof CanonicalEmbedConflict
      || (error instanceof CanonicalEmbedWriteRejected && error.code === "embed_revision_conflict");
    if (!denied && !conflict) return { status: "waiting", operation_id: operation.operation_id };
    const state = denied ? "denied" : "conflict";
    const failure_code = error instanceof CanonicalEmbedWriteRejected ? error.reason ?? error.code : error.code;
    // Replace only queue control fields. Ciphertext and wrappers remain the original evidence.
    await chatDB.addPendingEmbedOperation({ ...operation, state, failure_code });
    console.warn("[EmbedSenders] Canonical embed operation requires review", {
      failure_code, origin: operation.origin ?? "legacy",
      version: operation.store_embed_payload.version_number ?? 1,
    });
    notificationStore.addNotificationWithOptions("warning", {
      message: get(text)(denied ? "chats.embed_sync.denied" : "chats.embed_sync.conflict"),
      duration: 0, dedupeKey: `embed-write-conflict:${operation.embed_id}`,
      ...(operation.store_embed_payload.chat_id ? {
        actionLabel: get(text)("chats.embed_sync.review_chat"),
        onAction: async () => {
          const chat = await chatDB.getChat(operation.store_embed_payload.chat_id!);
          if (chat) window.dispatchEvent(new CustomEvent("chatHeaderNavigation", {
            detail: { chat, scrollToTop: false },
          }));
        },
      } : {}),
    });
    return { status: state, operation_id: operation.operation_id, failure_code };
  }
}

async function persistQueuedEmbedOperation(
  operation: PendingEmbedOperation, lease?: CanonicalEmbedWriteLease,
): Promise<EmbedPersistenceResult> {
  const terminal = terminalResult(operation);
  if (terminal && !canReconcileRetainedConflict(operation)) return terminal;
  const active = activePendingEmbedOperations.get(operation.operation_id);
  if (active) return active;
  if (activePendingEmbedOperations.size >= MAX_ACTIVE_EMBED_RECEIPTS) {
    capacityDeferred = true;
    return { status: "waiting", operation_id: operation.operation_id };
  }
  const persist = async (): Promise<EmbedPersistenceResult> => {
    if (terminal) return settleOperation(operation);
    const queued = (await chatDB.getPendingEmbedOperations())
      .filter((candidate) => candidate.embed_id === operation.embed_id && !terminalResult(candidate))
      .sort((a, b) => a.created_at - b.created_at || a.operation_id.localeCompare(b.operation_id));
    const position = queued.findIndex((candidate) => candidate.operation_id === operation.operation_id);
    if (position < 0) return { status: "persisted", operation_id: operation.operation_id };
    for (const earlier of queued.slice(0, position)) {
      const result = await settleOperation(earlier);
      if (result.status === "waiting") return { status: "waiting", operation_id: operation.operation_id };
    }
    // Use the freshly read queue controls: another browser may have marked
    // this operation read-only since the caller took its flush snapshot.
    return settleOperation(queued[position]);
  };
  if (lease) assertCanonicalEmbedWriteLease(lease, operation.embed_id);
  const run = lease ? persist() : withCanonicalEmbedWrite(operation.embed_id, persist);
  activePendingEmbedOperations.set(operation.operation_id, run);
  try { return await run; } finally {
    if (activePendingEmbedOperations.get(operation.operation_id) === run) activePendingEmbedOperations.delete(operation.operation_id);
    if (activePendingEmbedOperations.size < MAX_ACTIVE_EMBED_RECEIPTS) scheduleCapacityDrain();
  }
}

/** Persist one durable operation; reconnects reuse its identity and original encrypted payload. */
export async function sendStoreEmbedOperationImpl(
  serviceInstance: ChatSynchronizationService,
  payload: StoreEmbedPayload,
  embedKeysPayload?: { keys: Array<Record<string, unknown>> },
  lease?: CanonicalEmbedWriteLease,
  origin = "canonical-embed-sender",
): Promise<EmbedPersistenceResult> {
  if (lease) assertCanonicalEmbedWriteLease(lease, payload.embed_id);
  const createdAt = Math.max(Date.now(), lastPendingEmbedOperationTime + 0.001);
  lastPendingEmbedOperationTime = createdAt;
  const operation: PendingEmbedOperation = {
    operation_id: crypto.randomUUID(), embed_id: payload.embed_id,
    store_embed_payload: payload, store_embed_keys_payload: embedKeysPayload,
    created_at: createdAt, state: "pending", origin,
  };
  await chatDB.addPendingEmbedOperation(operation);
  if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
    return { status: "waiting", operation_id: operation.operation_id };
  }
  return persistQueuedEmbedOperation(operation, lease);
}

/** Compatibility adapter for producers that only need a durable success flag. */
export async function sendStoreEmbedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: StoreEmbedPayload,
  embedKeysPayload?: { keys: Array<Record<string, unknown>> },
  lease?: CanonicalEmbedWriteLease,
  origin = "canonical-embed-sender",
): Promise<boolean> {
  const result = await sendStoreEmbedOperationImpl(serviceInstance, payload, embedKeysPayload, lease, origin);
  return result.status === "persisted" || result.status === "adopted";
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
    const operations = (await chatDB.getPendingEmbedOperations()).filter((op) => !terminalResult(op) || canReconcileRetainedConflict(op));
    if (operations.length === 0) return;

    console.info(
      `[EmbedSenders] Flushing ${operations.length} pending embed operation(s)`,
    );

    for (const op of operations.sort((a, b) => a.created_at - b.created_at)) {
      try {
        const result = await persistQueuedEmbedOperation(op);
        console.debug(`[EmbedSenders] Embed operation outcome: ${result.status}`);
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

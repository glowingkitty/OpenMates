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
import {
  RECONCILABLE_WRITE_REJECTIONS, availabilityPlan, availabilityRequest, canonicalIdentity, canonicalWrapperRow,
  classifyFailure, historyPage, identityNeedsContentDigest, missingKeys as planMissingKeys, queuedWrapperRow,
  receiptMatches, type CanonicalPrecondition, type EmbedSenderDecisions, type EmbedSenderOp, type FailureInput,
  type ReceiptInput, type SenderHeadFacts, type WrapperRowAction,
} from "./embedSenderPolicy";

const EMBED_RECEIPT_TIMEOUT_MS = 30_000;
const MAX_ACTIVE_EMBED_RECEIPTS = 32;
const activePendingEmbedOperations = new Map<string, Promise<EmbedPersistenceResult>>();
const persistenceChatIds = new Map<string, string>();
const MAX_PERSISTENCE_CHAT_IDS = 128;
/**
 * VITE_OPENMATES_RUST_CORE=1: the sender decisions run in the shared Rust core
 * (embedSenderPolicy.ts documents the split). Default builds fold every
 * `RUST_EMBED_SENDER_BUILD ? await … : null` to null, so the synchronous TS
 * decision runs at the original place with no added await.
 */
const RUST_EMBED_SENDER_BUILD: boolean = import.meta.env.VITE_OPENMATES_RUST_CORE === "1";
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

/** Flag on: the Rust sender decision; null only when the Rust crypto arm is inactive (the TS arm). */
async function rustSenderDecision<O extends EmbedSenderOp>(
  op: O, input: EmbedSenderDecisions[O]["input"],
): Promise<EmbedSenderDecisions[O]["output"] | null> {
  const { decideEmbedSenderInRust } = await import("./rustCore/embeds/embedDataClient");
  return decideEmbedSenderInRust(op, input);
}

/** Rust answers `malformed` where the TS decision raised a TypeError on a null document. */
function malformed(what: string): TypeError {
  return new TypeError(`Canonical embed ${what} is malformed.`);
}

function wrapperAction(action: WrapperRowAction | "malformed" | undefined): WrapperRowAction {
  if (action === "malformed" || action === undefined) throw malformed("key wrapper row");
  return action;
}

/** Queued wrappers are never skipped: each one is proven or refused. */
function queuedAction(action: WrapperRowAction): Exclude<WrapperRowAction, "skip"> {
  if (action === "skip") throw malformed("queued key wrapper verdict");
  return action;
}

function receiptOk(input: ReceiptInput, rust: boolean | null): boolean {
  return rust ?? receiptMatches(input);
}

/** The queued head fields the canonical identity check compares. */
function senderHeadFacts(head: StoreEmbedPayload): SenderHeadFacts {
  return {
    embed_id: head.embed_id, hashed_chat_id: head.hashed_chat_id, hashed_user_id: head.hashed_user_id,
    hashed_message_id: head.hashed_message_id, parent_embed_id: head.parent_embed_id,
    version_number: head.version_number, status: head.status, app_id: head.app_id, skill_id: head.skill_id,
    hashed_task_id: head.hashed_task_id, is_private: head.is_private, is_shared: head.is_shared,
  };
}

function failureFacts(error: unknown): FailureInput {
  if (error instanceof CanonicalEmbedWriteRejected) return { kind: "rejected", code: error.code, reason: error.reason ?? null };
  if (error instanceof CanonicalEmbedConflict) return { kind: "conflict", code: error.code, reason: null };
  return { kind: "other", code: null, reason: null };
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
  type: "store_embed" | "store_embed_keys" | "store_embed_diff",
  confirmedType: "store_embed_confirmed" | "store_embed_keys_confirmed" | "store_embed_diff_confirmed",
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

/**
 * Prove that a queued re-encrypted write is the already sealed head. With
 * `advance` (a Rust `read_advance` plan) the Rust identity verdict may instead
 * find this child one version below the queued head: then the same key/type
 * proof runs, content is not compared, and `advancePrecondition` is the
 * Rust-built write precondition.
 */
async function readEquivalentCanonicalHead(head: StoreEmbedPayload, historical = false, revision?: CanonicalRevision,
  advance = false): Promise<{
  embed: Record<string, unknown>; type: string; content: string;
  queuedContent: string; key: Uint8Array; keySubject: string; verifiedKeyTypes: Set<string>;
  advancePrecondition: CanonicalPrecondition | null;
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
  const page: unknown = await response.json();
  // A null page throws this TypeError here, before any decision (as before).
  const embed = (page as { embed?: Record<string, unknown> }).embed;
  const advanceDigest = advance && typeof embed === "object" && embed !== null
    && typeof embed.encrypted_content === "string";
  const contentSha256 = advanceDigest || identityNeedsContentDigest(page, revision ?? null)
    ? await computeSHA256((embed as Record<string, unknown>).encrypted_content as string) : null;
  const identityInput = {
    head: senderHeadFacts(head), page, historical, revision: revision ?? null, content_sha256: contentSha256,
    head_embed_ids_json: head.embed_ids !== undefined ? JSON.stringify(head.embed_ids ?? []) : null,
    embed_ids_json: typeof embed === "object" && embed !== null ? JSON.stringify(embed.embed_ids ?? []) : null,
    ...(advance ? { advance: true } : {}),
  };
  const identity = (RUST_EMBED_SENDER_BUILD ? await rustSenderDecision("senderCanonicalIdentity", identityInput) : null)
    ?? canonicalIdentity(identityInput);
  switch (identity.outcome) {
    case "malformed": throw malformed("page");
    case "conflict": throw new CanonicalEmbedConflict(identity.code);
    case "recovery_pending": throw new CanonicalEmbedRecoveryPending();
    case "wrappers_incomplete": throw new Error("Canonical embed key wrappers are incomplete.");
  }
  const advancePrecondition = identity.outcome === "advance" ? identity.precondition : null;
  // Only an advance compares no content: the canonical head is the previous version.
  const sameVersion = !historical && advancePrecondition === null;
  // The identity verdict proved `embed` an object with string ciphertext and a bounded wrapper array.
  const canonicalEmbed = embed as Record<string, unknown> & { encrypted_content: string; encrypted_type: string };
  const embedKeys = (page as { embed_keys: Array<Record<string, unknown>> }).embed_keys;
  const { embedStore } = await import("./embedStore");
  const key = await embedStore.getEmbedKey(head.embed_id, head.hashed_chat_id);
  if (!key) throw new Error("Canonical embed key is unavailable.");
  const keySubject = head.parent_embed_id || head.embed_id;
  const hashedSubject = await computeSHA256(keySubject);
  const verifiedKeyTypes = new Set<string>();
  const rowInput = { hashed_subject: hashedSubject, hashed_user_id: head.hashed_user_id, hashed_chat_id: head.hashed_chat_id };
  const rustActions = RUST_EMBED_SENDER_BUILD
    ? await rustSenderDecision("senderWrapperRows", { ...rowInput, mode: "canonical", rows: embedKeys }) : null;
  for (const [index, wrapper] of embedKeys.entries()) {
    // Other authorized key scopes are not evidence that this owner's queued
    // master/chat wrapper already exists. Validate every row we would reuse.
    const action = rustActions ? wrapperAction(rustActions[index]) : canonicalWrapperRow(wrapper, rowInput);
    if (action === "skip") continue;
    if (action === "conflict") throw new CanonicalEmbedConflict("embed_wrapper_conflict");
    const wrapped = wrapper.encrypted_embed_key as string;
    let unwrapped: Uint8Array | null = null;
    if (action === "master") {
      if (!await getKeyFromStorage()) throw new CanonicalEmbedRecoveryPending();
      unwrapped = await unwrapEmbedKeyWithMasterKey(wrapped, keySubject);
    } else {
      const chatKey = await chatKeyManager.getKey(head.chat_id);
      if (!chatKey) throw new CanonicalEmbedRecoveryPending();
      unwrapped = await unwrapEmbedKeyWithChatKey(wrapped, chatKey, {
        embedId: keySubject, chatId: head.chat_id,
      });
    }
    if (!unwrapped || unwrapped.length !== key.length
      || unwrapped.some((byte, index) => byte !== key[index])) {
      throw new CanonicalEmbedConflict("embed_wrapper_conflict");
    }
    // Historical wrappers may use different nonces for the same key. Verify
    // every row before deduplicating types; never rotate canonical ciphertext.
    verifiedKeyTypes.add(action);
  }
  if (verifiedKeyTypes.size === 0) throw new CanonicalEmbedRecoveryPending();
  const [queuedContent, canonicalContent, queuedType, canonicalType] = await Promise.all([
    decryptWithEmbedKey(head.encrypted_content, key),
    decryptWithEmbedKey(canonicalEmbed.encrypted_content, key),
    decryptWithEmbedKey(head.encrypted_type, key),
    decryptWithEmbedKey(canonicalEmbed.encrypted_type, key),
  ]);
  if (queuedContent === null || queuedType === null
    || canonicalContent === null || (sameVersion && queuedContent !== canonicalContent)
    || queuedType !== canonicalType) {
    throw new CanonicalEmbedConflict("embed_content_or_type_conflict");
  }
  const queuedPreview = head.encrypted_text_preview;
  const canonicalPreview = canonicalEmbed.encrypted_text_preview;
  if (sameVersion && (queuedPreview != null || canonicalPreview != null)) {
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
  return { embed: canonicalEmbed, type: canonicalType, content: canonicalContent,
    queuedContent, key, keySubject, verifiedKeyTypes, advancePrecondition };
}

/**
 * A finished child reports no canonical revision, so availability cannot see that a
 * later user-made version (Enhance, restore) superseded the queued one. When the
 * current head conflicts, the queued version settles only if the server's stored row
 * of that version reconstructs to exactly the queued content; otherwise the original
 * conflict stands.
 */
async function readEquivalentCurrentOrSupersededChild(
  head: StoreEmbedPayload,
): Promise<Awaited<ReturnType<typeof readEquivalentCanonicalHead>>> {
  try {
    return await readEquivalentCanonicalHead(head);
  } catch (current) {
    if (!head.parent_embed_id || !(current instanceof CanonicalEmbedConflict)
      || current.code !== "embed_identity_or_version_conflict") throw current;
    try {
      return await readEquivalentHistoricalHead(head);
    } catch (historical) {
      if (historical instanceof CanonicalEmbedConflict) throw current;
      throw historical;
    }
  }
}

/** Reconcile an old queued root only against its authenticated historical source. */
async function readEquivalentHistoricalHead(
  head: StoreEmbedPayload, revision?: CanonicalRevision,
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
  const pageInput = { embed_id: head.embed_id, version: head.version_number ?? 1, page };
  const pageVerdict = (RUST_EMBED_SENDER_BUILD ? await rustSenderDecision("senderHistoryPage", pageInput) : null)
    ?? historyPage(pageInput);
  if (pageVerdict.outcome === "malformed") throw malformed("version page");
  if (pageVerdict.outcome === "conflict") throw new CanonicalEmbedConflict(pageVerdict.code);
  if (!page.rows) throw malformed("version page");
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
  const rowInput = { hashed_subject: hashedSubject, hashed_user_id: head.hashed_user_id, hashed_chat_id: head.hashed_chat_id };
  const rustActions = RUST_EMBED_SENDER_BUILD
    ? await rustSenderDecision("senderWrapperRows", { ...rowInput, mode: "queued", rows: keys }) : null;
  for (const [index, wrapper] of keys.entries()) {
    const action = rustActions
      ? queuedAction(wrapperAction(rustActions[index]))
      : queuedWrapperRow(wrapper, rowInput);
    // A row that is neither this owner's master nor this chat's wrapper unwraps nothing.
    if (action === "conflict") throw new CanonicalEmbedConflict("embed_wrapper_conflict");
    const wrapped = wrapper.encrypted_embed_key as string;
    let unwrapped: Uint8Array | null = null;
    if (action === "master") {
      if (!await getKeyFromStorage()) throw new CanonicalEmbedRecoveryPending();
      unwrapped = await unwrapEmbedKeyWithMasterKey(wrapped, canonical.keySubject);
    } else {
      const chatKey = await chatKeyManager.getKey(head.chat_id!);
      if (!chatKey) throw new CanonicalEmbedRecoveryPending();
      unwrapped = await unwrapEmbedKeyWithChatKey(wrapped, chatKey, {
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
  const requestInput = {
    chat_id: head.chat_id, team_id: chat.team_id ?? null, embed_id: head.embed_id,
    parent_embed_id: head.parent_embed_id ?? null, version: requestedVersion,
  };
  const request = (RUST_EMBED_SENDER_BUILD ? await rustSenderDecision("senderAvailabilityRequest", requestInput) : null)
    ?? availabilityRequest(requestInput);
  const availability = await fetch(getApiEndpoint(request.path), {
    method: "POST", credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request.body),
  });
  requireAuthorizedRead(availability);
  const reply: unknown = await availability.json();
  const planInput = {
    embed_id: head.embed_id, parent_embed_id: head.parent_embed_id ?? null,
    requested_version: requestedVersion, read_only: readOnly, reply, origin: operation.origin ?? null,
  };
  // Missing/invalid proof is UNKNOWN. A missing recovery ACK never grants permission.
  const plan = (RUST_EMBED_SENDER_BUILD ? await rustSenderDecision("senderAvailabilityPlan", planInput) : null)
    ?? availabilityPlan(planInput);
  let canonical: Awaited<ReturnType<typeof readEquivalentCanonicalHead>> | null = null;
  let precondition: CanonicalPrecondition | undefined;
  let allowWrapperWrites = !readOnly;
  // The plan validated this revision for the read_current_revision/read_historical outcomes.
  const revision = () => (reply as { results: Array<{ canonical_revision: CanonicalRevision }> })
    .results[0].canonical_revision;
  switch (plan.outcome) {
    case "malformed": throw malformed("availability reply");
    case "unknown_identity": throw new Error("Canonical embed availability identity is unknown.");
    case "recovery_pending": throw new CanonicalEmbedRecoveryPending();
    case "conflict": throw new CanonicalEmbedConflict(plan.code);
    case "read_current":
      // Read-only equivalence can prove durable canonical bytes even when
      // availability cannot grant a write capability (notably child embeds).
      canonical = await readEquivalentCurrentOrSupersededChild(head);
      allowWrapperWrites = plan.allow_wrapper_writes;
      break;
    case "read_historical":
      canonical = await readEquivalentHistoricalHead(head, revision());
      precondition = plan.precondition;
      allowWrapperWrites = plan.allow_wrapper_writes;
      break;
    case "read_current_revision":
      canonical = await readEquivalentCanonicalHead(head, false, revision());
      precondition = plan.precondition;
      allowWrapperWrites = plan.allow_wrapper_writes;
      break;
    case "read_advance": {
      // Rust decided: the head is either already the equivalent N+1 (adopt) or
      // the child at N, written next under the Rust-built precondition.
      const read = await readEquivalentCanonicalHead(head, false, undefined, true);
      if (read.advancePrecondition) precondition = read.advancePrecondition;
      else canonical = read;
      allowWrapperWrites = plan.allow_wrapper_writes;
      break;
    }
    case "write":
      precondition = plan.precondition;
      allowWrapperWrites = plan.allow_wrapper_writes;
      break;
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
      if (error instanceof CanonicalEmbedWriteRejected) {
        const failure = failureFacts(error);
        const verdict = (RUST_EMBED_SENDER_BUILD ? await rustSenderDecision("senderFailure", failure) : null)
          ?? classifyFailure(failure);
        if (verdict.reconcile) {
          // Another browser/recovery consumer may have saved the same result with
          // another AES nonce. Refresh authority and prove equivalence without
          // retrying a write or replacing the original queued ciphertext.
          const reconciliation = { ...operation, failure_code: error.reason };
          await chatDB.addPendingEmbedOperation(reconciliation);
          return persistCanonicalEmbedOperation(reconciliation, true);
        }
      }
      throw error;
    }
    const expectedDigest = await computeSHA256(head.encrypted_content);
    const headCheck: ReceiptInput = { kind: "head", receipt: headReceipt, embed_id: head.embed_id, expected_digest: expectedDigest };
    if (!receiptOk(headCheck, RUST_EMBED_SENDER_BUILD ? await rustSenderDecision("senderReceipt", headCheck) : null)) {
      throw new Error("Canonical embed receipt did not match its ciphertext.");
    }
  }
  const keys = operation.store_embed_keys_payload?.keys ?? [];
  if (canonical && keys.length > 0) await verifyQueuedWrappersForCanonicalHead(head, keys, canonical);
  const keysInput = {
    key_types: keys.map((wrapper) => wrapper.key_type ?? null),
    verified_key_types: canonical ? [...canonical.verifiedKeyTypes] : null,
    allow_wrapper_writes: allowWrapperWrites, requested_version: requestedVersion,
    canonical_version: canonical ? (canonical.embed.version_number as number | null | undefined) ?? null : null,
  };
  const keyPlan = (RUST_EMBED_SENDER_BUILD ? await rustSenderDecision("senderMissingKeys", keysInput) : null)
    ?? planMissingKeys(keysInput);
  if (keyPlan.outcome === "recovery_pending") throw new CanonicalEmbedRecoveryPending();
  if (keyPlan.outcome === "send") {
    if (keyPlan.missing.some((index) => !Number.isInteger(index) || index < 0 || index >= keys.length)) {
      throw malformed("missing key plan");
    }
    const missingKeys = keyPlan.missing.map((index) => keys[index]);
    const keyReceipt = await sendWithReceipt("store_embed_keys", "store_embed_keys_confirmed", { keys: missingKeys,
      operation_id: operation.operation_id });
    const keysCheck: ReceiptInput = { kind: "keys", receipt: keyReceipt, count: missingKeys.length };
    if (!receiptOk(keysCheck, RUST_EMBED_SENDER_BUILD ? await rustSenderDecision("senderReceipt", keysCheck) : null)) {
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
      app_id: (canonical.embed.app_id as string | undefined) ?? head.app_id,
      skill_id: (canonical.embed.skill_id as string | undefined) ?? head.skill_id,
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
    const failure = failureFacts(error);
    const { settle } = (RUST_EMBED_SENDER_BUILD ? await rustSenderDecision("senderFailure", failure) : null)
      ?? classifyFailure(failure);
    if (settle.outcome === "waiting") return { status: "waiting", operation_id: operation.operation_id };
    const state = settle.outcome;
    const denied = state === "denied";
    const failure_code = settle.failure_code;
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
  const check: ReceiptInput = { kind: "keys", receipt, count: payload.keys.length };
  if (!receiptOk(check, RUST_EMBED_SENDER_BUILD ? await rustSenderDecision("senderReceipt", check) : null)) {
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
    throw new Error("Cannot confirm encrypted embed history while disconnected.");
  }
  const receipt = await sendWithReceipt("store_embed_diff", "store_embed_diff_confirmed",
    payload as unknown as Record<string, unknown>);
  const expected = await computeSHA256(JSON.stringify([
    payload.encrypted_snapshot ?? null, payload.encrypted_patch ?? null,
  ]));
  const check: ReceiptInput = {
    kind: "diff", receipt, embed_id: payload.embed_id, version_number: payload.version_number, expected_digest: expected,
  };
  if (!receiptOk(check, RUST_EMBED_SENDER_BUILD ? await rustSenderDecision("senderReceipt", check) : null)) {
    throw new Error("Canonical embed history receipt did not match the submitted version.");
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

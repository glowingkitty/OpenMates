/**
 * chatSyncServiceHandlersRecovery.ts - Sealed completion recovery handlers.
 *
 * Claims server-sealed completion jobs, decrypts them with chat-derived recovery
 * keys, and commits only chat-key-encrypted assistant messages. Plaintext remains
 * transient in browser memory and never crosses the durable server boundary.
 */
import type { ChatSynchronizationService } from "./chatSyncService";
import type { Chat, Message, StoreEmbedPayload, StoreEmbedDiffPayload } from "../types/chat";
import type { EmbedType } from "../message_parsing/types";
import {
  deriveChatCompletionRecoveryKeypair,
  openChatCompletionRecoveryEnvelope,
  openRecoveryOutputEnvelope,
  type RecoveryOutputKind,
  type ChatCompletionRecoveryEnvelope,
} from "../utils/chatCompletionRecovery";
import { chatDB } from "./db";
import { getApiEndpoint } from "../config/api";
import { userDB } from "./userDB";
import { chatKeyManager } from "./encryption/ChatKeyManager";
import { ensureChatKeySafeForWrite } from "./chatKeyWriteGuard";
import { webSocketService } from "./websocketService";
import { aiTypingStore } from "../stores/aiTypingStore";
import { notificationStore } from "../stores/notificationStore";
import { unreadMessagesStore } from "../stores/unreadMessagesStore";
import { isChatVisiblyActive } from "./chatNotificationVisibility";
import {
  encryptChatKeyWithMasterKey, deriveEmbedKeyFromChatKey,
  encryptWithEmbedKey, decryptWithEmbedKey, wrapEmbedKeyWithMasterKey, wrapEmbedKeyWithChatKey,
  unwrapEmbedKeyWithMasterKey, unwrapEmbedKeyWithChatKey,
} from "./encryption/MetadataEncryptor";
import { encryptWithChatKey } from "./encryption/MessageEncryptor";
import { computeSHA256 } from "../message_parsing/utils";
import { reconstructEncryptedVersionRows, type EmbedVersionMeta } from "./embedDiffStore";
import { catalogContextFromSealedEmbed, historySourceFromSealedEmbed, isUnwrittenInitialDiffRead } from "./recoveryEmbedSource";
import { refreshRecoveryChatVersion } from "./chatRecoveryVersionRefresh";
import {
  hasAcknowledgedRecoveredEmbed, markAcknowledgedRecoveredEmbed, withCanonicalEmbedWrite,
  type CanonicalEmbedWriteLease,
} from "./canonicalEmbedWriteCoordinator";

const CHAT_RECOVERY_PROTOCOL_VERSION = 1;
const CHAT_RECOVERY_EVENT_TIMEOUT_MS = 20_000;
const CHAT_RECOVERY_EVENT_MAX_RETRIES = 3;
const CHAT_RECOVERY_LEASE_EXPIRY_MS = 60_000;
const CHAT_RECOVERY_RETRY_DELAY_MS = CHAT_RECOVERY_LEASE_EXPIRY_MS + 1_000;
const INITIAL_SYNC_POLL_MS = 100;
const RECOVERY_PREREQUISITE_POLL_MS = 250;
const RECOVERY_PREREQUISITE_TIMEOUT_MS = 120_000;
const RECOVERY_RETRYABLE_ERROR_CODES = new Set(["lease_conflict"]);
const RECOVERY_STALE_TERMINAL_ERROR_CODES = new Set(["recovery_job_not_found"]);
const recoveryJobsInProgress = new Set<string>();
const recoveryOutputsInProgress = new Set<string>();

function buildRecoveryMessagePreview(content: string): string {
  const plainText = content
    .replace(/#{1,6}\s+/g, "")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\*(.+?)\*/g, "$1")
    .replace(/`{1,3}[^`]*`{1,3}/g, "")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/!\[[^\]]*\]\([^)]+\)/g, "")
    .replace(/>\s+/g, "")
    .replace(/[-*+]\s+/g, "")
    .replace(/\n+/g, " ")
    .trim();

  if (!plainText) return "New AI response ready";
  return plainText.length > 120 ? `${plainText.substring(0, 120)}...` : plainText;
}

class RecoveryEventTimeoutError extends Error {}

class RecoveryStaleJobError extends Error {}

class RecoveryProtocolError extends Error {
  constructor(
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

interface AvailableRecoveryJob {
  job_id: string;
  chat_id: string;
  turn_id: string;
  assistant_message_id: string;
  chat_key_version: number;
}

interface AvailableRecoveryOutput {
  record_id: string;
  root_chat_id: string;
  root_hashed_team_id?: string | null;
  target_chat_id: string;
  turn_id: string;
  subject_id: string;
  output_kind: RecoveryOutputKind;
  output_version: number;
  chat_key_version: number;
  message_role?: "user" | "assistant" | null;
}

interface RecoveryPrerequisites {
  chat: Chat;
  chatKey: Uint8Array;
}

interface RecoveredEmbedReceipt {
  digest: string;
  source: "head" | "version_row";
  embed?: Record<string, unknown>;
}

export async function sendEmbedStoreWithReceipt(
  eventType: "store_embed" | "store_embed_diff",
  confirmedType: "store_embed_confirmed" | "store_embed_diff_confirmed",
  payload: Record<string, unknown>, embedId: string, version: number | undefined,
  recoveryRecordId: string,
): Promise<RecoveredEmbedReceipt> {
  const requestId = crypto.randomUUID();
  let stop = () => {};
  const confirmation = new Promise<RecoveredEmbedReceipt>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      stop();
      reject(new RecoveryEventTimeoutError(`Canonical ${eventType} confirmation timed out.`));
    }, CHAT_RECOVERY_EVENT_TIMEOUT_MS);
    const onConfirmed = (raw: unknown) => {
      const event = raw as Record<string, unknown>;
      if (event.request_id !== requestId || event.embed_id !== embedId
        || (version !== undefined && event.version_number !== version)) return;
      stop();
      const source = event.canonical_source;
      const digest = event.canonical_digest;
      const expectedSource = eventType === "store_embed" ? "head" : "version_row";
      if (source !== expectedSource || typeof digest !== "string" || !/^[0-9a-f]{64}$/.test(digest)) {
        reject(new Error("Canonical embed write receipt was incomplete."));
      } else resolve({ digest, source: source as "head" | "version_row" });
    };
    const onError = (raw: unknown) => {
      const event = raw as Record<string, unknown>;
      if (event.request_id !== requestId || typeof event.code !== "string") return;
      stop();
      reject(new RecoveryProtocolError(event.code, `Canonical ${eventType} storage was rejected.`));
    };
    stop = () => {
      window.clearTimeout(timer);
      webSocketService.off(confirmedType, onConfirmed);
      webSocketService.off("error", onError);
    };
    webSocketService.on(confirmedType, onConfirmed);
    webSocketService.on("error", onError);
  });
  try {
    await webSocketService.sendMessage(eventType, {
      ...payload, request_id: requestId, recovery_record_id: recoveryRecordId,
    });
    return await confirmation;
  } catch (error) {
    stop();
    throw error;
  }
}

async function sendEmbedKeysWithReceipt(
  keys: Array<Record<string, unknown>>, recoveryRecordId: string,
): Promise<void> {
  const requestId = crypto.randomUUID();
  let stop = () => {};
  const confirmation = new Promise<void>((resolve, reject) => {
    const timer = window.setTimeout(() => {
      stop();
      reject(new RecoveryEventTimeoutError("Canonical embed key confirmation timed out."));
    }, CHAT_RECOVERY_EVENT_TIMEOUT_MS);
    const onConfirmed = (raw: unknown) => {
      const event = raw as Record<string, unknown>;
      if (event.request_id !== requestId) return;
      stop();
      if (event.failed_count !== 0 || event.created_count !== keys.length
        || event.requested_count !== keys.length) {
        reject(new Error("Canonical embed key storage was incomplete."));
      } else resolve();
    };
    stop = () => {
      window.clearTimeout(timer);
      webSocketService.off("store_embed_keys_confirmed", onConfirmed);
    };
    webSocketService.on("store_embed_keys_confirmed", onConfirmed);
  });
  try {
    await webSocketService.sendMessage("store_embed_keys", {
      keys, request_id: requestId, recovery_record_id: recoveryRecordId,
    });
    await confirmation;
  } catch (error) {
    stop();
    throw error;
  }
}

async function verifyExactCanonicalEmbedWrappers(
  output: Pick<AvailableRecoveryOutput, "target_chat_id">, keySubject: string,
  embedKey: Uint8Array, chatKey: Uint8Array,
): Promise<Array<Record<string, unknown>>> {
  const chat = await chatDB.getChat(output.target_chat_id);
  const query = chat?.team_id ? `?team_id=${encodeURIComponent(chat.team_id)}` : "";
  const response = await fetch(getApiEndpoint(
    `/v1/embeds/chats/${encodeURIComponent(output.target_chat_id)}/embeds/${encodeURIComponent(keySubject)}${query}`,
  ), { credentials: "include" });
  if (!response.ok) throw new Error(`Canonical embed wrapper read failed (${response.status}).`);
  const page = await response.json() as { embed_keys?: Array<Record<string, unknown>> };
  const hashedSubject = await computeSHA256(keySubject);
  const hashedChat = await computeSHA256(output.target_chat_id);
  const wrappers = (page.embed_keys ?? []).filter((row) => row.hashed_embed_id === hashedSubject
    && (row.key_type === "master" || row.key_type === "chat"));
  if (wrappers.length !== 2
    || wrappers.filter((row) => row.key_type === "master" && row.hashed_chat_id == null).length !== 1
    || wrappers.filter((row) => row.key_type === "chat" && row.hashed_chat_id === hashedChat).length !== 1) {
    throw new Error("Canonical recovery embed wrappers were not exact.");
  }
  for (const wrapper of wrappers) {
    if (typeof wrapper.encrypted_embed_key !== "string") {
      throw new Error("Canonical recovery embed wrapper ciphertext was missing.");
    }
    const unwrapped = wrapper.key_type === "master"
      ? await unwrapEmbedKeyWithMasterKey(wrapper.encrypted_embed_key, keySubject)
      : await unwrapEmbedKeyWithChatKey(wrapper.encrypted_embed_key, chatKey, {
        embedId: keySubject, chatId: output.target_chat_id,
      });
    if (!unwrapped || unwrapped.length !== embedKey.length
      || unwrapped.some((value, index) => value !== embedKey[index])) {
      throw new Error("Canonical recovery embed wrapper did not open to the expected key.");
    }
  }
  return wrappers;
}

async function readRecoveredCanonicalEmbed(
  output: Pick<AvailableRecoveryOutput, "target_chat_id" | "subject_id" | "output_version">,
  expectedContent: string, expectedType: string,
  expectedMessageId: string, embedKey: Uint8Array,
): Promise<RecoveredEmbedReceipt | null> {
  const chat = await chatDB.getChat(output.target_chat_id);
  const query = chat?.team_id ? `?team_id=${encodeURIComponent(chat.team_id)}` : "";
  const response = await fetch(getApiEndpoint(
    `/v1/embeds/chats/${encodeURIComponent(output.target_chat_id)}/embeds/${encodeURIComponent(output.subject_id)}${query}`,
  ), { credentials: "include" });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`Canonical embed read failed (${response.status}).`);
  const page = await response.json() as { embed?: Record<string, unknown> };
  const embed = page.embed;
  if (!embed || embed.embed_id !== output.subject_id) throw new Error("Canonical embed identity mismatch.");
  if (embed.hashed_chat_id !== await computeSHA256(output.target_chat_id)) {
    throw new Error("Canonical embed chat identity mismatch.");
  }
  if (embed.hashed_message_id !== await computeSHA256(expectedMessageId)) {
    throw new Error("Canonical embed message identity mismatch.");
  }
  if (typeof embed.encrypted_type !== "string"
    || await decryptWithEmbedKey(embed.encrypted_type, embedKey) !== expectedType) {
    throw new Error("Canonical embed type identity mismatch.");
  }
  const version = Number(embed.version_number || 1);
  if (version > output.output_version) {
    const versionQuery = new URLSearchParams({ capability: "bounded-v1", chat_id: output.target_chat_id });
    if (chat?.team_id) versionQuery.set("team_id", chat.team_id);
    const versionResponse = await fetch(getApiEndpoint(
      `/v1/embeds/${encodeURIComponent(output.subject_id)}/versions/${output.output_version}?${versionQuery}`,
    ), { credentials: "include" });
    if (!versionResponse.ok) throw new Error(`Canonical historical embed read failed (${versionResponse.status}).`);
    const history = await versionResponse.json() as {
      embed_id?: string; version_number?: number; rows?: EmbedVersionMeta[];
    };
    if (history.embed_id !== output.subject_id || history.version_number !== output.output_version
      || !Array.isArray(history.rows)) throw new Error("Canonical historical embed identity mismatch.");
    const last = history.rows[history.rows.length - 1];
    if (!last || last.version_number !== output.output_version
      || (!last.encrypted_snapshot && !last.encrypted_patch)) {
      throw new Error("Canonical historical embed row is missing.");
    }
    const plaintext = await reconstructEncryptedVersionRows(history.rows, embedKey);
    if (plaintext !== await historySourceFromSealedEmbed(expectedContent, expectedType)) {
      throw new Error("Canonical historical embed content differs from sealed output.");
    }
    return {
      digest: await computeSHA256(JSON.stringify([
        last.encrypted_snapshot ?? null, last.encrypted_patch ?? null,
      ])), source: "version_row", embed,
    };
  }
  if (version < output.output_version || typeof embed.encrypted_content !== "string") return null;
  const plaintext = await decryptWithEmbedKey(embed.encrypted_content, embedKey);
  if (plaintext !== expectedContent) throw new Error("Canonical embed content differs from sealed recovery output.");
  return { digest: await computeSHA256(embed.encrypted_content), source: "head", embed };
}

/** Reuse an ACKed recovery head; a late normal event must not replace it or regress its version. */
export async function reuseAcknowledgedRecoveredEmbed(
  lease: CanonicalEmbedWriteLease,
  data: {
    embed_id: string; chat_id: string; message_id: string; content: string;
    type: string; version_number?: number; parent_embed_id?: string | null;
    app_id?: string; skill_id?: string;
  },
  embedKey: Uint8Array, chatKey: Uint8Array,
): Promise<boolean> {
  const version = data.version_number ?? 1;
  if (!hasAcknowledgedRecoveredEmbed(lease, data.chat_id, version)) return false;
  const identity = {
    subject_id: data.embed_id, target_chat_id: data.chat_id, output_version: version,
  };
  const canonical = await readRecoveredCanonicalEmbed(
    identity, data.content, data.type, data.message_id, embedKey,
  );
  if (!canonical?.embed || typeof canonical.embed.encrypted_content !== "string"
    || typeof canonical.embed.encrypted_type !== "string") {
    throw new Error("Acknowledged recovery head was unavailable for ordinary reuse.");
  }
  const wrappers = await verifyExactCanonicalEmbedWrappers(
    identity, data.parent_embed_id || data.embed_id, embedKey, chatKey,
  );
  const { embedStore } = await import("./embedStore");
  await embedStore.storeEmbedKeys(wrappers.map((row) => ({
    hashed_embed_id: row.hashed_embed_id as string,
    key_type: row.key_type as "master" | "chat",
    hashed_chat_id: (row.hashed_chat_id as string) || null,
    encrypted_embed_key: row.encrypted_embed_key as string,
    hashed_user_id: row.hashed_user_id as string,
    created_at: row.created_at as number,
  })));
  const embed = canonical.embed;
  await embedStore.putEncrypted(`embed:${data.embed_id}`, {
    embed_id: data.embed_id, encrypted_content: embed.encrypted_content,
    encrypted_type: embed.encrypted_type, encrypted_text_preview: embed.encrypted_text_preview,
    status: embed.status, hashed_chat_id: embed.hashed_chat_id,
    hashed_message_id: embed.hashed_message_id, hashed_user_id: embed.hashed_user_id,
    embed_ids: embed.embed_ids, parent_embed_id: embed.parent_embed_id,
    version_number: embed.version_number, is_private: embed.is_private,
    is_shared: embed.is_shared, createdAt: embed.created_at, updatedAt: embed.updated_at,
  }, data.type as EmbedType, undefined,
  await catalogContextFromSealedEmbed(data.content, data.app_id, data.skill_id) ?? undefined);
  return true;
}

async function readRecoveredCanonicalDiff(
  output: AvailableRecoveryOutput, expectedSnapshot: string | null,
  expectedPatch: string | null, embedKey: Uint8Array,
): Promise<string | null> {
  const chat = await chatDB.getChat(output.target_chat_id);
  const query = new URLSearchParams({ capability: "bounded-v1", chat_id: output.target_chat_id });
  if (chat?.team_id) query.set("team_id", chat.team_id);
  const response = await fetch(getApiEndpoint(
    `/v1/embeds/${encodeURIComponent(output.subject_id)}/versions/${output.output_version}?${query}`,
  ), { credentials: "include" });
  if (response.status === 404) return null;
  if (!response.ok) {
    const error = await response.json().catch(() => null) as { detail?: unknown } | null;
    if (isUnwrittenInitialDiffRead(response.status, error?.detail, output.output_version)) return null;
    const detail = typeof error?.detail === "string" ? error.detail.slice(0, 80) : "unknown";
    throw new Error(`Canonical diff read failed (${response.status}: ${detail}).`);
  }
  const page = await response.json() as { rows?: Array<Record<string, unknown>> };
  const row = page.rows?.find((candidate) => candidate.version_number === output.output_version);
  if (!row) return null;
  const snapshot = typeof row.encrypted_snapshot === "string" ? row.encrypted_snapshot : null;
  const patch = typeof row.encrypted_patch === "string" ? row.encrypted_patch : null;
  if ((snapshot ? await decryptWithEmbedKey(snapshot, embedKey) : null) !== expectedSnapshot
    || (patch ? await decryptWithEmbedKey(patch, embedKey) : null) !== expectedPatch) {
    throw new Error("Canonical diff content differs from sealed recovery output.");
  }
  return computeSHA256(JSON.stringify([snapshot, patch]));
}

async function persistRecoveredEmbed(
  output: AvailableRecoveryOutput, content: Record<string, unknown>,
  chatKey: Uint8Array, ownerId: string,
): Promise<RecoveredEmbedReceipt> {
  if (content.embed_id !== output.subject_id) throw new Error("Recovered embed identity mismatch.");
  const embedId = output.subject_id;
  const parentEmbedId = typeof content.parent_embed_id === "string" ? content.parent_embed_id : null;
  const embedKey = await deriveEmbedKeyFromChatKey(chatKey, parentEmbedId || embedId);
  const ownerHash = await computeSHA256(ownerId);
  if (output.output_kind === "diff") {
    if (content.version_number !== output.output_version) throw new Error("Recovered diff version mismatch.");
    const expectedSnapshot = typeof content.snapshot === "string" ? content.snapshot : null;
    const expectedPatch = typeof content.patch === "string" ? content.patch : null;
    const existingDigest = await readRecoveredCanonicalDiff(output, expectedSnapshot, expectedPatch, embedKey);
    if (existingDigest) return { digest: existingDigest, source: "version_row" };
    const snapshot = expectedSnapshot ? await encryptWithEmbedKey(expectedSnapshot, embedKey) : null;
    const patch = expectedPatch ? await encryptWithEmbedKey(expectedPatch, embedKey) : null;
    if ((output.output_version === 1 && (!snapshot || patch))
      || (output.output_version > 1 && !patch)) throw new Error("Recovered diff has no required snapshot or patch.");
    const diff: StoreEmbedDiffPayload = {
      embed_id: embedId, version_number: output.output_version,
      encrypted_snapshot: snapshot, encrypted_patch: patch,
      hashed_user_id: ownerHash,
      created_at: typeof content.created_at === "number" ? content.created_at : Math.floor(Date.now() / 1000),
    };
    const writeReceipt = await sendEmbedStoreWithReceipt("store_embed_diff", "store_embed_diff_confirmed",
      diff as unknown as Record<string, unknown>, embedId, output.output_version, output.record_id);
    const savedDigest = await readRecoveredCanonicalDiff(output, expectedSnapshot, expectedPatch, embedKey);
    if (!savedDigest) throw new Error("Canonical recovered diff remained unavailable after store receipt.");
    if (writeReceipt.source !== "version_row" || writeReceipt.digest !== savedDigest) {
      throw new Error("Canonical recovered diff receipt did not match its reread.");
    }
    return { digest: savedDigest, source: "version_row" };
  }
  if (content.version_number !== undefined && content.version_number !== output.output_version) {
    throw new Error("Recovered embed version mismatch.");
  }
  if (typeof content.content !== "string" || typeof content.type !== "string"
    || typeof content.message_id !== "string") throw new Error("Recovered embed payload was invalid.");
  if (content.chat_id !== output.target_chat_id) throw new Error("Recovered embed chat identity mismatch.");
  const targetChat = await chatDB.getChat(output.target_chat_id);
  if (!targetChat) throw new Error("Recovered embed target chat was unavailable.");
  const catalog = await catalogContextFromSealedEmbed(content.content, content.app_id, content.skill_id);
  const existingDigest = await readRecoveredCanonicalEmbed(
    output, content.content, content.type, content.message_id, embedKey,
  );
  const encryptedContent = existingDigest ? null : await encryptWithEmbedKey(content.content, embedKey);
  const encryptedType = await encryptWithEmbedKey(content.type, embedKey);
  if ((!encryptedContent && !existingDigest) || !encryptedType) throw new Error("Recovered embed encryption failed.");
  const encryptedPreview = typeof content.text_preview === "string"
    ? await encryptWithEmbedKey(content.text_preview, embedKey) : undefined;
  const storePayload: StoreEmbedPayload & {
    chat_id: string; team_id: string | null; app_id?: string; skill_id?: string;
  } = {
    embed_id: embedId, encrypted_content: encryptedContent as string, encrypted_type: encryptedType,
    chat_id: output.target_chat_id, team_id: targetChat.team_id ?? null,
    ...(catalog ?? {}),
    encrypted_text_preview: encryptedPreview || undefined,
    status: "finished", hashed_chat_id: await computeSHA256(output.target_chat_id),
    hashed_message_id: await computeSHA256(content.message_id), hashed_user_id: ownerHash,
    version_number: output.output_version,
    parent_embed_id: parentEmbedId || undefined,
    embed_ids: Array.isArray(content.embed_ids) ? content.embed_ids as string[] : undefined,
    is_private: content.is_private === true, is_shared: content.is_shared === true,
    created_at: typeof content.createdAt === "number" ? content.createdAt : Math.floor(Date.now() / 1000),
    updated_at: typeof content.updatedAt === "number" ? content.updatedAt : Math.floor(Date.now() / 1000),
  };
  const writeReceipt = !existingDigest
    ? await sendEmbedStoreWithReceipt("store_embed", "store_embed_confirmed",
      storePayload as unknown as Record<string, unknown>, embedId, undefined, output.record_id)
    : null;
  if (!parentEmbedId) {
    const wrappedMaster = await wrapEmbedKeyWithMasterKey(embedKey);
    const wrappedChat = await wrapEmbedKeyWithChatKey(embedKey, chatKey);
    if (!wrappedMaster || !wrappedChat) throw new Error("Recovered embed key wrapping failed.");
    const hashedEmbedId = await computeSHA256(embedId);
    await sendEmbedKeysWithReceipt([
      { hashed_embed_id: hashedEmbedId, key_type: "master", hashed_chat_id: null,
        encrypted_embed_key: wrappedMaster, hashed_user_id: ownerHash, created_at: Math.floor(Date.now() / 1000) },
      { hashed_embed_id: hashedEmbedId, key_type: "chat", hashed_chat_id: await computeSHA256(output.target_chat_id),
        encrypted_embed_key: wrappedChat, hashed_user_id: ownerHash, created_at: Math.floor(Date.now() / 1000) },
    ], output.record_id);
  }
  const savedDigest = await readRecoveredCanonicalEmbed(
    output, content.content, content.type, content.message_id, embedKey,
  );
  if (!savedDigest) throw new Error("Canonical recovered embed remained unavailable after store receipt.");
  if (writeReceipt && (writeReceipt.source !== savedDigest.source || writeReceipt.digest !== savedDigest.digest)) {
    throw new Error("Canonical recovered embed receipt did not match its reread.");
  }
  await verifyExactCanonicalEmbedWrappers(output, parentEmbedId || embedId, embedKey, chatKey);
  return savedDigest;
}

function encodeRecoveryChatKey(bytes: Uint8Array): string {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) binary += String.fromCharCode(bytes[index]);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function waitForInitialSync(serviceInstance: ChatSynchronizationService): Promise<void> {
  const deadline = Date.now() + RECOVERY_PREREQUISITE_TIMEOUT_MS;
  while (!serviceInstance.hasCompletedInitialSync_FOR_HANDLERS_ONLY) {
    if (Date.now() >= deadline) {
      throw new Error("Recovery job processing timed out waiting for initial chat sync.");
    }
    await new Promise((resolve) => window.setTimeout(resolve, INITIAL_SYNC_POLL_MS));
  }
}

async function waitForRecoveryPrerequisites(job: AvailableRecoveryJob): Promise<RecoveryPrerequisites | null> {
  const deadline = Date.now() + RECOVERY_PREREQUISITE_TIMEOUT_MS;
  while (Date.now() < deadline) {
    const chat = await chatDB.getChat(job.chat_id);
    if (!chat) {
      await new Promise((resolve) => window.setTimeout(resolve, RECOVERY_PREREQUISITE_POLL_MS));
      continue;
    }

    const chatKey = await chatKeyManager.getKey(job.chat_id);
    if (!chatKey) {
      await new Promise((resolve) => window.setTimeout(resolve, RECOVERY_PREREQUISITE_POLL_MS));
      continue;
    }

    if (chat.user_id) return { chat, chatKey };

    const userProfile = await userDB.getUserProfile();
    if (userProfile?.user_id) {
      const hydratedChat = { ...chat, user_id: userProfile.user_id };
      await chatDB.updateChat(hydratedChat);
      return { chat: hydratedChat, chatKey };
    }

    await new Promise((resolve) => window.setTimeout(resolve, RECOVERY_PREREQUISITE_POLL_MS));
  }
  return null;
}

function waitForRecoveryEvent(
  type: string,
  jobId: string,
  requestId: string,
  timeoutMs: number,
): {
  promise: Promise<Record<string, unknown>>;
  cancel: (error: unknown) => void;
} {
  let cancel = (_error: unknown): void => {};
  const promise = new Promise<Record<string, unknown>>((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      cleanup();
      reject(new RecoveryEventTimeoutError(`${type} timed out for recovery job ${jobId}`));
    }, timeoutMs);
    const handleEvent = (payload: unknown) => {
      const event = payload as Record<string, unknown>;
      if (
        (event.job_id !== jobId && event.record_id !== jobId) ||
        event.request_id !== requestId
      ) return;
      cleanup();
      resolve(event);
    };
    const handleError = (payload: unknown) => {
      const event = payload as Record<string, unknown>;
      if (
        event.job_id !== jobId ||
        event.request_id !== requestId ||
        typeof event.code !== "string"
      ) return;
      if (RECOVERY_STALE_TERMINAL_ERROR_CODES.has(event.code)) {
        cleanup();
        reject(new RecoveryStaleJobError(
          typeof event.message === "string" ? event.message : `${type} referenced a stale recovery job.`,
        ));
        return;
      }
      if (RECOVERY_RETRYABLE_ERROR_CODES.has(event.code)) return;
      cleanup();
      reject(new RecoveryProtocolError(
        event.code,
        typeof event.message === "string" ? event.message : `${type} was rejected.`,
      ));
    };
    const cleanup = () => {
      window.clearTimeout(timeout);
      webSocketService.off(type, handleEvent);
      webSocketService.off("error", handleError);
    };
    cancel = (error: unknown) => {
      cleanup();
      reject(error);
    };
    webSocketService.on(type, handleEvent);
    webSocketService.on("error", handleError);
  });
  return { promise, cancel };
}

async function storeRecoveredCheckpoint(
  output: AvailableRecoveryOutput,
  content: Record<string, unknown>,
  encryptedSummary: string,
): Promise<void> {
  if (content.summary_message_id !== output.subject_id
    || typeof content.compressed_up_to_timestamp !== "number"
    || typeof content.compressed_up_to_message_id !== "string"
    || !content.compressed_up_to_message_id
    || typeof content.compressed_message_count !== "number"
    || typeof content.summary_token_estimate !== "number") {
    throw new Error("Recovery checkpoint identity or boundary was invalid.");
  }
  const confirmation = new Promise<Record<string, unknown>>((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      webSocketService.off("chat_compression_checkpoint_stored", onStored);
      reject(new RecoveryEventTimeoutError("Checkpoint canonical persistence timed out."));
    }, CHAT_RECOVERY_EVENT_TIMEOUT_MS);
    const onStored = (payload: unknown) => {
      const event = payload as Record<string, unknown>;
      const checkpoint = event.checkpoint as Record<string, unknown> | undefined;
      if (event.chat_id !== output.target_chat_id || checkpoint?.id !== output.subject_id) return;
      window.clearTimeout(timeout);
      webSocketService.off("chat_compression_checkpoint_stored", onStored);
      resolve(checkpoint);
    };
    webSocketService.on("chat_compression_checkpoint_stored", onStored);
  });
  await webSocketService.sendMessage("store_chat_compression_checkpoint", {
    chat_id: output.target_chat_id,
    checkpoint_id: output.subject_id,
    encrypted_summary: encryptedSummary,
    compressed_up_to_timestamp: content.compressed_up_to_timestamp,
    compressed_up_to_message_id: content.compressed_up_to_message_id ?? null,
    covered_message_ids: content.covered_message_ids ?? null,
    compressed_message_count: content.compressed_message_count,
    summary_token_estimate: content.summary_token_estimate,
    key_version: output.chat_key_version,
    created_at: Math.floor(Date.now() / 1000),
  });
  const checkpoint = await confirmation;
  if (checkpoint.encrypted_summary !== encryptedSummary
    || (checkpoint.compressed_up_to_message_id ?? null) !== (content.compressed_up_to_message_id ?? null)
    || JSON.stringify(checkpoint.covered_message_ids ?? null) !== JSON.stringify(content.covered_message_ids ?? null)) {
    throw new Error("Canonical checkpoint did not match recovered output.");
  }
  const acknowledged = await requestRecoveryEvent(
    "recovery_output_checkpoint_acknowledged", "recovery_output_ack_checkpoint", output.record_id,
    {
      protocol_version: CHAT_RECOVERY_PROTOCOL_VERSION, record_id: output.record_id,
      encrypted_summary: encryptedSummary,
      compressed_up_to_message_id: content.compressed_up_to_message_id,
      covered_message_ids: content.covered_message_ids ?? null,
    },
  );
  if (acknowledged.state !== "ACKNOWLEDGED") throw new Error("Recovery checkpoint was not acknowledged.");
}

async function requestRecoveryEvent(
  responseType: string,
  requestType: string,
  jobId: string,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  let lastTimeout: RecoveryEventTimeoutError | null = null;
  for (let retry = 0; retry <= CHAT_RECOVERY_EVENT_MAX_RETRIES; retry += 1) {
    const requestId = crypto.randomUUID();
    const waiter = waitForRecoveryEvent(
      responseType,
      jobId,
      requestId,
      CHAT_RECOVERY_EVENT_TIMEOUT_MS + (retry * CHAT_RECOVERY_RETRY_DELAY_MS),
    );
    if (retry > 0) {
      await new Promise((resolve) => {
        window.setTimeout(resolve, CHAT_RECOVERY_RETRY_DELAY_MS);
      });
    }
    try {
      await webSocketService.sendMessage(requestType, {
        ...payload,
        request_id: requestId,
      });
    } catch (error) {
      waiter.cancel(error);
    }
    try {
      return await waiter.promise;
    } catch (error) {
      if (!(error instanceof RecoveryEventTimeoutError)) throw error;
      lastTimeout = error;
      if (retry === CHAT_RECOVERY_EVENT_MAX_RETRIES) throw error;
    }
  }
  throw lastTimeout ?? new Error(`Recovery request failed for job ${jobId}`);
}

export async function handleRecoveryJobsAvailableImpl(
  serviceInstance: ChatSynchronizationService,
  payload: { jobs?: AvailableRecoveryJob[] },
): Promise<void> {
  await waitForInitialSync(serviceInstance);
  await Promise.allSettled((payload.jobs ?? []).map(async (job) => {
    if (!job.job_id || recoveryJobsInProgress.has(job.job_id)) return;
    recoveryJobsInProgress.add(job.job_id);
    try {
      // A local synced/delivered row can still be browser-only if the user logs out
      // before sealed recovery reaches terminal persistence. The server job is the
      // durable idempotency boundary, so do not skip an available job based on IDB.
      await serviceInstance.requestChatContentBatch_FOR_HANDLERS_ONLY([job.chat_id]);
      const prerequisites = await waitForRecoveryPrerequisites(job);
      if (!prerequisites) {
        console.warn(
          `[ChatSyncService:Recovery] Recovery job ${job.job_id} prerequisites did not hydrate in time.`,
        );
        return;
      }
      const { chat, chatKey } = prerequisites;
      if (!(
        await ensureChatKeySafeForWrite(job.chat_id, chatKey, "completion recovery", {
          reportFailure: false,
        })
      )) return;

      const claim = await requestRecoveryEvent(
        "recovery_job_claimed",
        "recovery_job_claim",
        job.job_id,
        {
          protocol_version: CHAT_RECOVERY_PROTOCOL_VERSION,
          job_id: job.job_id,
        },
      );

      const claimMatchesJob =
        claim.chat_id === job.chat_id &&
        claim.turn_id === job.turn_id &&
        claim.assistant_message_id === job.assistant_message_id &&
        claim.chat_key_version === job.chat_key_version;
      if (claim.state === "TERMINAL" && claimMatchesJob) {
        await serviceInstance.requestChatContentBatch_FOR_HANDLERS_ONLY([job.chat_id]);
        const taskInfo = serviceInstance.activeAITasks?.get(job.chat_id);
        if (taskInfo && taskInfo.taskId === job.assistant_message_id) {
          serviceInstance.activeAITasks?.delete(job.chat_id);
        }
        aiTypingStore.clearTyping(job.chat_id, job.assistant_message_id);
        return;
      }
      if (
        claim.state !== "LEASED" ||
        typeof claim.lease_token !== "string" ||
        typeof claim.lease_generation !== "number" ||
        typeof claim.sealed_payload !== "string" ||
        !claimMatchesJob
      ) {
        throw new Error(`Recovery job ${job.job_id} returned invalid lease or identity data.`);
      }

      const recoveryKeypair = await deriveChatCompletionRecoveryKeypair(
        encodeRecoveryChatKey(chatKey),
        job.chat_id,
        job.chat_key_version,
      );
      const plaintext = await openChatCompletionRecoveryEnvelope(
        JSON.parse(claim.sealed_payload) as ChatCompletionRecoveryEnvelope,
        {
          recoveryPrivateKey: recoveryKeypair.privateKey,
          ownerId: chat.user_id,
          chatId: job.chat_id,
          turnId: job.turn_id,
          jobId: job.job_id,
          assistantMessageId: job.assistant_message_id,
          keyVersion: job.chat_key_version,
        },
      );
      const recovered = JSON.parse(
        new TextDecoder("utf-8", { fatal: true }).decode(plaintext),
      ) as Record<string, unknown>;
      if (
        recovered.job_id !== job.job_id ||
        recovered.chat_id !== job.chat_id ||
        recovered.turn_id !== job.turn_id ||
        recovered.assistant_message_id !== job.assistant_message_id ||
        recovered.key_version !== job.chat_key_version ||
        typeof recovered.content !== "string" ||
        (recovered.category !== null && typeof recovered.category !== "string") ||
        (recovered.model_name !== null && typeof recovered.model_name !== "string")
      ) {
        throw new Error(`Recovery job ${job.job_id} plaintext identity did not match its lease.`);
      }

      const existingAssistantMessage = await chatDB.getMessage(job.assistant_message_id);
      const linkedUserMessageId = existingAssistantMessage?.role === "assistant"
        ? existingAssistantMessage.user_message_id
        : undefined;
      const now = Math.floor(Date.now() / 1000);
      const aiMessage = {
        message_id: job.assistant_message_id,
        chat_id: job.chat_id,
        role: "assistant",
        content: recovered.content,
        category: recovered.category ?? undefined,
        model_name: recovered.model_name ?? undefined,
        status: "synced",
        created_at: now,
      } as Message;
      const encryptedFields = await chatDB.getEncryptedFields(aiMessage, job.chat_id);
      const persistRecoveredMessage = (expectedMessagesV: number) => requestRecoveryEvent(
        "recovery_job_persisted",
        "recovery_job_persist",
        job.job_id,
        {
          protocol_version: CHAT_RECOVERY_PROTOCOL_VERSION,
          job_id: job.job_id,
          lease_token: claim.lease_token,
          lease_generation: claim.lease_generation,
          expected_messages_v: expectedMessagesV,
          encrypted_assistant_message: {
            client_message_id: job.assistant_message_id,
            chat_id: job.chat_id,
            role: "assistant",
            encrypted_content: encryptedFields.encrypted_content,
            encrypted_sender_name: encryptedFields.encrypted_sender_name,
            encrypted_category: encryptedFields.encrypted_category,
            encrypted_model_name: encryptedFields.encrypted_model_name,
            created_at: now,
            updated_at: now,
          },
        },
      );

      let persistedResult: Record<string, unknown>;
      let persistBaseChat = chat;
      try {
        persistedResult = await persistRecoveredMessage(chat.messages_v);
      } catch (error) {
        if (!(error instanceof RecoveryProtocolError) || error.code !== "version_conflict") throw error;
        const refreshedChat = await refreshRecoveryChatVersion(chat);
        if (!refreshedChat) throw error;
        persistBaseChat = refreshedChat;
        persistedResult = await persistRecoveredMessage(refreshedChat.messages_v);
      }
      if (
        persistedResult.state !== "TERMINAL" ||
        (persistedResult.committed_messages_v !== undefined &&
          (typeof persistedResult.committed_messages_v !== "number" ||
            !Number.isSafeInteger(persistedResult.committed_messages_v)))
      ) {
        throw new Error(`Recovery job ${job.job_id} persistence acknowledgement was invalid.`);
      }

      await chatDB.saveMessage(aiMessage);
      const updatedChat = {
        ...persistBaseChat,
        messages_v:
          typeof persistedResult.committed_messages_v === "number"
            ? persistedResult.committed_messages_v
            : persistBaseChat.messages_v + 1,
        last_edited_overall_timestamp: now,
        updated_at: now,
      };
      await chatDB.updateChat(updatedChat);
      const taskInfo = serviceInstance.activeAITasks?.get(job.chat_id);
      const taskMatchesRecoveryMessage = taskInfo?.taskId === job.assistant_message_id;
      if (taskMatchesRecoveryMessage) {
        serviceInstance.activeAITasks?.delete(job.chat_id);
      }
      aiTypingStore.clearTyping(job.chat_id, job.assistant_message_id);
      if (!isChatVisiblyActive(job.chat_id) && !updatedChat.is_sub_chat && !updatedChat.parent_id) {
        unreadMessagesStore.incrementUnread(job.chat_id);
        notificationStore.chatMessage(
          job.chat_id,
          updatedChat.title || "New message",
          buildRecoveryMessagePreview(recovered.content),
          undefined,
          (recovered.category as string | null) || updatedChat.category || undefined,
        );
      }
      serviceInstance.dispatchEvent(
        new CustomEvent("chatUpdated", {
          detail: {
            chat_id: job.chat_id,
            chat: updatedChat,
            newMessage: aiMessage,
            type: "recovery_job_persisted",
            messagesUpdated: true,
          },
        }),
      );
      serviceInstance.dispatchEvent(
        new CustomEvent("aiTaskEnded", {
          detail: {
            chatId: job.chat_id,
            taskId: taskMatchesRecoveryMessage ? taskInfo.taskId : undefined,
            userMessageId: linkedUserMessageId ?? (taskMatchesRecoveryMessage ? taskInfo.userMessageId : undefined),
            status: "completed",
          },
        }),
      );
    } catch (error) {
      if (error instanceof RecoveryStaleJobError) {
        console.debug(
          `[ChatSyncService:Recovery] Ignoring stale recovery job ${job.job_id}:`,
          error.message,
        );
        return;
      }
      console.error(`[ChatSyncService:Recovery] Failed recovery job ${job.job_id}:`, error);
    } finally {
      recoveryJobsInProgress.delete(job.job_id);
    }
  }));
}

let recoveryOutputPageQueue: Promise<void> = Promise.resolve();

export function handleRecoveryOutputsAvailableImpl(
  serviceInstance: ChatSynchronizationService,
  payload: { outputs?: AvailableRecoveryOutput[] },
): Promise<void> {
  const pending = recoveryOutputPageQueue.then(() => processRecoveryOutputsAvailable(serviceInstance, payload));
  recoveryOutputPageQueue = pending.catch((error) => {
    console.error("[ChatSyncService:Recovery] Output discovery page failed:", error);
  });
  return pending;
}

async function processRecoveryOutputsAvailable(
  serviceInstance: ChatSynchronizationService,
  payload: { outputs?: AvailableRecoveryOutput[] },
): Promise<void> {
  await waitForInitialSync(serviceInstance);
  const outputOrder: Record<RecoveryOutputKind, number> = {
    message: 0, embed: 1, diff: 2, summary: 3, checkpoint: 4,
  };
  for (const output of [...(payload.outputs ?? [])].sort((a, b) =>
    outputOrder[a.output_kind] - outputOrder[b.output_kind]
    || (a.output_kind === "message" && b.output_kind === "message"
      ? Number(a.message_role !== "user") - Number(b.message_role !== "user") : 0)
    || a.output_version - b.output_version)) {
    await (async () => {
    if (!output.record_id || recoveryOutputsInProgress.has(output.record_id)) return;
    recoveryOutputsInProgress.add(output.record_id);
    try {
      const rootChat = await chatDB.getChat(output.root_chat_id);
      const rootKey = await chatKeyManager.getKey(output.root_chat_id);
      if (!rootChat || !rootKey) return;
      const localTeamHash = rootChat.team_id ? await computeSHA256(rootChat.team_id) : null;
      if (localTeamHash !== (output.root_hashed_team_id ?? null)) {
        throw new Error("Recovery Team key context does not match the sealed output scope.");
      }
      const ownerId = rootChat.user_id || (await userDB.getUserProfile())?.user_id;
      if (!ownerId || !await ensureChatKeySafeForWrite(output.root_chat_id, rootKey, "output recovery", { reportFailure: false })) return;
      const result = await requestRecoveryEvent(
        "recovery_output_ready", "recovery_output_get", output.record_id,
        { protocol_version: CHAT_RECOVERY_PROTOCOL_VERSION, record_id: output.record_id },
      );
      if (result.record_id !== output.record_id || result.root_chat_id !== output.root_chat_id
        || (result.root_hashed_team_id ?? null) !== (output.root_hashed_team_id ?? null)
        || result.target_chat_id !== output.target_chat_id || result.turn_id !== output.turn_id
        || result.subject_id !== output.subject_id || result.output_kind !== output.output_kind
        || result.output_version !== output.output_version || result.chat_key_version !== output.chat_key_version
        || result.message_role !== output.message_role
        || typeof result.sealed_payload !== "string" || !Number.isSafeInteger(result.messages_v)) {
        throw new Error("Recovery output identity or payload did not match its index.");
      }
      const keypair = await deriveChatCompletionRecoveryKeypair(
        encodeRecoveryChatKey(rootKey), output.root_chat_id, output.chat_key_version,
      );
      const plaintext = await openRecoveryOutputEnvelope(
        JSON.parse(result.sealed_payload) as ChatCompletionRecoveryEnvelope,
        {
          recoveryPrivateKey: keypair.privateKey,
          ownerId, rootChatId: output.root_chat_id, targetChatId: output.target_chat_id,
          turnId: output.turn_id, recordId: output.record_id, subjectId: output.subject_id,
          outputKind: output.output_kind, outputVersion: output.output_version, keyVersion: output.chat_key_version,
        },
      );
      const recovered = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(plaintext)) as Record<string, unknown>;
      const content = recovered.content as Record<string, unknown>;
      if (recovered.record_id !== output.record_id || recovered.target_chat_id !== output.target_chat_id
        || recovered.subject_id !== output.subject_id || recovered.output_kind !== output.output_kind
        || recovered.output_version !== output.output_version || !content || typeof content !== "object") {
        throw new Error("Recovery output plaintext failed identity validation.");
      }
      chatKeyManager.injectKey(output.target_chat_id, rootKey, "master_key");
      const encryptedChatKey = typeof result.encrypted_chat_key === "string" && result.encrypted_chat_key
        ? result.encrypted_chat_key : await encryptChatKeyWithMasterKey(rootKey);
      if (!encryptedChatKey) throw new Error("Could not wrap child recovery chat key.");
      const now = Math.floor(Date.now() / 1000);
      const encryptedTitle = typeof result.encrypted_title === "string" && result.encrypted_title
        ? result.encrypted_title : await encryptWithChatKey("Sub-chat", rootKey);
      let childChat = await chatDB.getChat(output.target_chat_id);
      if (!childChat) {
        childChat = {
          chat_id: output.target_chat_id, parent_id: output.root_chat_id,
          is_sub_chat: true, title: "Sub-chat", encrypted_title: encryptedTitle,
          encrypted_chat_key: encryptedChatKey, messages_v: result.messages_v as number,
          title_v: 0, unread_count: 0, user_id: ownerId, team_id: rootChat.team_id,
          created_at: now, updated_at: now, last_edited_overall_timestamp: now,
        } as Chat;
        await chatDB.addChat(childChat);
      }
      if (!await ensureChatKeySafeForWrite(output.target_chat_id, rootKey, "child output recovery", { reportFailure: false })) return;
      if (output.output_kind === "embed" || output.output_kind === "diff") {
        await withCanonicalEmbedWrite(output.subject_id, async (lease) => {
          const canonicalReceipt = await persistRecoveredEmbed(output, content, rootKey, ownerId);
          const acknowledged = await requestRecoveryEvent(
            "recovery_output_embed_acknowledged", "recovery_output_ack_embed", output.record_id,
            { protocol_version: CHAT_RECOVERY_PROTOCOL_VERSION, record_id: output.record_id,
              canonical_digest: canonicalReceipt.digest, canonical_source: canonicalReceipt.source },
          );
          if (acknowledged.state !== "ACKNOWLEDGED") throw new Error("Recovered embed was not acknowledged.");
          markAcknowledgedRecoveredEmbed(lease, output.target_chat_id, output.output_version);
        });
        serviceInstance.dispatchEvent(new CustomEvent("embedUpdated", {
          detail: { embed_id: output.subject_id, chat_id: output.target_chat_id,
            status: "finished", version_number: output.output_version, isProcessing: false },
        }));
        return;
      }
      if (output.output_kind === "checkpoint") {
        if (typeof content.summary_content !== "string") throw new Error("Recovery checkpoint summary was invalid.");
        await storeRecoveredCheckpoint(output, content, await encryptWithChatKey(content.summary_content, rootKey));
        return;
      }
      if (output.output_kind === "summary") {
        if (typeof content.summary !== "string" || !Number.isSafeInteger(result.metadata_v)) {
          throw new Error("Recovery summary content or version was invalid.");
        }
        const encryptedSummary = await encryptWithChatKey(content.summary, rootKey);
        const persistSummary = (version: number) => requestRecoveryEvent(
          "recovery_output_summary_persisted", "recovery_output_persist_summary", output.record_id,
          {
            protocol_version: CHAT_RECOVERY_PROTOCOL_VERSION, record_id: output.record_id,
            expected_metadata_v: version, encrypted_summary: encryptedSummary,
          },
        );
        let persistedSummary: Record<string, unknown>;
        try {
          persistedSummary = await persistSummary(result.metadata_v as number);
        } catch (error) {
          if (!(error instanceof RecoveryProtocolError) || error.code !== "version_conflict") throw error;
          const refreshed = await requestRecoveryEvent(
            "recovery_output_ready", "recovery_output_get", output.record_id,
            { protocol_version: CHAT_RECOVERY_PROTOCOL_VERSION, record_id: output.record_id },
          );
          if (!Number.isSafeInteger(refreshed.metadata_v)) throw error;
          persistedSummary = await persistSummary(refreshed.metadata_v as number);
        }
        if (persistedSummary.state !== "ACKNOWLEDGED") throw new Error("Recovery summary was not acknowledged.");
        await chatDB.updateChat({
          ...childChat, chat_summary: content.summary, encrypted_chat_summary: encryptedSummary,
          metadata_v: persistedSummary.committed_metadata_v as number,
          updated_at: now,
        });
        return;
      }
      if (typeof content.content !== "string"
        || (output.message_role !== "user" && output.message_role !== "assistant")
        || content.role !== output.message_role
        || (content.category !== null && typeof content.category !== "string")
        || (content.model_name !== null && typeof content.model_name !== "string")) {
        throw new Error("Recovery message content was invalid.");
      }
      const messageCreatedAt = Number.isSafeInteger(content.created_at)
        ? content.created_at as number : now;
      const aiMessage = {
        message_id: output.subject_id, chat_id: output.target_chat_id, role: output.message_role,
        content: content.content, category: content.category ?? undefined,
        model_name: content.model_name ?? undefined, status: "synced", created_at: messageCreatedAt,
      } as Message;
      const encryptedFields = await chatDB.getEncryptedFields(aiMessage, output.target_chat_id);
      const persist = (version: number) => requestRecoveryEvent(
        "recovery_output_persisted", "recovery_output_persist_message", output.record_id,
        {
          protocol_version: CHAT_RECOVERY_PROTOCOL_VERSION, record_id: output.record_id,
          expected_messages_v: version,
          ...(result.encrypted_chat_key ? {} : { encrypted_chat_key: encryptedChatKey, encrypted_title: encryptedTitle }),
          [output.message_role === "user" ? "encrypted_user_message" : "encrypted_assistant_message"]: {
            client_message_id: output.subject_id, chat_id: output.target_chat_id,
            role: output.message_role, encrypted_content: encryptedFields.encrypted_content,
            encrypted_sender_name: encryptedFields.encrypted_sender_name,
            encrypted_category: encryptedFields.encrypted_category,
            encrypted_model_name: encryptedFields.encrypted_model_name,
            created_at: messageCreatedAt, updated_at: now,
          },
        },
      );
      let persisted: Record<string, unknown>;
      try {
        persisted = await persist(result.messages_v as number);
      } catch (error) {
        if (!(error instanceof RecoveryProtocolError) || error.code !== "version_conflict") throw error;
        const refreshed = await requestRecoveryEvent(
          "recovery_output_ready", "recovery_output_get", output.record_id,
          { protocol_version: CHAT_RECOVERY_PROTOCOL_VERSION, record_id: output.record_id },
        );
        if (!Number.isSafeInteger(refreshed.messages_v)) throw error;
        persisted = await persist(refreshed.messages_v as number);
      }
      if (persisted.state !== "ACKNOWLEDGED") throw new Error("Recovery output was not acknowledged.");
      await chatDB.saveMessage(aiMessage);
      await chatDB.updateChat({
        ...childChat, messages_v: persisted.committed_messages_v as number,
        updated_at: now, last_edited_overall_timestamp: now,
      });
      serviceInstance.dispatchEvent(new CustomEvent("chatUpdated", {
        detail: { chat_id: output.target_chat_id, newMessage: aiMessage, type: "recovery_output_persisted", messagesUpdated: true },
      }));
    } catch (error) {
      if (!(error instanceof RecoveryStaleJobError)) console.error("[ChatSyncService:Recovery] Output recovery failed:", error);
    } finally {
      recoveryOutputsInProgress.delete(output.record_id);
    }
    })();
  }
}

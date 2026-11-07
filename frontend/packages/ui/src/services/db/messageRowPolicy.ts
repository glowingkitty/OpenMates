// frontend/packages/ui/src/services/db/messageRowPolicy.ts
// Pure message-row write policy of the IndexedDB `messages` store: which version
// of a message wins (status priority), when new encrypted fields force a write,
// which rows are content duplicates and which cached rows are safe to evict.
//
// No IndexedDB, crypto or network access: with VITE_OPENMATES_RUST_CORE=1 the same
// decisions are made by the shared Rust core (web_persist::message_policy, served
// by the Worker `persist` unit) and this module is the flag-off implementation and
// the source of the parity vectors (web_persist/ts_vectors.json). Type-only
// imports keep it loadable by the vector generator without the app.

import type { Message } from "../../types/chat";

const UNSAFE_TO_EVICT_MESSAGE_STATUSES = new Set<Message["status"]>([
  "sending",
  "waiting_for_upload",
  "waiting_for_internet",
  "queued",
  "processing",
  "streaming",
  "failed",
  "waiting_for_user",
  "delivered",
]);


export function isSafeToEvictMessage(message: Message | undefined): boolean {
  if (!message) return false;
  const raw = message as Message & Record<string, unknown>;
  return message.status === "synced" &&
    !UNSAFE_TO_EVICT_MESSAGE_STATUSES.has(message.status) &&
    !raw.pending_turn_preflight_v1 &&
    !raw.pending_encrypted_turn_preflight_v1 &&
    !raw.pending_encrypted_embed_bundle_v1;
}


/**
 * Status priority map for determining which message version to keep
 * Higher priority means the message has progressed further in its lifecycle
 */
export const STATUS_PRIORITY: Record<string, number> = {
  sending: 1,
  waiting_for_upload: 1, // Upload in progress, same level as sending
  waiting_for_internet: 1,
  queued: 3.1, // Server queue admission survives an ordinary synced/delivered refresh
  processing: 2,
  streaming: 2,
  waiting_for_user: 2.3, // Higher than streaming/processing, lower than failed - chat paused for user action
  failed: 2.5,
  delivered: 2.8, // Server received the message, awaiting full sync confirmation
  synced: 3,
};

/**
 * Determines if a new message should update an existing message.
 *
 * Rules:
 * - Always allow streaming -> streaming updates (content grows over time).
 * - Never allow synced to overwrite waiting_for_user. 'waiting_for_user' is a
 *   terminal client-side display state (e.g. credits-rejection, permissions request).
 *   Phased sync delivers these messages from Directus with status='synced' (the
 *   server-side storage status), but the client must keep 'waiting_for_user' so
 *   the Buy Credits button, header banner, and typing indicator suppression remain
 *   correct after a tab reload.
 * - Otherwise, allow updates when status priority increases.
 */
export function shouldUpdateMessage(
  existing: Message,
  incoming: Message,
): boolean {
  if (existing.queue_dispatch_status === "paused" &&
      (incoming.queue_dispatch_status === "queued" || incoming.queue_dispatch_status === "processing")) {
    return false; // This increment has no same-ID resume; older receipts cannot revive a paused turn.
  }
  if (existing.queue_dispatch_status === "processing" && incoming.queue_dispatch_status === "queued") {
    return false; // An older queued receipt cannot undo a durable task handoff.
  }
  if ((existing.status === "queued" || existing.queue_dispatch_status === "processing") &&
      incoming.queue_dispatch_status === "paused") {
    return true; // Failure receipt supersedes both pending and consumed Steer states.
  }
  if (existing.status === "queued" && Number.isSafeInteger(incoming.queue_revision) &&
      (incoming.queue_revision ?? 0) >= (existing.queue_revision ?? 0) &&
      incoming.queue_dispatch_status === "processing") {
    return true; // Durable server handoff receipt clears queued UI after missed WS events.
  }
  if (existing.status === "queued" && Number.isSafeInteger(incoming.queue_revision) &&
      (incoming.queue_revision ?? 0) > (existing.queue_revision ?? 0)) {
    return true; // A newer encrypted edit revision must replace a stale local body.
  }
  // Streaming chunks must be able to update the same message id.
  if (existing.status === "streaming" && incoming.status === "streaming") {
    return true;
  }

  // Never overwrite a waiting_for_user message with synced or delivered from phased sync.
  // 'waiting_for_user' is a terminal client-side display state that the server doesn't
  // persist — Directus has no status column, so phased sync messages arrive with no status
  // and prepareMessagesForStorage() assigns 'delivered' as the default. Since 'delivered'
  // has higher priority (2.8) than 'waiting_for_user' (2.3), the priority check below would
  // allow the overwrite. This would clobber the client state and hide the Buy Credits button
  // and the credits-error header after a page reload.
  // Guard both 'synced' (from chat_message_confirmed events) and 'delivered' (from phased sync).
  if (
    existing.status === "waiting_for_user" &&
    (incoming.status === "synced" || incoming.status === "delivered")
  ) {
    return false;
  }

  const existingPriority = STATUS_PRIORITY[existing.status] ?? 0;
  const incomingPriority = STATUS_PRIORITY[incoming.status] ?? 0;

  if (incomingPriority > existingPriority) {
    return true;
  }

  if (incomingPriority === existingPriority && existing.status === incoming.status) {
    if (existing.content !== incoming.content) return false;

    if (
      existing.model_name !== incoming.model_name ||
      existing.category !== incoming.category ||
      existing.thinking_content !== incoming.thinking_content ||
      existing.thinking_signature !== incoming.thinking_signature ||
      existing.thinking_token_count !== incoming.thinking_token_count ||
      existing.has_thinking !== incoming.has_thinking
    ) {
      return true;
    }
  }

  return false;
}

/**
 * Returns true if the incoming encrypted record adds encrypted fields that are missing on the existing record.
 * This is important for placeholder messages (e.g. assistant message created before first chunk arrives).
 */
export function hasNewEncryptedFields(
  existing: Message,
  incomingEncrypted: Message,
): boolean {
  const pairs: Array<[keyof Message, keyof Message]> = [
    ["encrypted_content", "encrypted_content"],
    ["encrypted_sender_name", "encrypted_sender_name"],
    ["encrypted_category", "encrypted_category"],
    ["encrypted_model_name", "encrypted_model_name"],
    // Thinking content/signature must be persisted even if status doesn't advance.
    ["encrypted_thinking_content", "encrypted_thinking_content"],
    ["encrypted_thinking_signature", "encrypted_thinking_signature"],
    // PII mappings for client-side restoration of anonymized data
    ["encrypted_pii_mappings", "encrypted_pii_mappings"],
  ];

  return pairs.some(([existingKey, incomingKey]) => {
    const existingValue = existing[existingKey];
    const incomingValue = incomingEncrypted[incomingKey];
    return !existingValue && !!incomingValue;
  });
}

export function hasNewerStoredRevision(stored: Message, incoming: Message): boolean {
  return Number.isSafeInteger(stored.queue_revision) &&
    Number.isSafeInteger(incoming.queue_revision) &&
    (stored.queue_revision ?? 0) > (incoming.queue_revision ?? 0);
}

// ============================================================================
// DUPLICATE DETECTION
// ============================================================================

/**
 * Determines if two messages are content duplicates (same logical message, different IDs)
 *
 * CRITICAL: For assistant messages, we also check if the message_id matches the task_id pattern
 * to avoid false positives when the same response is saved with different IDs from different sources.
 */
export function isContentDuplicate(
  existing: Message,
  incoming: Message,
): boolean {
  // Must be same chat, role, and have similar content
  if (
    existing.chat_id !== incoming.chat_id ||
    existing.role !== incoming.role
  ) {
    return false;
  }

  // Repeating text is a new user submission when its stable message ID differs.
  // Retries and sync copies retain that ID and use the primary-key save path.
  if (existing.role === "user" && existing.message_id !== incoming.message_id) {
    return false;
  }

  // For assistant messages, if message_ids are different but both look like task IDs (UUIDs),
  // and content matches, they might be the same message from different sync sources.
  // However, we should be more careful - only treat as duplicate if encrypted_content matches
  // AND timestamps are very close (within 1 minute for assistant messages to account for streaming delays)
  const isAssistantMessage =
    existing.role === "assistant" && incoming.role === "assistant";
  const timeThreshold = isAssistantMessage ? 60 : 300; // 1 minute for assistant, 5 minutes for user

  // Prefer encrypted content when both records have it. When this function is
  // called after getMessagesForChat(), records may already be decrypted and
  // encrypted_content is intentionally absent; two missing encrypted fields are
  // not evidence of duplicate content.
  const hasEncryptedContent = !!existing.encrypted_content && !!incoming.encrypted_content;
  const contentMatch = hasEncryptedContent
    ? existing.encrypted_content === incoming.encrypted_content
    : !!existing.content && !!incoming.content && existing.content === incoming.content;

  // Check if timestamps are close (within threshold) - messages from different sync sources
  const timeDiff = Math.abs(existing.created_at - incoming.created_at);
  const timeMatch = timeDiff < timeThreshold;

  // Check if sender names match (for user messages)
  // For assistant messages, sender_name is typically null/undefined, so this check is less relevant
  const senderMatch =
    existing.encrypted_sender_name === incoming.encrypted_sender_name ||
    (existing.role === "assistant" && incoming.role === "assistant");

  const isDuplicate = contentMatch && timeMatch && senderMatch;

  if (isDuplicate && isAssistantMessage) {
    console.debug(
      `[ChatDatabase] Detected potential duplicate assistant message: ` +
        `existing=${existing.message_id}, incoming=${incoming.message_id}, ` +
        `timeDiff=${timeDiff}s, contentMatch=${contentMatch}`,
    );
  }

  return isDuplicate;
}

/** The fields of a stored message the duplicate-cleanup plan reads. */
export interface DuplicateCleanupRow {
  chat_id: string;
  message_id: string;
}

/**
 * `message_id`s `cleanupDuplicateMessages` deletes, in order: per chat (first
 * appearance order) every id stored more than once, once, by first occurrence. The delete is by id, so
 * which of the copies has the higher status priority does not change the outcome.
 */
export function planDuplicateCleanup(messages: readonly DuplicateCleanupRow[]): string[] {
  const countsByChat = new Map<string, Map<string, number>>();
  for (const { chat_id, message_id } of messages) {
    let counts = countsByChat.get(chat_id);
    if (!counts) countsByChat.set(chat_id, (counts = new Map()));
    counts.set(message_id, (counts.get(message_id) ?? 0) + 1);
  }
  const deletes: string[] = [];
  for (const counts of countsByChat.values()) {
    for (const [messageId, count] of counts) if (count > 1) deletes.push(messageId);
  }
  return deletes;
}

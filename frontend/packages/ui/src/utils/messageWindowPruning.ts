// frontend/packages/ui/src/utils/messageWindowPruning.ts
// Shared bounded-window pruning for decrypted chat message arrays.
//
// The encrypted IndexedDB cache may hold more pages, but Svelte component state
// should stay small for long chats. This helper keeps recent/latest context and
// unsafe in-flight rows while pruning normal durable rows toward a target size.

import type { ChatCompressionCheckpoint, Message, MessageStatus } from "../types/chat";

export const NORMAL_MESSAGE_PAGE_LIMIT = 30;
export const DECRYPTED_WINDOW_TARGET = 60;
export const DECRYPTED_WINDOW_HARD_CAP = 90;

const UNSAFE_TO_PRUNE_STATUSES = new Set<MessageStatus>([
  "sending",
  "waiting_for_upload",
  "waiting_for_internet",
  "processing",
  "streaming",
  "failed",
  "waiting_for_user",
  "delivered",
]);

export type PrunableMessage = Pick<Message, "role"> & {
  status?: MessageStatus;
  category?: string;
  created_at?: number | null;
  original_message?: Pick<Message, "created_at" | "category"> | null;
};

export interface PruneDecryptedMessageWindowOptions {
  compressionCheckpoints?: ChatCompressionCheckpoint[];
  pageLimit?: number;
  target?: number;
  hardCap?: number;
}

export interface PruneDecryptedMessageWindowResult<T extends PrunableMessage> {
  messages: T[];
  prunedCount: number;
}

export type MessageWindowIdentity = {
  message_id?: string;
};

function latestCompressionBoundary(checkpoints: ChatCompressionCheckpoint[] | undefined): number | null {
  if (!checkpoints || checkpoints.length === 0) return null;
  return [...checkpoints].sort((a, b) => b.created_at - a.created_at)[0]?.compressed_up_to_timestamp ?? null;
}

function messageCreatedAt(message: PrunableMessage): number | null {
  return message.created_at ?? message.original_message?.created_at ?? null;
}

function messageCategory(message: PrunableMessage): string | undefined {
  return message.category ?? message.original_message?.category;
}

function isNormalMessage(message: PrunableMessage, compressionBoundary: number | null): boolean {
  const createdAt = messageCreatedAt(message);
  if (createdAt === null) return false;
  if (message.role === "system" && messageCategory(message) === "compression_summary") return false;
  if (compressionBoundary !== null && createdAt <= compressionBoundary) return false;
  return true;
}

function isUnsafeToPrune(message: PrunableMessage): boolean {
  return !!message.status && UNSAFE_TO_PRUNE_STATUSES.has(message.status);
}

export function pruneDecryptedMessageWindow<T extends PrunableMessage>(
  messages: T[],
  options: PruneDecryptedMessageWindowOptions = {},
): PruneDecryptedMessageWindowResult<T> {
  const pageLimit = Math.max(1, Math.floor(options.pageLimit ?? NORMAL_MESSAGE_PAGE_LIMIT));
  const target = Math.max(pageLimit, Math.floor(options.target ?? DECRYPTED_WINDOW_TARGET));
  const hardCap = Math.max(target, Math.floor(options.hardCap ?? DECRYPTED_WINDOW_HARD_CAP));
  const compressionBoundary = latestCompressionBoundary(options.compressionCheckpoints);
  const normalIndexes = messages
    .map((message, index) => ({ message, index }))
    .filter(({ message }) => isNormalMessage(message, compressionBoundary));

  if (normalIndexes.length <= hardCap) {
    return { messages, prunedCount: 0 };
  }

  const keepIndexes = new Set<number>();
  for (const { message, index } of normalIndexes) {
    if (isUnsafeToPrune(message)) keepIndexes.add(index);
  }
  for (const { index } of normalIndexes.slice(0, pageLimit)) keepIndexes.add(index);
  for (const { index } of normalIndexes.slice(-pageLimit)) keepIndexes.add(index);
  for (let i = normalIndexes.length - 1; keepIndexes.size < target && i >= 0; i -= 1) {
    keepIndexes.add(normalIndexes[i].index);
  }

  const prunedMessages = messages.filter((message, index) => {
    if (!isNormalMessage(message, compressionBoundary)) return true;
    return keepIndexes.has(index);
  });

  return {
    messages: prunedMessages,
    prunedCount: messages.length - prunedMessages.length,
  };
}

export function shouldPreserveExpandedMessageWindow<T extends MessageWindowIdentity>(
  currentMessages: T[],
  incomingMessages: T[],
): boolean {
  if (incomingMessages.length === 0 || currentMessages.length <= incomingMessages.length) return false;

  const currentIds = new Set(currentMessages.map((message) => message.message_id).filter(Boolean));
  return incomingMessages.every((message) => !!message.message_id && currentIds.has(message.message_id));
}

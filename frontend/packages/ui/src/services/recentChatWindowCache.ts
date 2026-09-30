import type { Chat, ChatCompressionCheckpoint, Message } from '../types/chat';
import { BoundedCache, estimatePayloadBytes } from '../utils/boundedCache';
import { getWorkspaceCacheEpoch, registerWorkspaceCacheClear } from './workspaceCacheLifecycle';
import { get } from 'svelte/store';
import { userProfile } from '../stores/userProfile';
import { shouldPreserveExpandedMessageWindow } from '../utils/messageWindowPruning';

const MAX_RECENT_WINDOWS = 8;
const MAX_RECENT_WINDOW_BYTES = 16 * 1024 * 1024;
const MAX_REVISION_TOKENS = 256;

export interface RecentChatHeader {
  title: string;
  category: string | null;
  icon: string | null;
  summary: string | null;
  encryptedTitle?: string | null;
  encryptedCategory?: string | null;
  encryptedIcon?: string | null;
  encryptedSummary?: string | null;
  titleVersion?: number | null;
}

export interface RecentChatWindow {
  messages: Message[];
  compressionCheckpoints: ChatCompressionCheckpoint[];
  hasMoreBefore: boolean;
  header: RecentChatHeader;
}

interface StoredRecentChatWindow extends RecentChatWindow {
  epoch: number;
  revision: number;
  accountId: string;
}

const cache = new BoundedCache<string, StoredRecentChatWindow>(MAX_RECENT_WINDOW_BYTES, MAX_RECENT_WINDOWS);
const revisions = new Map<string, number>();
let nextRevision = 0;

function rememberRevision(chatId: string, revision: number): number {
  revisions.delete(chatId);
  revisions.set(chatId, revision);
  while (revisions.size > MAX_REVISION_TOKENS) revisions.delete(revisions.keys().next().value!);
  return revision;
}

function snapshot<T>(value: T): T {
  // Svelte $state wraps active messages in proxies, which structuredClone rejects.
  if (typeof structuredClone === 'function') {
    try { return structuredClone(value); } catch { /* fall back to serializable message data */ }
  }
  return JSON.parse(JSON.stringify(value)) as T;
}

export function getRecentChatRevision(chatId: string): number {
  const revision = revisions.get(chatId);
  return rememberRevision(chatId, revision ?? ++nextRevision);
}

/** Reject a canonical read completed after a message or key lifecycle change. */
export function isRecentChatReadCurrent(chatId: string, epoch: number, revision: number): boolean {
  return epoch === getWorkspaceCacheEpoch() && revision === getRecentChatRevision(chatId);
}

/** Keep older loaded pages while refreshing canonical fields of the latest page. */
export function reconcileRecentChatMessages(current: Message[], incoming: Message[], hasMoreBefore: boolean): Message[] {
  if (!hasMoreBefore || !shouldPreserveExpandedMessageWindow(current, incoming)) return incoming;
  const freshById = new Map(incoming.map((message) => [message.message_id, message]));
  return current.map((message) => freshById.get(message.message_id) ?? message);
}

/** A committed message mutation makes the last decrypted window unsafe to replay. */
export function invalidateRecentChatWindow(chatId: string): void {
  rememberRevision(chatId, ++nextRevision);
  cache.delete(chatId);
}

export function invalidateRecentChatWindowForMessage(messageId: string): void {
  for (const [chatId, entry] of cache) {
    if (entry.messages.some((message) => message.message_id === messageId)) invalidateRecentChatWindow(chatId);
  }
}

export function clearRecentChatWindows(): void {
  cache.clear();
  revisions.clear();
}

registerWorkspaceCacheClear(clearRecentChatWindows);

export function putRecentChatWindow(
  chatId: string,
  window: RecentChatWindow,
  expectedEpoch = getWorkspaceCacheEpoch(),
  expectedRevision = getRecentChatRevision(chatId),
): boolean {
  // Resolve identity only on access; importing the store must not subscribe at module initialization.
  const accountId = get(userProfile).user_id;
  if (!accountId) return false;
  if (!isRecentChatReadCurrent(chatId, expectedEpoch, expectedRevision)) return false;
  if (window.messages.length === 0 || window.messages.some((message) => message.chat_id !== chatId)) return false;
  // Only settled, persisted messages can be replayed on a future selection.
  if (window.messages.some((message) =>
    typeof message.content !== 'string'
    || (message as Message & { _decryptionPending?: boolean })._decryptionPending
    || ['sending', 'processing', 'streaming', 'waiting_for_upload', 'waiting_for_internet'].includes(message.status)
  )) return false;
  let entry: StoredRecentChatWindow;
  try {
    entry = snapshot({ ...window, epoch: expectedEpoch, revision: expectedRevision, accountId });
  } catch {
    // Optional memory acceleration must never interrupt canonical chat opening.
    return false;
  }
  if (estimatePayloadBytes(entry, MAX_RECENT_WINDOW_BYTES) > MAX_RECENT_WINDOW_BYTES) return false;
  cache.set(chatId, entry);
  return cache.has(chatId);
}

export function getRecentChatWindow(chat: Chat): RecentChatWindow | null {
  const accountId = get(userProfile).user_id;
  if (!accountId) return null;
  const entry = cache.get(chat.chat_id);
  if (!entry) return null;
  if (entry.accountId !== accountId || entry.epoch !== getWorkspaceCacheEpoch() || entry.revision !== getRecentChatRevision(chat.chat_id)) {
    cache.delete(chat.chat_id);
    return null;
  }
  return snapshot(entry);
}

export function recentChatHeaderMatches(chat: Chat, header: RecentChatHeader): boolean {
  return (chat.encrypted_title ?? null) === (header.encryptedTitle ?? null)
    && (chat.encrypted_category ?? null) === (header.encryptedCategory ?? null)
    && (chat.encrypted_icon ?? null) === (header.encryptedIcon ?? null)
    && (chat.encrypted_chat_summary ?? null) === (header.encryptedSummary ?? null)
    && (chat.title_v ?? null) === (header.titleVersion ?? null);
}

export function getRecentChatWindowStats(): { count: number; maxCount: number; maxBytes: number; revisionTokens: number } {
  return { count: cache.size, maxCount: MAX_RECENT_WINDOWS, maxBytes: MAX_RECENT_WINDOW_BYTES, revisionTokens: revisions.size };
}

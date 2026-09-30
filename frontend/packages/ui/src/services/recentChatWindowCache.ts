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
  sourceChat: Chat | null;
}

const cache = new BoundedCache<string, StoredRecentChatWindow>(MAX_RECENT_WINDOW_BYTES, MAX_RECENT_WINDOWS);
const revisions = new Map<string, number>();
let nextRevision = 0;
const invalidationListeners = new Set<() => void>();

/** Observe revocations synchronously; callers must unsubscribe on unmount. */
export function subscribeRecentChatWindowInvalidation(listener: () => void): () => void {
  invalidationListeners.add(listener);
  return () => invalidationListeners.delete(listener);
}

function signalInvalidation(): void {
  for (const listener of invalidationListeners) listener();
}

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

/** Distinguish a recoverable message write from loss of the warm view's security scope. */
export class RecentChatWarmReadGuard {
  private state: 'active' | 'revoked' | 'completed' = 'active';

  constructor(
    readonly chatId: string,
    readonly epoch: number,
    private revision: number,
  ) {}

  get active(): boolean { return this.state === 'active'; }
  get canContinue(): boolean { return this.state !== 'revoked'; }

  inspect(scopeValid: boolean, epoch: number, revision: number): 'current' | 'mutation' | 'revoked' {
    if (this.state === 'revoked') return 'revoked';
    if (this.state === 'completed') return 'current';
    if (!scopeValid || epoch !== this.epoch) {
      this.state = 'revoked';
      return 'revoked';
    }
    if (revision !== this.revision) {
      this.revision = revision;
      return 'mutation';
    }
    return 'current';
  }

  complete(): void {
    if (this.state === 'active') this.state = 'completed';
  }
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
  signalInvalidation();
}

export function invalidateRecentChatWindowForMessage(messageId: string): void {
  for (const [chatId, entry] of cache) {
    if (entry.messages.some((message) => message.message_id === messageId)) invalidateRecentChatWindow(chatId);
  }
}

export function clearRecentChatWindows(): void {
  cache.clear();
  revisions.clear();
  signalInvalidation();
}

registerWorkspaceCacheClear(clearRecentChatWindows);

export function putRecentChatWindow(
  chatId: string,
  window: RecentChatWindow,
  expectedEpoch = getWorkspaceCacheEpoch(),
  expectedRevision = getRecentChatRevision(chatId),
  sourceChat?: Chat,
): boolean {
  // Resolve identity only on access; importing the store must not subscribe at module initialization.
  const accountId = get(userProfile).user_id;
  if (!accountId) return false;
  if (!isRecentChatReadCurrent(chatId, expectedEpoch, expectedRevision)) return false;
  if (sourceChat && (sourceChat.is_incognito || sourceChat.is_anonymous || sourceChat.is_hidden_candidate)) return false;
  if (window.messages.length === 0 || window.messages.some((message) => message.chat_id !== chatId)) return false;
  // Only settled, persisted messages can be replayed on a future selection.
  if (window.messages.some((message) =>
    typeof message.content !== 'string'
    || (message as Message & { _decryptionPending?: boolean })._decryptionPending
    || ['sending', 'processing', 'streaming', 'waiting_for_upload', 'waiting_for_internet'].includes(message.status)
  )) return false;
  let entry: StoredRecentChatWindow;
  try {
    const sourceChatForSelection: Chat | null = sourceChat?.chat_id === chatId
      ? {
          chat_id: sourceChat.chat_id,
          user_id: sourceChat.user_id,
          team_id: sourceChat.team_id,
          encrypted_title: sourceChat.encrypted_title,
          encrypted_category: sourceChat.encrypted_category,
          encrypted_icon: sourceChat.encrypted_icon,
          encrypted_chat_summary: sourceChat.encrypted_chat_summary,
          messages_v: sourceChat.messages_v,
          title_v: sourceChat.title_v,
          metadata_v: sourceChat.metadata_v,
          last_edited_overall_timestamp: sourceChat.last_edited_overall_timestamp,
          unread_count: sourceChat.unread_count,
          created_at: sourceChat.created_at,
          updated_at: sourceChat.updated_at,
          last_visible_message_id: sourceChat.last_visible_message_id,
          processing_metadata: sourceChat.processing_metadata,
          waiting_for_metadata: sourceChat.waiting_for_metadata,
          is_shared: sourceChat.is_shared,
          is_private: sourceChat.is_private,
          is_shared_by_others: sourceChat.is_shared_by_others,
          is_hidden: sourceChat.is_hidden,
          is_hidden_candidate: sourceChat.is_hidden_candidate,
          is_incognito: sourceChat.is_incognito,
          is_anonymous: sourceChat.is_anonymous,
          is_metadata_only: sourceChat.is_metadata_only,
          parent_id: sourceChat.parent_id,
          is_sub_chat: sourceChat.is_sub_chat,
          encrypted_draft_md: null,
          encrypted_draft_preview: null,
        }
      : null;
    entry = snapshot({
      ...window, epoch: expectedEpoch, revision: expectedRevision, accountId,
      // The remount shell needs the selected chat's metadata before IndexedDB
      // resolves. The composer restores its canonical draft separately.
      sourceChat: sourceChatForSelection,
    });
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
  return snapshot({
    messages: entry.messages,
    compressionCheckpoints: entry.compressionCheckpoints,
    hasMoreBefore: entry.hasMoreBefore,
    header: entry.header,
  });
}

/** Synchronous selected-chat snapshot for a new ActiveChat component instance. */
export function getRecentChatSelection(chatId: string): { chat: Chat; window: RecentChatWindow } | null {
  const entry = cache.get(chatId);
  if (!entry?.sourceChat || entry.sourceChat.chat_id !== chatId) return null;
  const window = getRecentChatWindow(entry.sourceChat);
  if (!window || !recentChatHeaderMatches(entry.sourceChat, window.header)) return null;
  return { chat: snapshot(entry.sourceChat), window };
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

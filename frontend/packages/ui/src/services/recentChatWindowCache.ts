import type { Chat, ChatCompressionCheckpoint, Message } from '../types/chat';
import { BoundedCache, estimatePayloadBytes } from '../utils/boundedCache';
import { getWorkspaceCacheEpoch, registerWorkspaceCacheClear } from './workspaceCacheLifecycle';
import { get } from 'svelte/store';
import { userProfile } from '../stores/userProfile';
import { shouldPreserveExpandedMessageWindow } from '../utils/messageWindowPruning';


// Optional test-installed observation only. No cache, navigation or security policy.
// Absent by default; no persistence, network, identifiers or domain references.
const RECENT_REPLAY_DIAGNOSTIC_REASONS = Object.freeze([
  "route-enter",
  "route-legal",
  "route-stale-target",
  "route-already-active",
  "route-target-options",
  "route-draft-md",
  "route-draft-preview",
  "route-component-absent",
  "route-continue",
  "route-replay-accepted",
  "route-replay-rejected",
  "surface-server",
  "surface-unauthenticated",
  "surface-logging-out",
  "surface-forced-logout",
  "surface-signup",
  "surface-store-target",
  "surface-already-current",
  "surface-public",
  "surface-example",
  "surface-anonymous",
  "surface-composer-content",
  "surface-code-fullscreen",
  "surface-embed-fullscreen",
  "surface-wiki-fullscreen",
  "surface-live-message",
  "surface-hash-target",
  "surface-hash-message",
  "surface-hash-message-alias",
  "surface-hash-embed",
  "surface-hash-embed-alias",
  "surface-hash-scroll",
  "surface-key-absent",
  "surface-selection-absent",
  "surface-incognito",
  "surface-anonymous-selection",
  "surface-draft-only",
  "surface-team-context",
  "surface-published",
  "selection-entry-absent",
  "selection-source-absent",
  "invalidation-metadata",
  "invalidation-metadata-local-list",
  "invalidation-metadata-chat-updated",
  "invalidation-metadata-draft-save",
  "invalidation-metadata-chat-row",
  "invalidation-metadata-draft-websocket",
  "invalidation-metadata-draft-delete-sender",
  "invalidation-metadata-sync-draft",
  "invalidation-metadata-sync-header",
  "invalidation-metadata-phase-sync",
  "invalidation-message",
  "invalidation-key",
  "invalidation-delete",
  "invalidation-unknown",
  "invalidation-workspace-clear",
  "invalidation-eviction",
  "selection-source-target",
  "selection-window-absent",
  "selection-header-mismatch",
  "selection-accepted",
  "window-account-absent",
  "window-miss",
  "window-account-mismatch",
  "window-epoch-mismatch",
  "window-revision-mismatch",
  "window-accepted",
  "admission-account-absent",
  "admission-stale-read",
  "admission-private-selection",
  "admission-empty-window",
  "admission-message-target",
  "admission-unsettled-message",
  "admission-snapshot-failed",
  "admission-oversized",
  "admission-accepted",
  "admission-evicted"
] as const);
type RecentReplayDiagnosticReason = typeof RECENT_REPLAY_DIAGNOSTIC_REASONS[number];
const RECENT_REPLAY_DIAGNOSTIC_PROPERTY = '__openmatesRecentReplayDiagnostics';
const RECENT_REPLAY_DIAGNOSTIC_ENABLED_PROPERTY = '__openmatesRecentReplayDiagnosticsEnabled';
const MAX_RECENT_REPLAY_DIAGNOSTICS = 64;
let recentReplayDiagnostics: readonly RecentReplayDiagnosticReason[] = Object.freeze([]);

export function recordRecentReplayDiagnostic(reason: RecentReplayDiagnosticReason): void {
  try {
    if (typeof window === 'undefined' || !RECENT_REPLAY_DIAGNOSTIC_REASONS.includes(reason)) return;
    const enabled = Object.getOwnPropertyDescriptor(window, RECENT_REPLAY_DIAGNOSTIC_ENABLED_PROPERTY);
    // Compare only primitive data. Never inspect externally supplied objects/proxies.
    if (!enabled || !('value' in enabled) || enabled.value !== true) return;
    const descriptor = Object.getOwnPropertyDescriptor(window, RECENT_REPLAY_DIAGNOSTIC_PROPERTY);
    if (descriptor && (!('value' in descriptor) || !descriptor.writable)) return;
    // Only this module owns the ring. Publish primitive JSON, never an array or callback.
    const next = Object.freeze([...recentReplayDiagnostics.slice(-(MAX_RECENT_REPLAY_DIAGNOSTICS - 1)), reason]);
    const receipt = JSON.stringify(next);
    Object.defineProperty(window, RECENT_REPLAY_DIAGNOSTIC_PROPERTY, {
      value: receipt, writable: true, configurable: descriptor?.configurable ?? true,
      enumerable: descriptor?.enumerable ?? false
    });
    recentReplayDiagnostics = next;
  } catch { /* Observation must never interrupt the existing path. */ }
}

/** Return the already evaluated predicate unchanged, preserving OR short circuiting. */
export function observeRecentReplayVeto<T>(reason: RecentReplayDiagnosticReason, veto: T): T {
  if (veto) recordRecentReplayDiagnostic(reason);
  return veto;
}

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

export type RecentChatInvalidationCategory = 'metadata' | 'metadata-local-list' | 'metadata-chat-updated' | 'metadata-draft-save' | 'metadata-chat-row' | 'metadata-draft-websocket' | 'metadata-draft-delete-sender' | 'metadata-sync-draft' | 'metadata-sync-header' | 'metadata-phase-sync' | 'message' | 'key' | 'delete' | 'unknown';

// Runtime callers may violate TypeScript. Switch compares primitives without coercion
// and only forwards module-owned literals into the diagnostic ring.
function recordRecentChatInvalidation(category: RecentChatInvalidationCategory): void {
  switch (category) {
    case 'metadata-local-list': recordRecentReplayDiagnostic('invalidation-metadata-local-list'); break;
    case 'metadata-chat-updated': recordRecentReplayDiagnostic('invalidation-metadata-chat-updated'); break;
    case 'metadata-draft-save': recordRecentReplayDiagnostic('invalidation-metadata-draft-save'); break;
    case 'metadata-chat-row': recordRecentReplayDiagnostic('invalidation-metadata-chat-row'); break;
    case 'metadata-draft-websocket': recordRecentReplayDiagnostic('invalidation-metadata-draft-websocket'); break;
    case 'metadata-draft-delete-sender': recordRecentReplayDiagnostic('invalidation-metadata-draft-delete-sender'); break;
    case 'metadata-sync-draft': recordRecentReplayDiagnostic('invalidation-metadata-sync-draft'); break;
    case 'metadata-sync-header': recordRecentReplayDiagnostic('invalidation-metadata-sync-header'); break;
    case 'metadata-phase-sync': recordRecentReplayDiagnostic('invalidation-metadata-phase-sync'); break;
    case 'metadata': recordRecentReplayDiagnostic('invalidation-metadata'); break;
    case 'message': recordRecentReplayDiagnostic('invalidation-message'); break;
    case 'key': recordRecentReplayDiagnostic('invalidation-key'); break;
    case 'delete': recordRecentReplayDiagnostic('invalidation-delete'); break;
    default: recordRecentReplayDiagnostic('invalidation-unknown');
  }
}

/** A committed message mutation makes the last decrypted window unsafe to replay. */
export function invalidateRecentChatWindow(chatId: string, category: RecentChatInvalidationCategory = 'unknown'): void {
  rememberRevision(chatId, ++nextRevision);
  const invalidated = cache.delete(chatId);
  if (invalidated) recordRecentChatInvalidation(category);
  signalInvalidation();
}

export function invalidateRecentChatWindowForMessage(messageId: string): void {
  for (const [chatId, entry] of cache) {
    if (entry.messages.some((message) => message.message_id === messageId)) invalidateRecentChatWindow(chatId, 'message');
  }
}

export function clearRecentChatWindows(): void {
  const hadEntries = cache.size > 0;
  cache.clear();
  revisions.clear();
  if (hadEntries) recordRecentReplayDiagnostic('invalidation-workspace-clear');
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
  if (!accountId) { recordRecentReplayDiagnostic('admission-account-absent'); return false; }
  if (observeRecentReplayVeto('admission-stale-read', !isRecentChatReadCurrent(chatId, expectedEpoch, expectedRevision))) return false;
  if (observeRecentReplayVeto('admission-private-selection', sourceChat && (sourceChat.is_incognito || sourceChat.is_anonymous || sourceChat.is_hidden_candidate))) return false;
  if (observeRecentReplayVeto('admission-empty-window', window.messages.length === 0) || observeRecentReplayVeto('admission-message-target', window.messages.some((message) => message.chat_id !== chatId))) return false;
  // Only settled, persisted messages can be replayed on a future selection.
  if (observeRecentReplayVeto('admission-unsettled-message', window.messages.some((message) =>
    typeof message.content !== 'string'
    || (message as Message & { _decryptionPending?: boolean })._decryptionPending
    || ['sending', 'processing', 'streaming', 'waiting_for_upload', 'waiting_for_internet'].includes(message.status)
  ))) return false;
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
    recordRecentReplayDiagnostic('admission-snapshot-failed');
    return false;
  }
  if (observeRecentReplayVeto('admission-oversized', estimatePayloadBytes(entry, MAX_RECENT_WINDOW_BYTES) > MAX_RECENT_WINDOW_BYTES)) return false;
  // Size/has do not touch LRU order. Observe any entries lost during existing trim.
  const expectedCount = cache.size + (cache.has(chatId) ? 0 : 1);
  cache.set(chatId, entry);
  if (cache.size < expectedCount) recordRecentReplayDiagnostic('invalidation-eviction');
  const admitted = cache.has(chatId);
  recordRecentReplayDiagnostic(admitted ? 'admission-accepted' : 'admission-evicted');
  return admitted;
}

export function getRecentChatWindow(chat: Chat): RecentChatWindow | null {
  const accountId = get(userProfile).user_id;
  if (!accountId) { recordRecentReplayDiagnostic('window-account-absent'); return null; }
  const entry = cache.get(chat.chat_id);
  if (!entry) { recordRecentReplayDiagnostic('window-miss'); return null; }
  if (observeRecentReplayVeto('window-account-mismatch', entry.accountId !== accountId) || observeRecentReplayVeto('window-epoch-mismatch', entry.epoch !== getWorkspaceCacheEpoch()) || observeRecentReplayVeto('window-revision-mismatch', entry.revision !== getRecentChatRevision(chat.chat_id))) {
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
  if (!entry) { recordRecentReplayDiagnostic('selection-entry-absent'); return null; }
  if (!entry.sourceChat) { recordRecentReplayDiagnostic('selection-source-absent'); return null; }
  if (entry.sourceChat.chat_id !== chatId) { recordRecentReplayDiagnostic('selection-source-target'); return null; }
  const window = getRecentChatWindow(entry.sourceChat);
  if (!window) { recordRecentReplayDiagnostic('selection-window-absent'); return null; }
  if (!recentChatHeaderMatches(entry.sourceChat, window.header)) { recordRecentReplayDiagnostic('selection-header-mismatch'); return null; }
  recordRecentReplayDiagnostic('selection-accepted');
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

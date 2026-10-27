/** Conditional cleanup of a new call shell; deletion always uses server fanout. */
import type { Chat, Message } from '../types/chat';
import { get } from 'svelte/store';
import { chatDB } from './db';
import { inspectDraftContent } from './drafts/draftContent';
import { webSocketService } from './websocketService';
import { getWorkspaceCacheIdentity } from './workspaceQueryCache';
import { getWorkspaceCacheEpoch } from './workspaceCacheLifecycle';
import { parseVoiceCallHistoryEvent, voiceCallLifecycleMessageId } from './voiceCallLifecycleEvent';

export interface EmptyVoiceCallCleanupInput {
  chatId: string;
  /** Echoed by voice_call_chat_prepare only for an eligible new shell. */
  cleanupAttemptId: string;
  callId: string | null;
  expectedMessagesVersion: number;
}
export interface EmptyVoiceCallCleanupSnapshot {
  chat: Chat | null;
  messages: Message[];
  artifactCount: number;
  pendingOperationCount: number;
  hasDraft: boolean;
  hasOrdinaryText: boolean;
  hasPendingTurn: boolean;
}

export interface EmptyVoiceCallCleanupSignals {
  hasLocalOrdinaryText: boolean;
  hasPendingTurn: boolean;
  hasLocalDraft?: boolean;
  isCurrent: () => boolean;
}
const unreadableSnapshot = (): EmptyVoiceCallCleanupSnapshot => ({
  chat: null, messages: [], artifactCount: 1, pendingOperationCount: 1,
  hasDraft: true, hasOrdinaryText: true, hasPendingTurn: true,
});

/** Load editor modules once, then return a synchronous final check suitable
 * for the same IndexedDB transaction that conditionally erases the shell.
 * True means no unsaved editor/session draft; unreadable state returns false. */
export async function prepareEmptyVoiceCallLocalDraftGuard(chatId: string): Promise<() => boolean> {
  try {
    const [core, state] = await Promise.all([import('./drafts/draftCore'), import('./drafts/draftState')]);
    const identity = getWorkspaceCacheIdentity(), epoch = getWorkspaceCacheEpoch();
    return () => {
      try {
        if (!identity || identity !== getWorkspaceCacheIdentity() || epoch !== getWorkspaceCacheEpoch()) return false;
        const draft = get(state.draftEditorUIState);
        const ownsEditor = draft.currentChatId === chatId || draft.newlyCreatedChatIdToSelect === chatId
          || draft.currentChatId === null;
        if (ownsEditor) {
          if (draft.hasUnsavedChanges || draft.isSaveInProgress || draft.isSwitchingContext
            || draft.lastSavedContentMarkdown?.trim()) return false;
          const editor = core.getEditorInstance();
          if (editor && !editor.isDestroyed && inspectDraftContent(editor.getJSON()).hasMeaningfulContent) return false;
        }
        return !sessionStorage.getItem(`draft_${chatId}`);
      } catch { return false; }
    };
  } catch { return () => false; }
}

/** Read current durable local state and the active editor before requesting a
 * server fence. Read-only transactions never remove work, and unreadable/older
 * schemas preserve the shell. Completed lifecycle outboxes are not pending. */
export async function readEmptyVoiceCallCleanupSnapshot(
  input: EmptyVoiceCallCleanupInput, signals: EmptyVoiceCallCleanupSignals,
): Promise<EmptyVoiceCallCleanupSnapshot> {
  try {
    if (!signals.isCurrent()) return unreadableSnapshot();
    await chatDB.init();
    const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(input.chatId)))]
      .map(byte => byte.toString(16).padStart(2, '0')).join('');
    const artifactStores = ['embeds', 'embed_keys', 'chat_compression_checkpoints',
      'message_highlights', 'code_run_outputs', 'notebook_run_outputs'];
    const queueStores = ['pending_sync_changes', 'pending_embed_operations', 'pending_embed_share_updates'];
    const stores = ['chats', 'messages', ...artifactStores, ...queueStores, 'pending_og_metadata_updates'];
    const tx = await chatDB.getTransaction(stores, 'readonly');
    const read = <T>(request: IDBRequest<T>) => new Promise<T>((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error ?? new Error('Cleanup snapshot read failed'));
    });
    const complete = new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onabort = tx.onerror = () => reject(tx.error ?? new Error('Cleanup snapshot transaction failed'));
    });
    const rawChat = read(tx.objectStore('chats').get(input.chatId)) as Promise<Chat | undefined>;
    const rawMessages = read(tx.objectStore('messages').index('chat_id').getAll(input.chatId, 4)) as Promise<Array<Message & Record<string, unknown>>>;
    const artifactReads = artifactStores.map(store => read(tx.objectStore(store)
      .index(store === 'embeds' || store === 'embed_keys' ? 'hashed_chat_id' : 'chat_id')
      .count(store === 'embeds' || store === 'embed_keys' ? hash : input.chatId)));
    const queueReads = queueStores.map(store => read(tx.objectStore(store).getAll(undefined, 257)) as Promise<Array<Record<string, unknown>>>);
    const metadataRead = read(tx.objectStore('pending_og_metadata_updates').index('chat_id').count(input.chatId));
    const [raw, rows, counts, queues, metadataCount] = await Promise.all([
      rawChat, rawMessages, Promise.all(artifactReads), Promise.all(queueReads), metadataRead, complete,
    ]);
    const [chat, messages, localDraftSafe] = await Promise.all([
      chatDB.getChat(input.chatId), chatDB.getMessagesForChat(input.chatId),
      prepareEmptyVoiceCallLocalDraftGuard(input.chatId),
    ]);
    if (!signals.isCurrent() || !raw || !chat) return unreadableSnapshot();
    const queueTouchesChat = (row: Record<string, unknown>): boolean => {
      const payload = row.store_embed_payload && typeof row.store_embed_payload === 'object'
        ? row.store_embed_payload as Record<string, unknown> : row;
      const id = row.chat_id ?? row.chatId ?? payload.chat_id;
      const hashedId = row.hashed_chat_id ?? payload.hashed_chat_id;
      if (typeof id === 'string') return id === input.chatId;
      if (typeof hashedId === 'string') return hashedId === hash;
      return true; // Scope cannot be proved, so retain the shell.
    };
    const pendingOperationCount = metadataCount + queues.reduce((count, rows) => count
      + (rows.length > 256 ? 1 : rows.filter(queueTouchesChat).length), 0);
    const pendingMessage = rows.some(row => {
      const outbox = row.call_persistence_v1 as { entries?: unknown[]; typed_pending?: boolean } | undefined;
      return row.status !== 'synced' || Boolean(row.pending_turn_preflight_v1)
        || Boolean(row.pending_encrypted_turn_preflight_v1) || Boolean(row.pending_encrypted_embed_bundle_v1)
        || Boolean(outbox?.typed_pending) || Boolean(outbox?.entries?.length);
    });
    // A session draft should not normally exist for an authenticated shell, but
    // preserving it is safer than losing an interrupted sign-in migration.
    return { chat, messages, artifactCount: counts.reduce((sum, count) => sum + count, 0), pendingOperationCount,
      hasDraft: signals.hasLocalDraft === true || !localDraftSafe()
        || Boolean(raw.encrypted_draft_md) || Boolean(raw.encrypted_draft_preview),
      hasOrdinaryText: signals.hasLocalOrdinaryText,
      hasPendingTurn: signals.hasPendingTurn || pendingMessage,
    };
  } catch { return unreadableSnapshot(); }
}

/** Fail closed for unknown or locally unsaved work, including ordinary text
 * that failed admission and therefore never became a durable server message. */
export function isEmptyVoiceCallCleanupEligible(
  input: EmptyVoiceCallCleanupInput, snapshot: EmptyVoiceCallCleanupSnapshot,
): boolean {
  const chat = snapshot.chat;
  if (!chat || chat.chat_id !== input.chatId || chat.team_id || chat.chat_visibility === 'direct'
    || chat.is_incognito || chat.is_anonymous || chat.pinned || chat.is_shared
    || (chat as Chat & { title_is_manual?: boolean }).title_is_manual || chat.encrypted_title || chat.title || chat.encrypted_chat_summary
    || chat.message_window_has_more_before || chat.embed_window_has_more_before
    || chat.messages_v !== input.expectedMessagesVersion || (chat.draft_v ?? 0) !== 0
    || snapshot.artifactCount !== 0 || snapshot.pendingOperationCount !== 0
    || snapshot.hasDraft !== false || snapshot.hasOrdinaryText !== false || snapshot.hasPendingTurn !== false) return false;
  const expected = input.callId === null ? [] : [
    voiceCallLifecycleMessageId(input.callId, 'started'), voiceCallLifecycleMessageId(input.callId, 'ended'),
  ];
  if (snapshot.messages.length !== expected.length) return false;
  const seen = new Set<string>();
  return snapshot.messages.every(message => {
    const event = parseVoiceCallHistoryEvent(message.content ?? '');
    if (message.chat_id !== input.chatId || message.role !== 'system' || message.status !== 'synced'
      || !expected.includes(message.message_id) || seen.has(message.message_id)
      || !event || event.call_id !== input.callId
      || voiceCallLifecycleMessageId(event.call_id, event.action) !== message.message_id) return false;
    seen.add(message.message_id);
    const row = message as Message & { call_persistence_v1?: { entries?: unknown[]; typed_pending?: boolean } };
    return !row.call_persistence_v1?.typed_pending && !row.call_persistence_v1?.entries?.length;
  });
}

/** The caller must derive snapshot counters from current local storage and
 * controller state. This helper never calls generic delete_chat or erases local
 * content: normal chat_deleted handling must keep its atomic local guards. */
export async function cleanupEmptyVoiceCallChat(
  input: EmptyVoiceCallCleanupInput,
  readSnapshot: () => Promise<EmptyVoiceCallCleanupSnapshot>,
): Promise<{ accepted: boolean; localEligible: boolean }> {
  const identity = getWorkspaceCacheIdentity();
  const epoch = getWorkspaceCacheEpoch();
  const current = () => Boolean(identity) && identity === getWorkspaceCacheIdentity()
    && epoch === getWorkspaceCacheEpoch();
  const connection = webSocketService.getConnectionForSend();
  const currentConnection = () => current() && webSocketService.getConnectionForSend() === connection;
  if (!connection || !currentConnection() || !/^[0-9a-f-]{36}$/.test(input.cleanupAttemptId)
    || !Number.isSafeInteger(input.expectedMessagesVersion) || input.expectedMessagesVersion < 0
    || (input.callId !== null && !/^[a-f0-9]{32}$/.test(input.callId))) {
    return { accepted: false, localEligible: false };
  }
  try {
    // Server eligibility follows final settlement. Give that durable work a
    // bounded window while checking fresh local authority before every request.
    const startedAt = performance.now();
    const deadlineMs = 30_000;
    const requestTimesMs = [0, 250, 1000, 3000, 7000, 13_000, 21_000, 29_000];
    for (const requestTimeMs of requestTimesMs) {
      const waitMs = requestTimeMs - (performance.now() - startedAt);
      if (waitMs > 0) await new Promise(resolve => setTimeout(resolve, waitMs));
      if (!currentConnection()) break;
      const state = await readSnapshot();
      const remainingMs = deadlineMs - (performance.now() - startedAt);
      if (!currentConnection() || remainingMs <= 0
        || !isEmptyVoiceCallCleanupEligible(input, state)) break;
      const requestId = crypto.randomUUID();
      let dispose = () => {};
      const receipt = new Promise<boolean>(resolve => {
        const listener = (payload: Record<string, unknown>) => {
          if (payload.request_id !== requestId || payload.chat_id !== input.chatId) return;
          dispose();
          resolve(payload.accepted === true);
        };
        const timer = setTimeout(() => { dispose(); resolve(false); }, Math.min(3000, remainingMs));
        dispose = () => { clearTimeout(timer); webSocketService.off('empty_call_chat_cleanup_result', listener); };
        webSocketService.on('empty_call_chat_cleanup_result', listener);
      });
      try {
        await webSocketService.sendMessage('delete_empty_call_chat', {
          request_id: requestId, chat_id: input.chatId, cleanup_attempt_id: input.cleanupAttemptId,
          call_id: input.callId, expected_messages_v: input.expectedMessagesVersion,
          lifecycle_message_ids: input.callId === null ? [] : [
            voiceCallLifecycleMessageId(input.callId, 'started'), voiceCallLifecycleMessageId(input.callId, 'ended'),
          ],
        }, { expectedConnection: connection });
        if (await receipt) {
          const state = await readSnapshot();
          return { accepted: true, localEligible: currentConnection()
            && isEmptyVoiceCallCleanupEligible(input, state) };
        }
      } finally { dispose(); }
    }
  } catch { /* Missing/stale authority preserves all local content. */ }
  return { accepted: false, localEligible: false };
}

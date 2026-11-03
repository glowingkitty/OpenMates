/**
 * Typed Rust-core adapter for chat read state and chat management (flag-on
 * only): visible-message receipts, private bookmarks, highlights, chat
 * management frames, the pending-deletion queue, forks and Project placement.
 * The binding computes every payload and ciphertext; callers keep the
 * socket, HTTP, IndexedDB, localStorage, events and notifications.
 */
import { bindingError, type ChatStateBinding, type ChatStateFrame, type ReceiptLedgerBinding } from './chatStateBinding';
import type { MessageHighlight } from '../../../types/chat';

export type ReceiptDecision =
  | { decision: 'refused' | 'recent' }
  | { decision: 'in_flight' | 'send'; ticket: number };

export interface ReceiptScope { ownerId: string; chatId: string; epoch: number; connection?: number }

export class RustReceiptLedger {
  constructor(private readonly ledger: ReceiptLedgerBinding) {}
  report(scope: ReceiptScope, messageId: string, nowMs: number): ReceiptDecision {
    return JSON.parse(this.ledger.report(scope.ownerId, scope.chatId, scope.epoch, scope.connection, messageId, nowMs));
  }
  settle(ticket: number, sent: boolean, nowMs: number): boolean {
    return this.ledger.settle(ticket, sent, nowMs);
  }
}

export type BookmarkIndex = Record<string, string[]>;
export interface HighlightWrite { type: string; payload: Record<string, unknown>; record: MessageHighlight | null }
export type HighlightInbound = { store: MessageHighlight } | { drop: 'undecryptable' | 'missing_anchor' | 'missing_embed' | 'unknown_kind' };
export interface TitleUpdate extends ChatStateFrame { encryptedTitle: string; titleV: number; updatedAt: number }
export interface SummaryUpdate extends ChatStateFrame { encryptedChatSummary: string; metadataV: number; updatedAt: number }
export type ActiveChatPlan = { skip: true } | ({ skip: false; persistLastOpened: string | null } & ChatStateFrame);
export interface PendingDeletionEdit { changed: boolean; write: string | null }
export type PlacementOp =
  | { op: 'move_item'; itemId: string; chatId: string }
  | { op: 'add_chat'; chatId: string }
  | { op: 'remove_from_project'; projectId: string; chatId: string };

/** Fork source row: decrypted message with `content` already a string. */
export interface ForkSourceMessage {
  message_id: string;
  role?: unknown;
  created_at?: number;
  content?: string;
  encrypted_content?: string | null;
  sender_name?: string;
  category?: string;
  model_name?: string;
}
export interface ForkChatSummary {
  chat_id: string;
  encrypted_chat_key: string;
  encrypted_title: string;
  encrypted_category?: string;
  encrypted_icon?: string;
  user_id?: string;
  message_count: number;
  now_seconds: number;
}

/** `JSON.stringify` non-string content exactly like `reencryptMessage`. */
export function forkSourceFromMessage(message: { message_id: string; role?: unknown; created_at?: number; content?: unknown; encrypted_content?: string | null; sender_name?: string; category?: string; model_name?: string }): ForkSourceMessage {
  const content = message.content ? (typeof message.content === 'string' ? message.content : JSON.stringify(message.content)) : undefined;
  return { message_id: message.message_id, role: message.role, created_at: message.created_at, content, encrypted_content: message.encrypted_content,
    sender_name: message.sender_name, category: message.category, model_name: message.model_name };
}

function call<T>(run: () => T): T {
  try {
    return run();
  } catch (reason) {
    throw bindingError(reason);
  }
}

async function callAsync<T>(run: () => Promise<T>): Promise<T> {
  try {
    return await run();
  } catch (reason) {
    throw bindingError(reason);
  }
}

export function createChatStateAdapter(b: ChatStateBinding) {
  return {
    createReceiptLedger: () => new RustReceiptLedger(b.createReceiptLedger()),

    // Bookmarks: account (master-key encrypted settings), device and transient.
    toggleAccountBookmark: (masterKey: CryptoKey, encryptedSettings: string | undefined, chatId: string, messageId: string, legacyIds: string[] = []) =>
      callAsync(async () => JSON.parse(await b.chat_state_bookmarks_toggle_account(masterKey, encryptedSettings, chatId, messageId, legacyIds)) as { encryptedSettings: string; index: BookmarkIndex }),
    readAccountBookmarks: (masterKey: CryptoKey, encryptedSettings: string | undefined) =>
      callAsync(async () => JSON.parse(await b.chat_state_bookmarks_read_account(masterKey, encryptedSettings)) as BookmarkIndex),
    toggleDeviceBookmark: (stored: string | null, chatId: string, messageId: string, legacyIds: string[] = []) =>
      call(() => b.chat_state_bookmarks_toggle_device(stored ?? undefined, chatId, messageId, legacyIds)),
    decodeDeviceBookmarks: (stored: string | null) => call(() => b.chat_state_bookmarks_decode_device(stored ?? undefined)),

    // Highlights: chat-key encrypted semantic payload, plaintext routing metadata.
    addHighlight: (record: MessageHighlight, chatKey: Uint8Array): HighlightWrite => call(() => JSON.parse(b.chat_state_highlight_add(JSON.stringify(record), chatKey))),
    updateHighlight: (record: MessageHighlight, chatKey: Uint8Array, nowSeconds: number): HighlightWrite =>
      call(() => JSON.parse(b.chat_state_highlight_update(JSON.stringify(record), chatKey, nowSeconds))),
    removeHighlight: (chatId: string, messageId: string, id: string): HighlightWrite => JSON.parse(b.chat_state_highlight_remove(chatId, messageId, id)),
    decodeHighlightAdded: (payload: unknown, chatKey: Uint8Array): HighlightInbound => call(() => JSON.parse(b.chat_state_highlight_decode_added(JSON.stringify(payload), chatKey))),
    decodeHighlightUpdated: (payload: unknown, chatKey: Uint8Array, cached: MessageHighlight | null): HighlightInbound =>
      call(() => JSON.parse(b.chat_state_highlight_decode_updated(JSON.stringify(payload), chatKey, cached ? JSON.stringify(cached) : undefined))),

    // Chat management frames. Callers keep ensureChatKeySafeForWrite first.
    updateTitle: (chatId: string, title: string, chatKey: Uint8Array, encryptedChatKey: string | undefined, titleV: number | undefined, nowSeconds: number): TitleUpdate =>
      call(() => JSON.parse(b.chat_state_update_title(chatId, title, chatKey, encryptedChatKey || undefined, titleV || undefined, nowSeconds))),
    updateSummary: (chatId: string, summary: string, chatKey: Uint8Array, encryptedChatKey: string, encryptedTitle: string | undefined,
      versions: { messages_v?: number; title_v?: number; metadata_v?: number; draft_v?: number }, nowSeconds: number): SummaryUpdate =>
      call(() => JSON.parse(b.chat_state_update_summary(chatId, summary, chatKey, encryptedChatKey, encryptedTitle || undefined, JSON.stringify(versions), nowSeconds))),
    pinFrame: (chatId: string, pinned: boolean): ChatStateFrame => JSON.parse(b.chat_state_pin_frame(chatId, pinned)),
    deleteChatFrame: (chatId: string, removeProjectEmbeds: boolean, embedIds: string[] = []): ChatStateFrame => JSON.parse(b.chat_state_delete_chat_frame(chatId, removeProjectEmbeds, embedIds)),
    deleteMessageFrame: (chatId: string, messageId: string, embedIds: string[] = []): ChatStateFrame => JSON.parse(b.chat_state_delete_message_frame(chatId, messageId, embedIds)),
    /** Protected embed count needing the confirm dialog, or `null`. */
    deletionDecision: (precheck: unknown): number | null => call(() => b.chat_state_deletion_decision(JSON.stringify(precheck)) ?? null),
    activeChatPlan: (chatId: string | null, authenticated: boolean, isPublicChat: boolean): ActiveChatPlan =>
      JSON.parse(b.chat_state_active_chat_plan(chatId ?? undefined, authenticated, isPublicChat)),
    hideDemoChat: (current: string[], chatId: string): string[] | null => b.chat_state_hide_demo_chat(current, chatId) ?? null,
    pendingDeletionEdit: (stored: string | null, chatId: string, add: boolean): PendingDeletionEdit => JSON.parse(b.chat_state_pending_deletions_edit(stored ?? undefined, chatId, add)),
    pendingDeletionIds: (stored: string | null): string[] => b.chat_state_pending_deletion_ids(stored ?? undefined),

    // Fork conversation.
    forkSelect: (messages: ForkSourceMessage[], upToMessageId: string): string[] => call(() => b.chat_state_fork_select(JSON.stringify(messages), upToMessageId)),
    forkReencryptBatch: (messages: ForkSourceMessage[], newChatId: string, chatKey: Uint8Array): Record<string, unknown>[] =>
      call(() => JSON.parse(b.chat_state_fork_reencrypt_batch(JSON.stringify(messages), newChatId, chatKey))),
    forkCopyField: (sourceCiphertext: string | null | undefined, sourceKey: Uint8Array, newKey: Uint8Array): string | undefined =>
      call(() => b.chat_state_fork_copy_field(sourceCiphertext ?? undefined, sourceKey, newKey)),
    forkEncryptTitle: (title: string, chatKey: Uint8Array): string => call(() => b.chat_state_fork_encrypt_title(title, chatKey)),
    forkFinalize: (chat: ForkChatSummary, rows: Record<string, unknown>[]): { record: Record<string, unknown>; payload: Record<string, unknown> } =>
      call(() => JSON.parse(b.chat_state_fork_finalize(JSON.stringify(chat), JSON.stringify(rows)))),
    normalizeExplainSelection: (selected: string): string => b.chat_state_normalize_explain_selection(selected),

    // Projects.
    planPlacement: (index: unknown, projectId: string, folderId: string | null, chatIds: string[], mode: 'add' | 'move'): PlacementOp[] =>
      call(() => JSON.parse(b.chat_state_plan_placement(JSON.stringify(index), projectId, folderId ?? undefined, chatIds, mode === 'move'))),
    assertOrganizable: (chats: { chat_id: string; is_incognito?: boolean; is_shared_by_others?: boolean; is_static: boolean; team_id?: string | null }[], activeTeamId: string | null): void =>
      call(() => b.chat_state_assert_organizable(JSON.stringify(chats.map(chat => ({ ...chat, is_incognito: !!chat.is_incognito, is_shared_by_others: !!chat.is_shared_by_others, team_id: chat.team_id ?? null }))), activeTeamId ?? undefined)),
    projectNamingTitles: (titles: string[]): string[] => b.chat_state_project_naming_titles(titles),
    validateProjectName: (proposed: string | undefined): string => call(() => b.chat_state_validate_project_name(proposed)),
  };
}

export type ChatStateAdapter = ReturnType<typeof createChatStateAdapter>;

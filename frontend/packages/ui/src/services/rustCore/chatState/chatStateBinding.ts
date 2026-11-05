/**
 * Worker binding surface of `openmates-browser-bindings` chat state (U11/U12):
 * receipts, bookmarks, highlights, hidden chats, chat management, forks and
 * Project placement. Every export lives in packages/openmates-browser-bindings
 * /src/browser_chat_state*.rs. The coordinator wires an instance through the
 * shared Rust worker (VITE_OPENMATES_RUST_CORE); with the flag off nothing here
 * runs and the legacy TypeScript services stay authoritative.
 *
 * Results are JSON strings; rejections are stable code strings: `locked`,
 * `crypto`, `protocol`, `cancelled`, `unavailable`, or a web error message
 * (for example `Bookmark limit reached`, `Fork point message not found`).
 */

/** `BrowserHiddenChatVault`: one per page; the combined secret stays in WASM. */
export interface HiddenChatVaultBinding {
  is_unlocked(): boolean;
  remaining_lockout_seconds(nowMs: number): number;
  unlock(code: string, salt: Uint8Array | undefined, encryptedChatKeys: string[], verifiedEncryptedChatKey: string | undefined, nowMs: number): Promise<number>;
  wrap_with_code(chatKey: Uint8Array, code: string, salt: Uint8Array | undefined, nowMs: number): Promise<string>;
  wrap(chatKey: Uint8Array): string;
  unwrap(encryptedChatKey: string): Uint8Array | undefined;
  classify(encryptedChatKey: string): Promise<{ class: 'normal' | 'hidden' | 'locked_candidate'; chatKey: Uint8Array | null }>;
  plan_hide(cachedChatKey: Uint8Array | undefined, encryptedChatKey: string | undefined): Promise<
    | { plan: 'needs_unlock' | 'already_hidden' | 'missing_key' }
    | { plan: 'hide'; encryptedChatKey: string; decryptedChatKey: Uint8Array | null }
  >;
  unhide(encryptedChatKey: string): Promise<{ encryptedChatKey: string }>;
  lock(): void;
  free(): void;
}

/** `BrowserReceiptLedger`: one per page. */
export interface ReceiptLedgerBinding {
  report(ownerId: string, chatId: string, epoch: number, connection: number | undefined, messageId: string, nowMs: number): string;
  settle(ticket: number, sent: boolean, nowMs: number): boolean;
  free(): void;
}

export interface ChatStateBinding {
  createHiddenChatVault(masterKey: CryptoKey): HiddenChatVaultBinding;
  createReceiptLedger(): ReceiptLedgerBinding;
  chat_state_hidden_key_update_payload(chatId: string, encryptedChatKey: string, messagesV: number | undefined, titleV: number | undefined, lastEdited: number | undefined, nowSeconds: number): string;
  chat_state_bookmarks_toggle_account(masterKey: CryptoKey, encryptedSettings: string | undefined, chatId: string, messageId: string, legacyIds: string[]): Promise<string>;
  chat_state_bookmarks_read_account(masterKey: CryptoKey, encryptedSettings: string | undefined): Promise<string>;
  chat_state_bookmarks_toggle_device(stored: string | undefined, chatId: string, messageId: string, legacyIds: string[]): string;
  chat_state_bookmarks_decode_device(stored: string | undefined): string[];
  chat_state_highlight_add(recordJson: string, chatKey: Uint8Array): string;
  chat_state_highlight_update(recordJson: string, chatKey: Uint8Array, nowSeconds: number): string;
  chat_state_highlight_remove(chatId: string, messageId: string, id: string): string;
  chat_state_highlight_decode_added(payloadJson: string, chatKey: Uint8Array): string;
  chat_state_highlight_decode_updated(payloadJson: string, chatKey: Uint8Array, cachedJson: string | undefined): string;
  chat_state_update_title(chatId: string, title: string, chatKey: Uint8Array, encryptedChatKey: string | undefined, titleV: number | undefined, nowSeconds: number): string;
  chat_state_update_summary(chatId: string, summary: string, chatKey: Uint8Array, encryptedChatKey: string, encryptedTitle: string | undefined, versionsJson: string, nowSeconds: number): string;
  chat_state_pin_frame(chatId: string, pinned: boolean): string;
  chat_state_delete_chat_frame(chatId: string, removeProjectEmbeds: boolean, embedIdsToDelete: string[]): string;
  chat_state_delete_message_frame(chatId: string, messageId: string, embedIdsToDelete: string[]): string;
  chat_state_deletion_decision(precheckJson: string): number | undefined;
  chat_state_active_chat_plan(chatId: string | undefined, authenticated: boolean, isPublicChat: boolean): string;
  chat_state_hide_demo_chat(current: string[], chatId: string): string[] | undefined;
  chat_state_pending_deletions_edit(stored: string | undefined, chatId: string, add: boolean): string;
  chat_state_pending_deletion_ids(stored: string | undefined): string[];
  chat_state_fork_select(messagesJson: string, upToMessageId: string): string[];
  chat_state_fork_reencrypt_batch(messagesJson: string, newChatId: string, chatKey: Uint8Array): string;
  chat_state_fork_copy_field(sourceCiphertext: string | undefined, sourceKey: Uint8Array, newKey: Uint8Array): string | undefined;
  chat_state_fork_encrypt_title(title: string, chatKey: Uint8Array): string;
  chat_state_fork_finalize(chatJson: string, rowsJson: string): string;
  chat_state_normalize_explain_selection(selected: string): string;
  chat_state_plan_placement(indexJson: string, projectId: string, folderId: string | undefined, chatIds: string[], move: boolean): string;
  chat_state_assert_organizable(chatsJson: string, activeTeamId: string | undefined): void;
  chat_state_project_naming_titles(titles: string[]): string[];
  chat_state_validate_project_name(proposed: string | undefined): string;
}

/** A socket frame for `webSocketService.sendMessage(type, payload)`. */
export interface ChatStateFrame { type: string; payload: Record<string, unknown> }

/** Rejection reasons from the binding are plain strings; surface them as Errors. */
export function bindingError(reason: unknown): Error {
  return reason instanceof Error ? reason : new Error(typeof reason === 'string' ? reason : 'unavailable');
}

export function bindingCode(reason: unknown): string {
  return typeof reason === 'string' ? reason : reason instanceof Error ? reason.message : 'unavailable';
}

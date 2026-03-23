/**
 * editMessageStore.ts — Global state for the "Edit message" feature.
 *
 * When a user chooses "Edit" from the message context menu, this store
 * holds the editing context so that ChatHistory can dim messages,
 * MessageInput can populate the editor and show a banner, and
 * sendHandlers can delete messages from the edit point before re-sending.
 *
 * Architecture: docs/architecture/chat-edit-reprocess.md (pending)
 */

import { writable, get } from 'svelte/store';

export interface EditMessageState {
  /** Chat ID the edited message belongs to */
  chatId: string;
  /** The user message being edited */
  messageId: string;
  /** Original markdown content of the message */
  messageContent: string;
  /** created_at timestamp of the edited message — messages at/after this are dimmed */
  createdAt: number;
}

export const editMessageStore = writable<EditMessageState | null>(null);

/**
 * Enter edit mode for a specific user message.
 * Populates the store so ChatHistory dims messages and MessageInput loads content.
 */
export function startEdit(chatId: string, messageId: string, messageContent: string, createdAt: number): void {
  editMessageStore.set({ chatId, messageId, messageContent, createdAt });
  console.debug('[editMessageStore] Edit started:', { chatId, messageId, createdAt });
}

/**
 * Exit edit mode without sending. Restores all messages to normal.
 */
export function cancelEdit(): void {
  const current = get(editMessageStore);
  if (current) {
    console.debug('[editMessageStore] Edit cancelled for message:', current.messageId);
  }
  editMessageStore.set(null);
}

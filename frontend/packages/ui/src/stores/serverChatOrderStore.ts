// frontend/packages/ui/src/stores/serverChatOrderStore.ts
/**
 * @file serverChatOrderStore.ts
 * @description Svelte store for managing the server-defined order of chat IDs.
 * This order is typically received during the initial sync process and is used
 * to influence the display order of chats in the UI, in conjunction with other
 * sorting criteria like last_edited_overall_timestamp.
 */
import { writable } from 'svelte/store';

/**
 * Stores an array of chat_id strings in the order provided by the server.
 * This helps in maintaining a consistent chat list order across devices,
 * especially for pinned chats or other server-side sorting logic.
 */
export const serverChatOrder = writable<string[]>([]);

/**
 * Sets the server chat order.
 * @param {string[]} order - An array of chat_id strings.
 */
export function setServerChatOrder(order: string[]): void {
  serverChatOrder.set(order);
}

/**
 * Clears the server chat order, typically on logout or full reset.
 */
export function clearServerChatOrder(): void {
  serverChatOrder.set([]);
}
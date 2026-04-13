// frontend/packages/ui/src/stores/pendingWebhookChatsStore.ts
/**
 * Writable store tracking incoming webhook chats that are awaiting user
 * approval (webhook key had `require_confirmation=true` when it fired).
 *
 * Shape: Map<chat_id, { messageId, content, webhookId, firedAt }>
 *
 * Populated by chatSyncServiceHandlersWebhooks when a `webhook_chat` event
 * arrives with `status === "pending_confirmation"`. Cleared by the same
 * handler when a `webhook_chat_approved` or `webhook_chat_rejected` event
 * arrives from another device, or by the approval banner itself once the
 * user clicks Process or Reject.
 *
 * Consumed by WebhookPendingBanner.svelte, which renders a Process / Reject
 * prompt above the chat history whenever the active chat id is in the map.
 */

import { writable, derived, type Readable } from 'svelte/store';
import { activeChatStore } from './activeChatStore';

export interface PendingWebhookChat {
  chat_id: string;
  message_id: string;
  content: string;
  webhook_id: string;
  fired_at: number;
}

type PendingMap = Map<string, PendingWebhookChat>;

function createPendingWebhookChatsStore() {
  const { subscribe, update, set } = writable<PendingMap>(new Map());

  return {
    subscribe,
    add(entry: PendingWebhookChat): void {
      update((map) => {
        const next = new Map(map);
        next.set(entry.chat_id, entry);
        return next;
      });
    },
    remove(chat_id: string): void {
      update((map) => {
        if (!map.has(chat_id)) return map;
        const next = new Map(map);
        next.delete(chat_id);
        return next;
      });
    },
    has(chat_id: string): boolean {
      let hit = false;
      subscribe((map) => {
        hit = map.has(chat_id);
      })();
      return hit;
    },
    clear(): void {
      set(new Map());
    },
  };
}

export const pendingWebhookChatsStore = createPendingWebhookChatsStore();

/**
 * Derived store: the pending entry for the currently active chat, or null.
 * Components can subscribe to this directly to drive banner visibility.
 */
export const activeChatPendingWebhook: Readable<PendingWebhookChat | null> = derived(
  [pendingWebhookChatsStore, activeChatStore],
  ([$pending, $activeChatId]) => {
    if (!$activeChatId) return null;
    return $pending.get($activeChatId) ?? null;
  }
);

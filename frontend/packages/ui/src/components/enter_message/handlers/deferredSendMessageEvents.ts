/**
 * deferredSendMessageEvents.ts
 *
 * Bridges deferred-send completion back into the live chat UI.
 * The deferred sender runs after the composer has been cleared, so it cannot
 * use MessageInput's original sendMessage dispatch path. Instead it emits the
 * same chatUpdated shape ActiveChat already merges by stable message_id.
 */

import { chatSyncService } from "../../../services/chatSyncService";
import type { Message } from "../../../types/chat";

const CHAT_UPDATED_EVENT = "chatUpdated";
const DEFERRED_MESSAGE_UPDATED_TYPE = "message_updated";

export function notifyDeferredMessageFinalized(message: Message): void {
  chatSyncService.dispatchEvent(
    new CustomEvent(CHAT_UPDATED_EVENT, {
      detail: {
        chat_id: message.chat_id,
        type: DEFERRED_MESSAGE_UPDATED_TYPE,
        newMessage: message,
      },
    }),
  );
}

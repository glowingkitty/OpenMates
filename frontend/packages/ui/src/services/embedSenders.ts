import type { ChatSynchronizationService } from "./chatSyncService";
import { webSocketService } from "./websocketService";
import type { StoreEmbedPayload } from "../types/chat";
import { chatDB } from "./db";

/**
 * Send encrypted embed to server for Directus storage.
 * If the WebSocket is not connected, queues the operation in IndexedDB
 * for retry on reconnect.
 */
export async function sendStoreEmbedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: StoreEmbedPayload,
  embedKeysPayload?: { keys: Array<Record<string, unknown>> },
): Promise<void> {
  if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
    console.warn(
      `[EmbedSenders] WebSocket not connected - queuing embed ${payload.embed_id} for offline sync`,
    );
    await _queuePendingEmbedOperation(payload, embedKeysPayload);
    return;
  }

  try {
    console.debug(
      `[EmbedSenders] Sending encrypted embed ${payload.embed_id} to server`,
    );
    await webSocketService.sendMessage("store_embed", payload);
  } catch (error) {
    console.error(
      `[EmbedSenders] Error sending store_embed for ${payload.embed_id}, queuing for retry:`,
      error,
    );
    await _queuePendingEmbedOperation(payload, embedKeysPayload);
  }
}

/**
 * Send embed key wrappers to server.
 * If offline, the keys are already queued as part of the embed operation.
 */
export async function sendStoreEmbedKeysImpl(
  serviceInstance: ChatSynchronizationService,
  payload: { keys: Array<Record<string, unknown>> },
): Promise<void> {
  if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
    console.warn(
      "[EmbedSenders] WebSocket not connected - embed keys will be sent with queued embed operation",
    );
    return;
  }

  try {
    console.debug(
      `[EmbedSenders] Sending ${payload.keys.length} embed key wrapper(s) to server`,
    );
    await webSocketService.sendMessage("store_embed_keys", payload);
  } catch (error) {
    console.error("[EmbedSenders] Error sending store_embed_keys:", error);
    // Keys will be re-sent when the embed operation is flushed from the queue
  }
}

/**
 * Queue an embed operation in IndexedDB for later retry.
 */
async function _queuePendingEmbedOperation(
  storePayload: StoreEmbedPayload,
  keysPayload?: { keys: Array<Record<string, unknown>> },
): Promise<void> {
  try {
    await chatDB.addPendingEmbedOperation({
      operation_id: crypto.randomUUID(),
      embed_id: storePayload.embed_id,
      store_embed_payload: storePayload,
      store_embed_keys_payload: keysPayload,
      created_at: Date.now(),
    });
    console.info(
      `[EmbedSenders] Queued embed ${storePayload.embed_id} for offline sync`,
    );
  } catch (error) {
    console.error(`[EmbedSenders] Failed to queue embed operation:`, error);
  }
}

/**
 * Flush all pending embed operations from IndexedDB.
 * Called on WebSocket reconnect.
 */
export async function flushPendingEmbedOperations(): Promise<void> {
  try {
    const operations = await chatDB.getPendingEmbedOperations();
    if (operations.length === 0) return;

    console.info(
      `[EmbedSenders] Flushing ${operations.length} pending embed operation(s)`,
    );

    for (const op of operations) {
      try {
        // Send the encrypted embed
        await webSocketService.sendMessage(
          "store_embed",
          op.store_embed_payload,
        );

        // Send keys if present
        if (
          op.store_embed_keys_payload &&
          op.store_embed_keys_payload.keys.length > 0
        ) {
          await webSocketService.sendMessage(
            "store_embed_keys",
            op.store_embed_keys_payload,
          );
        }

        // Remove from queue on success
        await chatDB.removePendingEmbedOperation(op.operation_id);
        console.debug(
          `[EmbedSenders] Flushed embed operation ${op.embed_id}`,
        );
      } catch (error) {
        console.error(
          `[EmbedSenders] Failed to flush embed operation ${op.embed_id}:`,
          error,
        );
        // Leave in queue for next reconnect attempt
      }
    }
  } catch (error) {
    console.error(
      "[EmbedSenders] Error flushing pending embed operations:",
      error,
    );
  }
}

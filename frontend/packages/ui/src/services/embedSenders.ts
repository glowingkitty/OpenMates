import type { ChatSynchronizationService } from "./chatSyncService";
import { webSocketService } from "./websocketService";
import type { StoreEmbedDiffPayload, StoreEmbedPayload } from "../types/chat";
import { chatDB, type PendingEmbedOperation } from "./db";
import { computeSHA256 } from "../message_parsing/utils";
import {
  assertCanonicalEmbedWriteLease, withCanonicalEmbedWrite,
  type CanonicalEmbedWriteLease,
} from "./canonicalEmbedWriteCoordinator";

const EMBED_RECEIPT_TIMEOUT_MS = 30_000;
const MAX_ACTIVE_EMBED_RECEIPTS = 32;
const activePendingEmbedOperations = new Map<string, Promise<void>>();
let pendingEmbedFlush: Promise<void> | null = null;
let lastPendingEmbedOperationTime = 0;
let capacityDeferred = false;
let capacityDrainScheduled = false;

function scheduleCapacityDrain(): void {
  if (!capacityDeferred || capacityDrainScheduled) return;
  capacityDeferred = false;
  capacityDrainScheduled = true;
  globalThis.setTimeout(() => {
    capacityDrainScheduled = false;
    void flushPendingEmbedOperations();
  }, 0);
}

async function sendWithReceipt(
  type: "store_embed" | "store_embed_keys",
  confirmedType: "store_embed_confirmed" | "store_embed_keys_confirmed",
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const requestId = crypto.randomUUID();
  let stop = () => {};
  const confirmation = new Promise<Record<string, unknown>>((resolve, reject) => {
    const timer = globalThis.setTimeout(() => {
      stop();
      reject(new Error(`Canonical ${type} confirmation timed out.`));
    }, EMBED_RECEIPT_TIMEOUT_MS);
    const onConfirmed = (raw: unknown) => {
      const receipt = raw as Record<string, unknown>;
      if (receipt.request_id !== requestId) return;
      stop();
      resolve(receipt);
    };
    const onClose = () => {
      stop();
      reject(new Error(`Connection closed before canonical ${type} confirmation.`));
    };
    stop = () => {
      globalThis.clearTimeout(timer);
      webSocketService.off(confirmedType, onConfirmed);
      webSocketService.removeEventListener("close", onClose);
    };
    webSocketService.on(confirmedType, onConfirmed);
    webSocketService.addEventListener("close", onClose);
  });
  void confirmation.catch(() => {});
  try {
    await webSocketService.sendMessage(type, { ...payload, request_id: requestId });
    return await confirmation;
  } finally {
    stop();
  }
}

async function persistCanonicalEmbedOperation(operation: PendingEmbedOperation): Promise<void> {
  const head = operation.store_embed_payload;
  const headReceipt = await sendWithReceipt("store_embed", "store_embed_confirmed", head as unknown as Record<string, unknown>);
  const expectedDigest = await computeSHA256(head.encrypted_content);
  if (headReceipt.embed_id !== head.embed_id || headReceipt.canonical_digest !== expectedDigest) {
    throw new Error(`Canonical embed ${head.embed_id} receipt did not match its ciphertext.`);
  }
  const keys = operation.store_embed_keys_payload?.keys ?? [];
  if (keys.length === 0) return;
  const keyReceipt = await sendWithReceipt("store_embed_keys", "store_embed_keys_confirmed", { keys });
  if (keyReceipt.failed_count !== 0 || keyReceipt.created_count !== keys.length) {
    throw new Error(`Canonical embed ${head.embed_id} key wrappers were incomplete.`);
  }
}

async function persistQueuedEmbedOperation(
  operation: PendingEmbedOperation, lease?: CanonicalEmbedWriteLease,
): Promise<void> {
  const active = activePendingEmbedOperations.get(operation.operation_id);
  if (active) {
    try {
      await active;
      return;
    } catch {
      // The reconnect flush retries an operation whose previous socket closed.
    }
  }
  if (activePendingEmbedOperations.size >= MAX_ACTIVE_EMBED_RECEIPTS) {
    capacityDeferred = true;
    throw new Error("Canonical embed receipt capacity is full; operation remains queued for retry.");
  }
  const persist = async () => {
    const queued = (await chatDB.getPendingEmbedOperations())
      .filter((candidate) => candidate.embed_id === operation.embed_id)
      .sort((a, b) => a.created_at - b.created_at || a.operation_id.localeCompare(b.operation_id));
    const position = queued.findIndex((candidate) => candidate.operation_id === operation.operation_id);
    if (position < 0) return; // An earlier flush already committed this operation.
    for (const earlier of queued.slice(0, position)) {
      await persistCanonicalEmbedOperation(earlier);
      await chatDB.removePendingEmbedOperation(earlier.operation_id);
    }
    await persistCanonicalEmbedOperation(operation);
    await chatDB.removePendingEmbedOperation(operation.operation_id);
  };
  if (lease) assertCanonicalEmbedWriteLease(lease, operation.embed_id);
  const run = lease ? persist() : withCanonicalEmbedWrite(operation.embed_id, persist);
  activePendingEmbedOperations.set(operation.operation_id, run);
  try {
    await run;
  } finally {
    if (activePendingEmbedOperations.get(operation.operation_id) === run) {
      activePendingEmbedOperations.delete(operation.operation_id);
    }
    if (activePendingEmbedOperations.size < MAX_ACTIVE_EMBED_RECEIPTS) scheduleCapacityDrain();
  }
}

/**
 * Send encrypted embed to server for Directus storage.
 * If the WebSocket is not connected, queues the operation in IndexedDB
 * for retry on reconnect.
 */
export async function sendStoreEmbedImpl(
  serviceInstance: ChatSynchronizationService,
  payload: StoreEmbedPayload,
  embedKeysPayload?: { keys: Array<Record<string, unknown>> },
  lease?: CanonicalEmbedWriteLease,
): Promise<void> {
  if (lease) assertCanonicalEmbedWriteLease(lease, payload.embed_id);
  const createdAt = Math.max(Date.now(), lastPendingEmbedOperationTime + 0.001);
  lastPendingEmbedOperationTime = createdAt;
  const operation: PendingEmbedOperation = {
    operation_id: crypto.randomUUID(), embed_id: payload.embed_id,
    store_embed_payload: payload, store_embed_keys_payload: embedKeysPayload,
    created_at: createdAt,
  };
  await chatDB.addPendingEmbedOperation(operation);
  if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
    console.warn(
      `[EmbedSenders] WebSocket not connected - queuing embed ${payload.embed_id} for offline sync`,
    );
    return;
  }

  try {
    await persistQueuedEmbedOperation(operation, lease);
  } catch (error) {
    console.error(
      `[EmbedSenders] Canonical embed ${payload.embed_id} is pending retry:`,
      error,
    );
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
    throw new Error("Cannot store standalone embed keys while disconnected.");
  }
  const receipt = await sendWithReceipt("store_embed_keys", "store_embed_keys_confirmed", payload);
  if (receipt.failed_count !== 0 || receipt.created_count !== payload.keys.length) {
    throw new Error("Canonical embed key wrappers were incomplete.");
  }
}

/**
 * Send an encrypted embed version row to server.
 * This is only called after the receiving client encrypts snapshot/patch data
 * with the parent embed key.
 */
export async function sendStoreEmbedDiffImpl(
  serviceInstance: ChatSynchronizationService,
  payload: StoreEmbedDiffPayload,
): Promise<void> {
  if (!serviceInstance.webSocketConnected_FOR_SENDERS_ONLY) {
    console.warn(
      `[EmbedSenders] WebSocket not connected - encrypted diff row for ${payload.embed_id} v${payload.version_number} was not sent`,
    );
    return;
  }

  try {
    console.debug(
      `[EmbedSenders] Sending encrypted embed diff ${payload.embed_id} v${payload.version_number} to server`,
    );
    await webSocketService.sendMessage("store_embed_diff", payload);
  } catch (error) {
    console.error(
      `[EmbedSenders] Error sending store_embed_diff for ${payload.embed_id} v${payload.version_number}:`,
      error,
    );
  }
}

/**
 * Flush all pending embed operations from IndexedDB.
 * Called on WebSocket reconnect.
 */
export async function flushPendingEmbedOperations(): Promise<void> {
  if (pendingEmbedFlush) return pendingEmbedFlush;
  pendingEmbedFlush = (async () => {
    const operations = await chatDB.getPendingEmbedOperations();
    if (operations.length === 0) return;

    console.info(
      `[EmbedSenders] Flushing ${operations.length} pending embed operation(s)`,
    );

    for (const op of operations.sort((a, b) => a.created_at - b.created_at)) {
      try {
        await persistQueuedEmbedOperation(op);
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
  })().catch((error) => {
    console.error(
      "[EmbedSenders] Error flushing pending embed operations:",
      error,
    );
  }).finally(() => { pendingEmbedFlush = null; });
  return pendingEmbedFlush;
}

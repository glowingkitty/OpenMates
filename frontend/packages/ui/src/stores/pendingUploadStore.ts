/**
 * pendingUploadStore.ts
 *
 * Tracks messages that are "queued" because one or more of their embedded files
 * are still uploading, transcribing, or being processed by a backend skill.
 *
 * Architecture overview:
 *   When a user presses Send while file embeds are still in-flight, instead of
 *   blocking with a toast warning, we:
 *   1. Snapshot the editor state into a PendingSendContext (embed IDs, snapshot of
 *      the TipTap editor JSON, markdown text so far, chat ID, etc.)
 *   2. Display the message in the chat history immediately with
 *      status: "waiting_for_upload" so the user gets instant visual feedback
 *   3. Store the context here, keyed by chat ID
 *   4. Listen to embedUpdated events: when all blocking embeds finish, execute the
 *      deferred send automatically (in MessageInput.svelte)
 *
 * One pending context per chat: if the user sends a second message in the same chat
 * before the first one has dispatched, it is queued as a separate entry in the
 * pending FIFO queue for that chat.
 *
 * Upload progress:
 *   Each blocking embed's XHR upload progress (0–100%) is stored here so the
 *   ChatMessage component can display a live progress indicator under the
 *   "waiting_for_upload" message.
 */

import { writable, get } from "svelte/store";
import type { Editor } from "@tiptap/core";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Per-embed upload progress entry.
 * Tracks the percentage (0–100) for each in-flight upload so ChatMessage can
 * render an accurate live progress bar.
 */
export interface EmbedProgress {
  /** The embed's TipTap node attr id (= the local embed UUID) */
  embedId: string;
  /** "uploading" | "transcribing" | "processing" | "finished" | "error" */
  status: string;
  /** Upload progress 0–100. Only meaningful for status === "uploading". */
  uploadPercent: number;
  /** Human-readable filename or type label (e.g. "photo.jpg", "Recording") */
  label: string;
}

/**
 * A deferred send that is waiting for one or more embeds to finish.
 *
 * Created by sendHandlers.ts when the send guard detects blocking embeds.
 * Consumed (and removed) by MessageInput.svelte once all embeds are done.
 */
export interface PendingSendContext {
  /** Unique ID for this pending send (used to correlate with the displayed message) */
  pendingId: string;
  /** Chat ID this message belongs to */
  chatId: string;
  /** The message_id already written to IndexedDB with status "waiting_for_upload" */
  messageId: string;
  /**
   * Snapshot of the TipTap editor JSON at the time the user pressed Send.
   * The deferred sender uses this to serialize the final markdown once all
   * uploads have completed (the node attrs will have been updated by then).
   */
  editorSnapshot: unknown;
  /**
   * Set of embed IDs (TipTap node attr `id`) that were blocking the send.
   * Entries are removed as each embed transitions to "finished".
   * When this set is empty the deferred send fires.
   */
  blockingEmbedIds: Set<string>;
  /** Per-embed progress information for the UI (keyed by embed ID) */
  embedProgress: Map<string, EmbedProgress>;
  /** Unix timestamp (ms) when the pending send was created */
  createdAt: number;
  /** PII exclusions captured at send time (passed through to the actual send) */
  piiExclusions: Set<string>;
  /** Original PII-anonymized markdown text (partial — may be updated when embeds finish) */
  partialMarkdown: string;
}

/**
 * The store state: a map from chatId → ordered queue of pending sends.
 * The FIFO queue handles the case where the user sends multiple messages
 * in the same chat before the first one has dispatched.
 */
export type PendingUploadState = Map<string, PendingSendContext[]>;

// ---------------------------------------------------------------------------
// Store
// ---------------------------------------------------------------------------

/**
 * Internal writable store. Components should use the exported helper functions
 * rather than subscribing to this directly.
 */
const _store = writable<PendingUploadState>(new Map());

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Add a new pending send context to the queue for a chat.
 * Called by sendHandlers.ts right after the message is saved to IndexedDB.
 */
export function addPendingSend(context: PendingSendContext): void {
  _store.update((state) => {
    const queue = state.get(context.chatId) ?? [];
    queue.push(context);
    state.set(context.chatId, queue);
    console.debug(
      `[PendingUploadStore] Added pending send ${context.pendingId} for chat ${context.chatId.slice(-6)}, blocking embeds:`,
      Array.from(context.blockingEmbedIds),
    );
    return new Map(state); // return new map reference for reactivity
  });
}

/**
 * Remove a specific pending send context (after it has been dispatched or cancelled).
 */
export function removePendingSend(chatId: string, pendingId: string): void {
  _store.update((state) => {
    const queue = state.get(chatId);
    if (!queue) return state;
    const filtered = queue.filter((ctx) => ctx.pendingId !== pendingId);
    if (filtered.length === 0) {
      state.delete(chatId);
    } else {
      state.set(chatId, filtered);
    }
    console.debug(
      `[PendingUploadStore] Removed pending send ${pendingId} for chat ${chatId.slice(-6)}`,
    );
    return new Map(state);
  });
}

/**
 * Get the head (first/oldest) pending send for a chat, or undefined if none.
 * The head is the first to be dispatched.
 */
export function getHeadPendingSend(
  chatId: string,
): PendingSendContext | undefined {
  const state = get(_store);
  const queue = state.get(chatId);
  return queue?.[0];
}

/**
 * Get ALL pending sends for a chat (in send order).
 */
export function getAllPendingSends(chatId: string): PendingSendContext[] {
  const state = get(_store);
  return state.get(chatId) ?? [];
}

/**
 * Update the upload progress for a specific embed across ALL pending sends
 * for a given chat (since an embed belongs to exactly one pending send, but
 * we don't want to search all queues from the caller's side).
 */
export function updateEmbedProgress(
  chatId: string,
  embedId: string,
  update: Partial<EmbedProgress>,
): void {
  _store.update((state) => {
    const queue = state.get(chatId);
    if (!queue) return state;

    let changed = false;
    for (const ctx of queue) {
      const existing = ctx.embedProgress.get(embedId);
      if (existing) {
        Object.assign(existing, update);
        changed = true;
        break; // embed belongs to exactly one pending send
      }
    }

    if (!changed) return state;
    return new Map(state); // trigger reactivity
  });
}

/**
 * Mark an embed as finished within any pending send for the given chat.
 * Removes the embed from the blocking set. If the blocking set becomes empty
 * the pending send is ready to fire (caller is responsible for checking).
 *
 * @returns The pending send context that was updated, if any.
 */
export function markEmbedFinished(
  chatId: string,
  embedId: string,
): PendingSendContext | undefined {
  let updatedContext: PendingSendContext | undefined;

  _store.update((state) => {
    const queue = state.get(chatId);
    if (!queue) return state;

    for (const ctx of queue) {
      if (ctx.blockingEmbedIds.has(embedId)) {
        ctx.blockingEmbedIds.delete(embedId);
        // Update the progress entry to "finished"
        const prog = ctx.embedProgress.get(embedId);
        if (prog) {
          prog.status = "finished";
          prog.uploadPercent = 100;
        }
        updatedContext = ctx;
        console.debug(
          `[PendingUploadStore] Embed ${embedId.slice(-6)} finished for pending send ${ctx.pendingId} in chat ${chatId.slice(-6)}. Remaining blocking: ${ctx.blockingEmbedIds.size}`,
        );
        break;
      }
    }

    return new Map(state);
  });

  return updatedContext;
}

/**
 * Mark an embed as errored. The pending send is NOT unblocked — an error
 * means the message should still not be sent (the embed is broken).
 * The UI will show "Upload failed" for that embed.
 */
export function markEmbedError(chatId: string, embedId: string): void {
  _store.update((state) => {
    const queue = state.get(chatId);
    if (!queue) return state;

    for (const ctx of queue) {
      const prog = ctx.embedProgress.get(embedId);
      if (prog) {
        prog.status = "error";
        // Keep the embed in the blocking set so the send doesn't fire with a broken embed
        break;
      }
    }

    return new Map(state);
  });
}

/**
 * Check if a pending send for the given chat is ready to fire (all blocking
 * embeds have finished). Returns the ready context or undefined.
 */
export function getReadyPendingSend(
  chatId: string,
): PendingSendContext | undefined {
  const state = get(_store);
  const queue = state.get(chatId);
  if (!queue || queue.length === 0) return undefined;

  // The head must be ready first (FIFO order — don't skip ahead)
  const head = queue[0];
  if (head.blockingEmbedIds.size === 0) {
    return head;
  }
  return undefined;
}

/**
 * Cancel (remove) all pending sends for a chat.
 * Called when the user navigates away from a chat while uploads are still
 * in progress AND the user explicitly cancels, or when a chat is deleted.
 *
 * NOTE: This does NOT cancel the actual uploads — it only removes the pending
 * send so the message won't be dispatched. The upload may still complete in
 * the background (the embed node attrs will be updated regardless).
 */
export function cancelAllPendingSends(chatId: string): void {
  _store.update((state) => {
    if (state.has(chatId)) {
      state.delete(chatId);
      console.debug(
        `[PendingUploadStore] Cancelled all pending sends for chat ${chatId.slice(-6)}`,
      );
    }
    return new Map(state);
  });
}

/**
 * Check if there are any pending sends queued for a chat.
 */
export function hasPendingSends(chatId: string): boolean {
  const state = get(_store);
  const queue = state.get(chatId);
  return !!queue && queue.length > 0;
}

/**
 * Get a flat list of all embed IDs that are currently blocking any pending send
 * across ALL chats. Used by embed update handlers to know which embeds to watch.
 */
export function getAllBlockingEmbedIds(): Set<string> {
  const state = get(_store);
  const result = new Set<string>();
  Array.from(state.values()).forEach((queue) => {
    queue.forEach((ctx) => {
      Array.from(ctx.blockingEmbedIds).forEach((id) => result.add(id));
    });
  });
  return result;
}

/**
 * Find which chat ID and pending send context contains the given embed ID.
 * Used by embed update listeners to route the update to the correct pending send.
 *
 * @returns { chatId, context } or undefined if not found.
 */
export function findPendingSendByEmbedId(
  embedId: string,
): { chatId: string; context: PendingSendContext } | undefined {
  const state = get(_store);
  let found: { chatId: string; context: PendingSendContext } | undefined;
  Array.from(state.entries()).forEach(([chatId, queue]) => {
    if (found) return;
    queue.forEach((ctx) => {
      if (
        !found &&
        (ctx.blockingEmbedIds.has(embedId) || ctx.embedProgress.has(embedId))
      ) {
        found = { chatId, context: ctx };
      }
    });
  });
  return found;
}

// Export the raw store for components that need to subscribe reactively
// (e.g. ChatMessage to render progress bars).
export const pendingUploadStore = {
  subscribe: _store.subscribe,
};

// shareMetadataQueue.ts
// Service for queuing and retrying OG metadata updates when offline

import { chatDB } from "./db";
import { getApiEndpoint } from "../config/api";
import { authStore } from "../stores/authStore";
import { websocketStatus } from "../stores/websocketStatusStore";
import { webSocketService } from "./websocketService";
import { get } from "svelte/store";

/**
 * Interface for pending OG metadata update (for chats)
 */
export interface PendingOGMetadataUpdate {
  update_id: string; // Unique ID for this update
  chat_id: string;
  title: string | null;
  summary: string | null;
  created_at: number; // Unix timestamp
  retry_count: number; // Number of retry attempts
}

/**
 * Interface for pending embed share metadata update
 */
export interface PendingEmbedShareUpdate {
  update_id: string; // Unique ID for this update
  embed_id: string;
  is_shared: boolean;
  title?: string | null;
  description?: string | null;
  created_at: number; // Unix timestamp
  retry_count: number; // Number of retry attempts
}

/**
 * Service for managing offline OG metadata updates
 * Queues updates when offline and retries when connection is restored
 */
class ShareMetadataQueueService {
  private readonly STORE_NAME = "pending_og_metadata_updates";
  private readonly EMBED_STORE_NAME = "pending_embed_share_updates";
  private readonly MAX_RETRY_COUNT = 5; // Maximum retry attempts before giving up
  private retryInterval: NodeJS.Timeout | null = null;
  private readonly RETRY_INTERVAL = 10000; // Retry every 10 seconds when offline
  private isRetrying = false;
  private unsubscribeWebSocketStatus: (() => void) | null = null;
  private wasConnected = false; // Track previous connection state to detect reconnection

  /**
   * Initialize the service and set up retry listeners
   */
  init(): void {
    // Initialize wasConnected with current state
    const currentStatus = get(websocketStatus);
    this.wasConnected = currentStatus.status === "connected";

    // Listen for network online events
    if (typeof window !== "undefined") {
      window.addEventListener("online", () => {
        console.debug(
          "[ShareMetadataQueue] Network online event detected - retrying pending OG metadata updates",
        );
        this.retryPendingUpdates();
      });
    }

    // Listen for WebSocket reconnection events
    // When WebSocket reconnects, it means we have network connectivity
    this.unsubscribeWebSocketStatus = websocketStatus.subscribe((status) => {
      const isConnected = status.status === "connected";

      // Detect reconnection (was disconnected, now connected)
      if (isConnected && !this.wasConnected) {
        console.debug(
          "[ShareMetadataQueue] WebSocket reconnected - retrying pending OG metadata updates",
        );
        // Small delay to ensure WebSocket is fully ready
        setTimeout(() => {
          this.retryPendingUpdates();
        }, 1000);
      }

      this.wasConnected = isConnected;
    });

    // Also listen to WebSocket 'open' events as a backup
    webSocketService.on("open", () => {
      console.debug(
        "[ShareMetadataQueue] WebSocket open event - retrying pending OG metadata updates",
      );
      setTimeout(() => {
        this.retryPendingUpdates();
      }, 1000);
    });

    // Start periodic retry when offline
    this.startPeriodicRetry();
  }

  /**
   * Cleanup listeners (for testing or shutdown)
   */
  destroy(): void {
    this.stopPeriodicRetry();
    if (this.unsubscribeWebSocketStatus) {
      this.unsubscribeWebSocketStatus();
      this.unsubscribeWebSocketStatus = null;
    }
  }

  /**
   * Queue an OG metadata update for retry
   * Stores the update in IndexedDB for persistence
   */
  async queueUpdate(
    chatId: string,
    title: string | null,
    summary: string | null,
  ): Promise<void> {
    try {
      const update: PendingOGMetadataUpdate = {
        update_id: crypto.randomUUID(),
        chat_id: chatId,
        title,
        summary,
        created_at: Math.floor(Date.now() / 1000),
        retry_count: 0,
      };

      await this.storePendingUpdate(update);
      console.debug(
        "[ShareMetadataQueue] Queued OG metadata update for chat:",
        chatId,
      );
    } catch (error) {
      console.error(
        "[ShareMetadataQueue] Error queueing OG metadata update:",
        error,
      );
    }
  }

  /**
   * Store pending update in IndexedDB
   */
  private async storePendingUpdate(
    update: PendingOGMetadataUpdate,
  ): Promise<void> {
    try {
      await chatDB.init();
      const transaction = await chatDB.getTransaction(
        [this.STORE_NAME],
        "readwrite",
      );
      const store = transaction.objectStore(this.STORE_NAME);

      // For same chat_id, we want to replace the old update with the new one
      // First, delete any existing updates for this chat_id
      const index = store.index("chat_id");
      const existingRequest = index.getAll(update.chat_id);

      await new Promise<void>((resolve, reject) => {
        existingRequest.onsuccess = () => {
          const existing = existingRequest.result || [];
          // Delete existing updates for this chat_id
          for (const existingUpdate of existing) {
            store.delete(existingUpdate.update_id);
          }
          // Then add the new update
          const putRequest = store.put(update);
          putRequest.onsuccess = () => resolve();
          putRequest.onerror = () => reject(putRequest.error);
        };
        existingRequest.onerror = () => reject(existingRequest.error);
      });

      // Wait for transaction to complete
      await new Promise<void>((resolve, reject) => {
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error);
      });

      console.debug(
        "[ShareMetadataQueue] Stored pending OG metadata update:",
        update.update_id,
      );
    } catch (error) {
      console.error(
        "[ShareMetadataQueue] Error storing pending update:",
        error,
      );
      throw error;
    }
  }

  /**
   * Get all pending updates from IndexedDB
   */
  private async getPendingUpdates(): Promise<PendingOGMetadataUpdate[]> {
    try {
      await chatDB.init();
      const transaction = await chatDB.getTransaction(
        [this.STORE_NAME],
        "readonly",
      );
      const store = transaction.objectStore(this.STORE_NAME);

      return new Promise<PendingOGMetadataUpdate[]>((resolve, reject) => {
        const request = store.getAll();
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
      });
    } catch (error) {
      console.error(
        "[ShareMetadataQueue] Error getting pending updates:",
        error,
      );
      return [];
    }
  }

  /**
   * Delete a pending update after successful retry
   */
  private async deletePendingUpdate(updateId: string): Promise<void> {
    try {
      await chatDB.init();
      const transaction = await chatDB.getTransaction(
        [this.STORE_NAME],
        "readwrite",
      );
      const store = transaction.objectStore(this.STORE_NAME);

      await new Promise<void>((resolve, reject) => {
        const request = store.delete(updateId);
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
      });

      // Wait for transaction to complete
      await new Promise<void>((resolve, reject) => {
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error);
      });

      console.debug("[ShareMetadataQueue] Deleted pending update:", updateId);
    } catch (error) {
      console.error(
        "[ShareMetadataQueue] Error deleting pending update:",
        error,
      );
    }
  }

  /**
   * Retry all pending OG metadata updates
   * Called when network comes back online or WebSocket reconnects
   */
  async retryPendingUpdates(): Promise<void> {
    // Prevent concurrent retry attempts
    if (this.isRetrying) {
      console.debug("[ShareMetadataQueue] Retry already in progress, skipping");
      return;
    }

    // Only retry if user is authenticated
    if (!get(authStore).isAuthenticated) {
      console.debug(
        "[ShareMetadataQueue] User not authenticated, skipping retry",
      );
      return;
    }

    this.isRetrying = true;

    try {
      const pendingUpdates = await this.getPendingUpdates();

      if (pendingUpdates.length === 0) {
        console.debug(
          "[ShareMetadataQueue] No pending OG metadata updates to retry",
        );
        this.isRetrying = false;
        return;
      }

      console.info(
        `[ShareMetadataQueue] Retrying ${pendingUpdates.length} pending OG metadata update(s)...`,
      );

      // Retry each update
      for (const update of pendingUpdates) {
        try {
          // Check if we've exceeded max retry count
          if (update.retry_count >= this.MAX_RETRY_COUNT) {
            console.warn(
              `[ShareMetadataQueue] Update ${update.update_id} exceeded max retry count, removing`,
            );
            await this.deletePendingUpdate(update.update_id);
            continue;
          }

          // Attempt to send the update (always include is_shared=true for retries)
          const success = await this.sendOGMetadataUpdate(
            update.chat_id,
            update.title,
            update.summary,
            true, // is_shared = true
          );

          if (success) {
            // Success - delete the pending update
            console.debug(
              `[ShareMetadataQueue] Successfully sent OG metadata update for chat ${update.chat_id}`,
            );
            await this.deletePendingUpdate(update.update_id);
          } else {
            // Failed - increment retry count and update
            update.retry_count++;
            await this.storePendingUpdate(update);
            console.debug(
              `[ShareMetadataQueue] Failed to send update ${update.update_id}, retry count: ${update.retry_count}`,
            );
          }
        } catch (error) {
          console.error(
            `[ShareMetadataQueue] Error retrying update ${update.update_id}:`,
            error,
          );
          // Increment retry count and continue
          update.retry_count++;
          await this.storePendingUpdate(update);
        }
      }
    } catch (error) {
      console.error(
        "[ShareMetadataQueue] Error in retryPendingUpdates:",
        error,
      );
    } finally {
      this.isRetrying = false;
    }
  }

  /**
   * Send OG metadata update to server
   * Returns true if successful, false otherwise
   */
  private async sendOGMetadataUpdate(
    chatId: string,
    title: string | null,
    summary: string | null,
    isShared: boolean = true,
  ): Promise<boolean> {
    try {
      const response = await fetch(getApiEndpoint("/v1/share/chat/metadata"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          Origin: window.location.origin,
        },
        body: JSON.stringify({
          chat_id: chatId,
          title: title || null,
          summary: summary || null,
          is_shared: isShared, // Mark chat as shared on server
        }),
        credentials: "include",
      });

      if (!response.ok) {
        const errorData = await response
          .json()
          .catch(() => ({ detail: "Unknown error" }));
        console.warn("[ShareMetadataQueue] Server returned error:", errorData);
        return false;
      }

      const data = await response.json();
      return data.success === true;
    } catch (error) {
      // Network error - will be retried
      console.debug(
        "[ShareMetadataQueue] Network error sending OG metadata update:",
        error,
      );
      return false;
    }
  }

  // ========================
  // Embed Share Queue Methods
  // ========================

  /**
   * Queue an embed share metadata update for retry
   * Stores the update in IndexedDB for persistence
   */
  async queueEmbedShareUpdate(
    embedId: string,
    isShared: boolean,
    title?: string | null,
    description?: string | null,
  ): Promise<void> {
    try {
      const update: PendingEmbedShareUpdate = {
        update_id: crypto.randomUUID(),
        embed_id: embedId,
        is_shared: isShared,
        title,
        description,
        created_at: Math.floor(Date.now() / 1000),
        retry_count: 0,
      };

      await this.storeEmbedPendingUpdate(update);
      console.debug(
        "[ShareMetadataQueue] Queued embed share update for embed:",
        embedId,
      );

      // Immediately attempt to send (non-blocking)
      this.sendEmbedShareUpdate(embedId, isShared, title, description).then(
        (success) => {
          if (success) {
            this.deleteEmbedPendingUpdate(update.update_id);
          }
        },
      );
    } catch (error) {
      console.error(
        "[ShareMetadataQueue] Error queueing embed share update:",
        error,
      );
    }
  }

  /**
   * Store pending embed update in IndexedDB
   */
  private async storeEmbedPendingUpdate(
    update: PendingEmbedShareUpdate,
  ): Promise<void> {
    try {
      await chatDB.init();

      // Check if the store exists; if not, skip (store may not be created yet)
      if (
        !chatDB.db ||
        !chatDB.db.objectStoreNames.contains(this.EMBED_STORE_NAME)
      ) {
        console.debug(
          "[ShareMetadataQueue] Embed store not yet created, skipping store",
        );
        return;
      }

      const transaction = await chatDB.getTransaction(
        [this.EMBED_STORE_NAME],
        "readwrite",
      );
      const store = transaction.objectStore(this.EMBED_STORE_NAME);

      // For same embed_id, we want to replace the old update with the new one
      const index = store.index("embed_id");
      const existingRequest = index.getAll(update.embed_id);

      await new Promise<void>((resolve, reject) => {
        existingRequest.onsuccess = () => {
          const existing = existingRequest.result || [];
          // Delete existing updates for this embed_id
          for (const existingUpdate of existing) {
            store.delete(existingUpdate.update_id);
          }
          // Then add the new update
          const putRequest = store.put(update);
          putRequest.onsuccess = () => resolve();
          putRequest.onerror = () => reject(putRequest.error);
        };
        existingRequest.onerror = () => reject(existingRequest.error);
      });

      // Wait for transaction to complete
      await new Promise<void>((resolve, reject) => {
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error);
      });

      console.debug(
        "[ShareMetadataQueue] Stored pending embed share update:",
        update.update_id,
      );
    } catch (error) {
      console.error(
        "[ShareMetadataQueue] Error storing pending embed update:",
        error,
      );
      // Don't throw - we still try to send immediately
    }
  }

  /**
   * Get all pending embed updates from IndexedDB
   */
  private async getEmbedPendingUpdates(): Promise<PendingEmbedShareUpdate[]> {
    try {
      await chatDB.init();

      // Check if the store exists
      if (
        !chatDB.db ||
        !chatDB.db.objectStoreNames.contains(this.EMBED_STORE_NAME)
      ) {
        return [];
      }

      const transaction = await chatDB.getTransaction(
        [this.EMBED_STORE_NAME],
        "readonly",
      );
      const store = transaction.objectStore(this.EMBED_STORE_NAME);

      return new Promise<PendingEmbedShareUpdate[]>((resolve, reject) => {
        const request = store.getAll();
        request.onsuccess = () => resolve(request.result || []);
        request.onerror = () => reject(request.error);
      });
    } catch (error) {
      console.error(
        "[ShareMetadataQueue] Error getting pending embed updates:",
        error,
      );
      return [];
    }
  }

  /**
   * Delete a pending embed update after successful retry
   */
  private async deleteEmbedPendingUpdate(updateId: string): Promise<void> {
    try {
      await chatDB.init();

      // Check if the store exists
      if (
        !chatDB.db ||
        !chatDB.db.objectStoreNames.contains(this.EMBED_STORE_NAME)
      ) {
        return;
      }

      const transaction = await chatDB.getTransaction(
        [this.EMBED_STORE_NAME],
        "readwrite",
      );
      const store = transaction.objectStore(this.EMBED_STORE_NAME);

      await new Promise<void>((resolve, reject) => {
        const request = store.delete(updateId);
        request.onsuccess = () => resolve();
        request.onerror = () => reject(request.error);
      });

      // Wait for transaction to complete
      await new Promise<void>((resolve, reject) => {
        transaction.oncomplete = () => resolve();
        transaction.onerror = () => reject(transaction.error);
      });

      console.debug(
        "[ShareMetadataQueue] Deleted pending embed update:",
        updateId,
      );
    } catch (error) {
      console.error(
        "[ShareMetadataQueue] Error deleting pending embed update:",
        error,
      );
    }
  }

  /**
   * Retry all pending embed share updates
   * Called when network comes back online or WebSocket reconnects
   */
  private async retryPendingEmbedUpdates(): Promise<void> {
    // Only retry if user is authenticated
    if (!get(authStore).isAuthenticated) {
      return;
    }

    try {
      const pendingUpdates = await this.getEmbedPendingUpdates();

      if (pendingUpdates.length === 0) {
        return;
      }

      console.info(
        `[ShareMetadataQueue] Retrying ${pendingUpdates.length} pending embed share update(s)...`,
      );

      // Retry each update
      for (const update of pendingUpdates) {
        try {
          // Check if we've exceeded max retry count
          if (update.retry_count >= this.MAX_RETRY_COUNT) {
            console.warn(
              `[ShareMetadataQueue] Embed update ${update.update_id} exceeded max retry count, removing`,
            );
            await this.deleteEmbedPendingUpdate(update.update_id);
            continue;
          }

          // Attempt to send the update
          const success = await this.sendEmbedShareUpdate(
            update.embed_id,
            update.is_shared,
            update.title,
            update.description,
          );

          if (success) {
            console.debug(
              `[ShareMetadataQueue] Successfully sent embed share update for embed ${update.embed_id}`,
            );
            await this.deleteEmbedPendingUpdate(update.update_id);
          } else {
            // Failed - increment retry count and update
            update.retry_count++;
            await this.storeEmbedPendingUpdate(update);
            console.debug(
              `[ShareMetadataQueue] Failed to send embed update ${update.update_id}, retry count: ${update.retry_count}`,
            );
          }
        } catch (error) {
          console.error(
            `[ShareMetadataQueue] Error retrying embed update ${update.update_id}:`,
            error,
          );
          // Increment retry count and continue
          update.retry_count++;
          await this.storeEmbedPendingUpdate(update);
        }
      }
    } catch (error) {
      console.error(
        "[ShareMetadataQueue] Error in retryPendingEmbedUpdates:",
        error,
      );
    }
  }

  /**
   * Send embed share metadata update to server
   * Returns true if successful, false otherwise
   */
  private async sendEmbedShareUpdate(
    embedId: string,
    isShared: boolean,
    title?: string | null,
    description?: string | null,
  ): Promise<boolean> {
    try {
      const response = await fetch(getApiEndpoint("/v1/share/embed/metadata"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          Origin: window.location.origin,
        },
        body: JSON.stringify({
          embed_id: embedId,
          is_shared: isShared,
          title: title || null,
          description: description || null,
        }),
        credentials: "include",
      });

      if (!response.ok) {
        const errorData = await response
          .json()
          .catch(() => ({ detail: "Unknown error" }));
        console.warn(
          "[ShareMetadataQueue] Server returned error for embed update:",
          errorData,
        );
        return false;
      }

      const data = await response.json();
      return data.success === true;
    } catch (error) {
      // Network error - will be retried
      console.debug(
        "[ShareMetadataQueue] Network error sending embed share update:",
        error,
      );
      return false;
    }
  }

  /**
   * Start periodic retry when offline
   * Checks for pending updates and retries them periodically
   */
  private startPeriodicRetry(): void {
    // Clear any existing interval
    if (this.retryInterval) {
      clearInterval(this.retryInterval);
    }

    // Start periodic retry
    this.retryInterval = setInterval(async () => {
      // Only retry if user is authenticated
      if (!get(authStore).isAuthenticated) {
        return;
      }

      // Check if we're online (navigator.onLine is a simple check)
      if (typeof navigator !== "undefined" && navigator.onLine) {
        // Try to retry pending updates (both chat and embed)
        await this.retryPendingUpdates();
        await this.retryPendingEmbedUpdates();
      }
    }, this.RETRY_INTERVAL);

    console.debug(
      "[ShareMetadataQueue] Started periodic retry for pending OG metadata updates",
    );
  }

  /**
   * Stop periodic retry
   */
  stopPeriodicRetry(): void {
    if (this.retryInterval) {
      clearInterval(this.retryInterval);
      this.retryInterval = null;
      console.debug("[ShareMetadataQueue] Stopped periodic retry");
    }
  }
}

// Export singleton instance
export const shareMetadataQueue = new ShareMetadataQueueService();

// Initialize on module load
if (typeof window !== "undefined") {
  shareMetadataQueue.init();
}

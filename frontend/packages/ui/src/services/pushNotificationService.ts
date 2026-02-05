// frontend/packages/ui/src/services/pushNotificationService.ts
/**
 * @file pushNotificationService.ts
 * @description Service for managing Web Push notifications, including permission requests,
 * subscription management, and notification display.
 *
 * This service handles:
 * - Requesting notification permission from the browser
 * - Creating and managing push subscriptions
 * - Sending subscription to the server
 * - Displaying local notifications (for in-app triggers)
 * - Platform-specific handling (iOS PWA, etc.)
 */

import {
  pushNotificationStore,
  type NotificationPermission,
} from "../stores/pushNotificationStore";

// Browser check for SSR safety
const browser = typeof window !== "undefined";

/**
 * Options for displaying a push notification
 */
export interface PushNotificationOptions {
  /** Notification title */
  title: string;
  /** Notification body text */
  body: string;
  /** Icon URL (defaults to app icon) */
  icon?: string;
  /** Badge URL for mobile */
  badge?: string;
  /** Tag for notification grouping/replacement */
  tag?: string;
  /** Data to pass to click handler */
  data?: Record<string, unknown>;
  /** Whether to require interaction to dismiss */
  requireInteraction?: boolean;
  /** Actions to display (platform dependent) - uses web API NotificationAction type */
  actions?: Array<{ action: string; title: string; icon?: string }>;
}

/**
 * Result of a permission request
 */
export interface PermissionResult {
  /** Whether permission was granted */
  granted: boolean;
  /** The permission state */
  permission: NotificationPermission;
  /** Error message if request failed */
  error?: string;
}

/**
 * Result of a subscription operation
 */
export interface SubscriptionResult {
  /** Whether subscription was successful */
  success: boolean;
  /** The subscription object (if successful) */
  subscription?: PushSubscription;
  /** Error message if subscription failed */
  error?: string;
}

/**
 * Push notification service singleton
 */
class PushNotificationService {
  private serviceWorkerRegistration: ServiceWorkerRegistration | null = null;

  /**
   * Initialize the service
   * Should be called once on app startup
   */
  async initialize(): Promise<void> {
    if (!browser) return;

    // Refresh permission state from browser
    pushNotificationStore.refreshPermission();

    // Register service worker if supported
    if ("serviceWorker" in navigator) {
      try {
        this.serviceWorkerRegistration = await navigator.serviceWorker.ready;
        console.debug(
          "[PushNotificationService] Service worker ready:",
          this.serviceWorkerRegistration,
        );

        // Check for existing subscription
        const subscription =
          await this.serviceWorkerRegistration.pushManager.getSubscription();
        if (subscription) {
          pushNotificationStore.setSubscription(subscription);
          console.debug(
            "[PushNotificationService] Existing subscription found",
          );
        }
      } catch (error) {
        console.error(
          "[PushNotificationService] Service worker registration failed:",
          error,
        );
      }
    }
  }

  /**
   * Check if push notifications are supported on this platform
   */
  isSupported(): boolean {
    if (!browser) return false;
    return (
      "Notification" in window &&
      "serviceWorker" in navigator &&
      "PushManager" in window
    );
  }

  /**
   * Check if the app is running as an installed PWA
   */
  isPWA(): boolean {
    if (!browser) return false;
    return (
      window.matchMedia("(display-mode: standalone)").matches ||
      (window.navigator as Navigator & { standalone?: boolean }).standalone ===
        true
    );
  }

  /**
   * Check if the platform is iOS
   */
  isIOS(): boolean {
    if (!browser) return false;
    return (
      /iPad|iPhone|iPod/.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
    );
  }

  /**
   * Request notification permission from the browser
   * Returns the result of the permission request
   */
  async requestPermission(): Promise<PermissionResult> {
    if (!browser) {
      return { granted: false, permission: "default", error: "Not in browser" };
    }

    if (!("Notification" in window)) {
      return {
        granted: false,
        permission: "denied",
        error: "Notifications not supported",
      };
    }

    // Check current permission
    const currentPermission = Notification.permission as NotificationPermission;
    if (currentPermission === "granted") {
      pushNotificationStore.setPermission("granted");
      return { granted: true, permission: "granted" };
    }

    if (currentPermission === "denied") {
      pushNotificationStore.setPermission("denied");
      return {
        granted: false,
        permission: "denied",
        error: "Notifications blocked by user",
      };
    }

    // Request permission
    try {
      const result = await Notification.requestPermission();
      const permission = result as NotificationPermission;
      pushNotificationStore.setPermission(permission);

      if (permission === "granted") {
        // Enable push notifications automatically when permission is granted
        pushNotificationStore.setEnabled(true);
        // Try to subscribe
        await this.subscribe();
      }

      return {
        granted: permission === "granted",
        permission,
      };
    } catch (error) {
      console.error(
        "[PushNotificationService] Permission request failed:",
        error,
      );
      return {
        granted: false,
        permission: "default",
        error:
          error instanceof Error ? error.message : "Permission request failed",
      };
    }
  }

  /**
   * Subscribe to push notifications
   * Requires permission to be granted first
   */
  async subscribe(): Promise<SubscriptionResult> {
    if (!browser) {
      return { success: false, error: "Not in browser" };
    }

    if (!this.serviceWorkerRegistration) {
      try {
        this.serviceWorkerRegistration = await navigator.serviceWorker.ready;
      } catch {
        return { success: false, error: "Service worker not available" };
      }
    }

    try {
      // Check if already subscribed
      let subscription =
        await this.serviceWorkerRegistration.pushManager.getSubscription();

      if (!subscription) {
        // Get VAPID public key from server
        // TODO: Fetch this from the server configuration
        const vapidPublicKey = await this.getVapidPublicKey();

        if (!vapidPublicKey) {
          return { success: false, error: "VAPID public key not available" };
        }

        // Subscribe to push
        subscription =
          await this.serviceWorkerRegistration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: this.urlBase64ToUint8Array(vapidPublicKey),
          });

        // Send subscription to server
        await this.sendSubscriptionToServer(subscription);
      }

      pushNotificationStore.setSubscription(subscription);
      console.debug(
        "[PushNotificationService] Subscribed to push notifications",
      );

      return { success: true, subscription };
    } catch (error) {
      console.error("[PushNotificationService] Subscription failed:", error);
      return {
        success: false,
        error: error instanceof Error ? error.message : "Subscription failed",
      };
    }
  }

  /**
   * Unsubscribe from push notifications
   */
  async unsubscribe(): Promise<boolean> {
    if (!browser) return false;

    const state = pushNotificationStore.getState();
    if (!state.subscription) return true;

    try {
      await state.subscription.unsubscribe();
      pushNotificationStore.setSubscription(null);

      // Notify server of unsubscription
      await this.removeSubscriptionFromServer(state.subscription);

      console.debug(
        "[PushNotificationService] Unsubscribed from push notifications",
      );
      return true;
    } catch (error) {
      console.error("[PushNotificationService] Unsubscribe failed:", error);
      return false;
    }
  }

  /**
   * Show a local notification (not from push)
   * Used for in-app notification triggers
   */
  async showNotification(options: PushNotificationOptions): Promise<boolean> {
    if (!browser) return false;

    const state = pushNotificationStore.getState();

    // Check if we have permission
    if (state.permission !== "granted") {
      console.debug(
        "[PushNotificationService] Cannot show notification: permission not granted",
      );
      return false;
    }

    // Check if notifications are enabled
    if (!state.enabled) {
      console.debug(
        "[PushNotificationService] Cannot show notification: notifications disabled",
      );
      return false;
    }

    try {
      // Use service worker to show notification (required for PWA)
      if (this.serviceWorkerRegistration) {
        // Build notification options - actions is supported by Service Worker API
        // but may not be in the base NotificationOptions type
        const notificationOptions: NotificationOptions & {
          actions?: Array<{ action: string; title: string; icon?: string }>;
        } = {
          body: options.body,
          icon: options.icon || "/icons/icon-192x192.png",
          badge: options.badge || "/icons/badge-72x72.png",
          tag: options.tag,
          data: options.data,
          requireInteraction: options.requireInteraction,
        };

        // Add actions if provided (Service Worker API supports this)
        if (options.actions) {
          notificationOptions.actions = options.actions;
        }

        await this.serviceWorkerRegistration.showNotification(
          options.title,
          notificationOptions,
        );
      } else {
        // Fallback to Notification API directly (no actions support)
        new Notification(options.title, {
          body: options.body,
          icon: options.icon || "/icons/icon-192x192.png",
          tag: options.tag,
          data: options.data,
          requireInteraction: options.requireInteraction,
        });
      }

      return true;
    } catch (error) {
      console.error(
        "[PushNotificationService] Failed to show notification:",
        error,
      );
      return false;
    }
  }

  /**
   * Show a notification for a new chat message
   */
  async showChatMessageNotification(
    chatId: string,
    chatTitle: string,
    messagePreview: string,
  ): Promise<boolean> {
    const state = pushNotificationStore.getState();

    // Check if new message notifications are enabled
    if (!state.preferences.newMessages) {
      return false;
    }

    return this.showNotification({
      title: chatTitle,
      body: messagePreview,
      tag: `chat-${chatId}`,
      data: {
        type: "chat_message",
        chatId,
      },
      requireInteraction: false,
    });
  }

  /**
   * Show a notification for a server event
   */
  async showServerEventNotification(
    title: string,
    message: string,
  ): Promise<boolean> {
    const state = pushNotificationStore.getState();

    // Check if server event notifications are enabled
    if (!state.preferences.serverEvents) {
      return false;
    }

    return this.showNotification({
      title,
      body: message,
      tag: "server-event",
      data: {
        type: "server_event",
      },
      requireInteraction: true,
    });
  }

  /**
   * Show a notification for a software update
   */
  async showSoftwareUpdateNotification(
    version: string,
    message: string,
  ): Promise<boolean> {
    const state = pushNotificationStore.getState();

    // Check if software update notifications are enabled
    if (!state.preferences.softwareUpdates) {
      return false;
    }

    return this.showNotification({
      title: `OpenMates ${version} Available`,
      body: message,
      tag: "software-update",
      data: {
        type: "software_update",
        version,
      },
      requireInteraction: true,
    });
  }

  /**
   * Get VAPID public key from server
   * TODO: Implement actual server fetch
   */
  private async getVapidPublicKey(): Promise<string | null> {
    // TODO: Fetch from server API endpoint
    // For now, return null to indicate not yet configured
    console.warn(
      "[PushNotificationService] VAPID public key not configured - server endpoint needed",
    );
    return null;
  }

  /**
   * Send subscription to server for push delivery
   */
  private async sendSubscriptionToServer(
    subscription: PushSubscription,
  ): Promise<void> {
    // TODO: Implement API call to send subscription to server
    console.debug(
      "[PushNotificationService] TODO: Send subscription to server",
      subscription.endpoint,
    );
  }

  /**
   * Remove subscription from server
   */
  private async removeSubscriptionFromServer(
    subscription: PushSubscription,
  ): Promise<void> {
    // TODO: Implement API call to remove subscription from server
    console.debug(
      "[PushNotificationService] TODO: Remove subscription from server",
      subscription.endpoint,
    );
  }

  /**
   * Convert VAPID key from base64 to ArrayBuffer
   * Returns ArrayBuffer to satisfy PushSubscriptionOptionsInit.applicationServerKey type
   */
  private urlBase64ToUint8Array(base64String: string): ArrayBuffer {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding)
      .replace(/-/g, "+")
      .replace(/_/g, "/");

    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);

    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }

    return outputArray.buffer;
  }
}

// Export singleton instance
export const pushNotificationService = new PushNotificationService();
